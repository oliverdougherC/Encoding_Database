# PL v7 retained E2E certification

`scripts/certify-v7-e2e.sh` is the release gate for PLA-90. It executes an actual
packaged client twice: once with a software encoder and once with an explicitly
named hardware encoder. It does not substitute a mock encoder and fails when the
hardware path is unavailable or unusable.

Each path uses the client's noninteractive `--v7-suite-clip` protocol runner,
including warmup and repeated measured runs. The default representative workload
is `sports-action-960x540-24p`; `--suite-clip` may select another canonical v1
clip without bypassing protocol validation.

The server and frontend must already be running against the same migrated
PostgreSQL database. The frontend must have `INTERNAL_API_BASE_URL` set to the
server URL and must not enable query mocks. Run from a clean `beta` commit:

```bash
export DATABASE_URL='postgresql://app:app@127.0.0.1:55432/benchmarks?schema=public'
scripts/certify-v7-e2e.sh \
  --hardware-encoder h264_videotoolbox \
  --server-url http://127.0.0.1:3001 \
  --frontend-url http://127.0.0.1:3100
```

On Linux use a hardware encoder that is both compiled in and backed by the host,
such as the host's verified VAAPI, QSV, or NVENC implementation. Merely appearing
in `ffmpeg -encoders` is insufficient: the packaged run itself must succeed.

Evidence is retained under `.test-reports/pl-v7-e2e/<commit>-<UTC timestamp>/`:

- `execution.json` binds the run to the exact beta commit and packaged-client hash.
- `software-client.log` and `hardware-client.log` retain the packaged executions.
- `authority-chain.json` contains immutable run, recipe, environment, artifact,
  authoritative quality-analysis, derived-result membership, server analytics,
  and frontend-proxy evidence.
- `SHA256SUMS` makes later alteration detectable.

Certification fails unless both paths are accepted, encoded artifacts are
retained with verified hashes, server VMAF distributions and canonical score
inputs are complete, each run belongs to a derived PL result, and the frontend
analytics response exactly matches the server response. A successful process
exit alone is never treated as certification evidence.
