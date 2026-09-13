# PL v7 retained E2E certification

`scripts/certify-v7-e2e.sh` is the release gate for PLA-90. It executes an actual
packaged client twice: once with a software encoder and once with an explicitly
named hardware encoder. It does not substitute a mock encoder and fails when the
hardware path is unavailable or unusable.

Each path uses the client's noninteractive `--v7-suite-clip` protocol runner,
including warmup and repeated measured runs. The default representative workload
is `sports-action-960x540-24p`; `--suite-clip` may select another canonical v1
clip without bypassing protocol validation.

The software path is routed through a local one-shot fault proxy. Its first
encoded-artifact upload receives an injected HTTP 503 after the request body is
consumed. Certification requires the packaged client to spool that submission,
replay it successfully for the same immutable BenchmarkRun, and leave no queued
payload behind. The recovered run must be accepted with a retained artifact and
complete authoritative analysis. Recovery can use a second upload or the
server's content-addressed deduplication when an identical artifact was retained
in the meantime. The proxy ledger and canonical recovery state are retained in
`upload-interruption.json`.

The server and frontend must already be running against the same migrated
PostgreSQL database. The frontend must have `INTERNAL_API_BASE_URL` set to the
server URL and must not enable query mocks. Run from a clean `beta` commit:

```bash
export DATABASE_URL='postgresql://app:app@127.0.0.1:55432/benchmarks?schema=public'
scripts/certify-v7-e2e.sh \
  --hardware-encoder h264_videotoolbox \
  --software-crf 24 \
  --hardware-target-bitrate-kbps 2500 \
  --server-url http://127.0.0.1:3001 \
  --frontend-url http://127.0.0.1:3100
```

For a calibration pilot, invoke the gate separately for every canonical clip and
every native rate-control point. The two rate-control flags are recorded in
`execution.json`; they are not converted into a synthetic cross-encoder quality
scale. A single invocation remains a path certificate, not a complete pilot.

On Linux use a hardware encoder that is both compiled in and backed by the host,
such as the host's verified VAAPI, QSV, or NVENC implementation. Merely appearing
in `ffmpeg -encoders` is insufficient: the packaged run itself must succeed.

Evidence is retained under `.test-reports/pl-v7-e2e/<commit>-<UTC timestamp>/`:

- `execution.json` binds the run to the exact beta commit and packaged-client hash.
- `software-client.log` and `hardware-client.log` retain the packaged executions.
- `authority-chain.json` contains immutable run, recipe, environment, artifact,
  authoritative quality-analysis, derived-result membership, server analytics,
  and frontend-proxy evidence. The verifier also reanalyzes one retained software
  artifact under a distinct worker identity and requires that exact new analysis
  to replace aggregate membership, proving retained-artifact recomputation.
- The verifier submits a separately identified byte-valid but structurally invalid
  `video/mp4` payload and requires an explicit rejected Artifact plus a
  rejected/invalid BenchmarkRun. That media is never reused as a canonical path.
- `SHA256SUMS` hashes every other evidence file and deliberately excludes itself,
  making later alteration detectable without a circular or empty-file digest.

Certification fails unless both paths are accepted, encoded artifacts are
retained with verified hashes, server VMAF distributions and canonical score
inputs are complete, each run belongs to a derived PL result, and the frontend
analytics response exactly matches the server response. A successful process
exit alone is never treated as certification evidence.

## Unscored canonical-suite beta candidate

The separate `scripts/certify-beta-corpus.sh` gate verifies collection before PL
calibration. The scored PLA-90 gate above remains unchanged. Run this candidate
gate from a clean committed candidate branch; it records the exact SHA and does
not require integration into `beta` first.

Start an isolated migrated server and its real frontend with
`PL_V7_REFERENCE_BITRATES_JSON` and `PL_V7_REFERENCE_CONTEXT_VERSION` blank and
`ALLOW_TEST_ONLY_REFERENCE_CONTEXTS=0`. Use those settings in the certification
shell too. The verifier records the shell configuration and independently
requires zero derived memberships and unavailable public PL; retain the server
launch configuration alongside deployment-review evidence to establish its
actual environment. Never enable test contexts to make this gate pass.

```bash
export DATABASE_URL='postgresql://app:app@127.0.0.1:55432/benchmarks?schema=public'
export ARTIFACT_STORAGE_ROOT='/absolute/path/to/server/retained-artifacts'
export PL_V7_REFERENCE_BITRATES_JSON=''
export PL_V7_REFERENCE_CONTEXT_VERSION=''
export ALLOW_TEST_ONLY_REFERENCE_CONTEXTS=0
scripts/certify-beta-corpus.sh --client ./encodingdb-client-macos \
  --suite-pack ./encodingdb-test-suite-v1.tar.gz \
  --server-url http://127.0.0.1:3001 --frontend-url http://127.0.0.1:3100
```

The binary must already be packaged from the committed candidate and the frozen
suite. The gate copies it and the exact external pack to a fresh installation,
starts with an empty cache, removes pack overrides, and invokes all seven IDs
from the final manifest using libx264/fast/CRF 24. Each invocation executes the
client's actual warmup/repetition protocol. A real proxy interrupts one upload;
the client must recover and empty its retry queue. This is adjacent-pack clean
installation evidence; network-only acquisition needs a separate executed check.

The verifier reads the actual database and retained artifact files (mount the
server storage into the verifier host when containerized). It requires repeated
accepted runs for every final clip, exact input hashes and suite identities,
retained bytes with matching SHA-256 and size, complete authoritative analyses
and full VMAF frame distributions. It reanalyzes one retained artifact, repeats
that request to check idempotence, and checks the retained analysis identity.
Both `/corpus` and frontend `/api/corpus` must expose matching repeated rows with
PL explicitly null and scoring status `UNSCORED_NO_PUBLIC_DERIVED_RESULT`.

Evidence under `.test-reports/beta-corpus/<SHA>-<timestamp>/` includes the actual
binary and pack, logs, fault ledger, execution identities, complete database and
HTTP evidence, and recursive `SHA256SUMS`. Publish that directory or a durable
archive and link it in the deployment review. Unit tests exercise verifier
rejection behavior only; they never constitute real benchmark certification.
