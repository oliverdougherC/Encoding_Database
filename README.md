Encoding Database
=================

Encoding Database is an open benchmarking platform for video encoding performance, quality, and efficiency. It combines:

- A cross-platform Python client that runs reproducible FFmpeg benchmarks.
- A Node/Express + Prisma API that validates, scores, and aggregates submissions.
- A Next.js frontend with comparison tools and leaderboards.

## Current release status

**1.3.0-rc.2 is the current published release** ([release](https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.3.0-rc.2),
client/0.3.1, protocol 7.1): packaged macOS DMG, Windows GUI executable and Linux
archive with verified SHA-256 digests on the [run page](/run). Collection readiness
and validated PL remain BLOCKED pending the remaining empirical gates; PL rows stay
unscored. 1.3.0-rc.1 stays published as superseded plain command-line builds.

The corrected candidate uses `client/0.3.0`, benchmark protocol `7.1`, and the
`ffmpeg-process-v1` encode timer. It preserves the frozen seven-clip Test Suite v1
and `vmaf-v1-sdr-1080p` model. The declared validation scope is 1920×1080, 24 fps,
SDR BT.709; 4K, HDR and HFR transfer are outside this release's validated scope.

- Ordinary CLI, Single and GUI contribution use the authoritative artifact flow,
  with bounded campaigns, checkpoints and independent upload resume.
- Intake checks complete frame coverage and timing consistency; admission,
  retries, leases and recomputation have PostgreSQL fault regressions.
- Exact-analysis reviews, immutable score contexts, disjoint fitting/holdout
  membership and hash-bound scoring/evidence policy remain release gates.
- Public rows distinguish accepted/suspect measurements, byte integrity,
  retention, PL availability and confidence. Sparse or incompatible rows remain
  provisional or ineligible even after a future calibrated release.

See [Final Release Handoff](docs/FINAL_RELEASE_HANDOFF.md) for executed evidence,
platform limits, remaining approvals and the exact promotion procedure. The
[integrated check receipt](docs/collection-readiness/integrated-4348ca8/receipt.json)
records 219 server, 217 client and 56 frontend tests for its stated source snapshot. Canonical
source acquisition, provenance and freeze are complete; no new filming is required.

## Why this project exists

Encoder performance claims are often hard to compare because workloads, settings, and hardware conditions differ. Encoding Database standardizes those dimensions (as best we can) so results are more comparable and useful in real-world decision making:

- Which encoder and preset is fastest on my class of hardware?
- What quality tradeoff am I buying for speed and output size?
- How much power and thermal headroom does a given encode path consume?

## System architecture

1. The client runs benchmark tasks against the versioned EncodingDB Test Suite v1 manifest.
2. The client executes native, fingerprinted recipes under the versioned benchmark protocol and captures performance and environment evidence.
3. The client uploads the encoded artifact through the v7 artifact API. Client-calculated quality is diagnostic only.
4. The server verifies the artifact, performs the pinned authoritative quality analysis, and rebuilds immutable, hardware-scoped derived results from accepted runs.
5. The frontend ranks canonical derived results and exposes PL, PL Fit, confidence, scope, Pareto, and valid BD-rate evidence.

## Repository layout

- `client/`: Python benchmark runner, hardware detection, FFmpeg orchestration, telemetry sampler.
- `server/`: Express API, Zod validation, Prisma models/migrations, ingest + query pipeline.
- `frontend/`: Next.js 16 app with benchmark table, analytics, leaderboards, and hardware pages.
- `nginx/`: reverse-proxy configuration for production.
- `scripts/`: consolidated operational scripts (`local_test.sh`, `client_test.sh`, `build_macos_client.sh`, `build_windows_client.ps1`).
- `client/resources/test_suite_v1/manifest.json`: machine-readable manifest for the seven-class EncodingDB Test Suite v1.
- `client/resources/test_suite_v1/suite-pack.json`: deterministic metadata for the external canonical-suite pack shipped with release clients.
- `client/ENCODINGDB_TEST_SUITE_V1.md`: provenance, licensing, and General PL coverage notes for the suite.

## Current platform capabilities

- Benchmark dimensions: codec/encoder, preset, explicit native rate-control structure, exact output recipe, content class, suite clip, and hardware environment.
- Core quality/performance: encode FPS, deterministic video-payload bitrate, full VMAF-v1 distribution, XPSNR, SSIM, and PSNR.
- Hardware telemetry: utilization, power, memory, temperatures, CPU frequency, process I/O and CPU time, battery state.
- Data integrity controls: canonical input hash checks, idempotent payload hash, accepted/suspect/rejected submission status.
- Aggregation model: immutable runs and analyses with robust medians, dispersion, confidence intervals, evidence tiers, and reproducible derived-result recomputation.
- Query API: filtering, sorting, ranges, pagination, derived efficiency metrics.
- Frontend analytics: scatter plots, histograms, rate-distortion, content/resolution comparisons, and PL Score v7 results when complete v7 evidence and frozen workload references are available.

## Telemetry and privacy

### Data collection policy

Benchmark payloads contain hardware/software context and a persistent random installation pseudonym used to distinguish physical-source evidence from repeated campaigns. They do not contain names or email addresses. Environment fingerprints and ordinary request logs can still be identifying; publication is opt-in.

Interactive client sessions ask once before the first publication and store that consent locally. Noninteractive CLI runs publish only when `--submit` is passed explicitly.

The client submits an explicit allowlist of fields. This prevents accidental inclusion of unrelated machine or user data.

The offline spool is also local and persistent:

- macOS: `~/Library/Application Support/EncodingDB/queue`
- Linux: `$XDG_STATE_HOME/EncodingDB/queue` or `~/.local/state/EncodingDB/queue`
- Windows: `%LOCALAPPDATA%\EncodingDB\queue`

Failed uploads remain in that queue until they are replayed or explicitly cleaned up.

### Operational logs

Benchmark payloads do not include direct account identity, but normal server request logs currently record standard operational metadata including the remote IP address, request path, response status, timing, and `User-Agent` header. This repository does not currently define a fixed retention period for those logs.

### Telemetry fields collected and why they matter

| Category | Fields | Why this is collected |
| --- | --- | --- |
| System profile | `cpuModel`, `gpuModel`, `ramGB`, `os` | Normalizes comparisons across hardware and OS environments. |
| Workload configuration | `codec`, `preset`, `crf`, `contentClass`, `resolution`, `passes` (fixed to `1`), `inputHash` | Ensures benchmark rows are compared only when workload settings are equivalent. |
| Core benchmark outcome | `fps`, `fileSizeBytes`, `vmaf`, `ssim`, `psnr`, `runMs` | Captures speed, size, and perceptual quality outcomes of each encode. |
| Runtime telemetry (efficiency) | `gpuUtilAvg`, `gpuPowerAvgW`, `gpuMemPeakMB`, `cpuUtilAvg`, `cpuUtilMax`, `peakMemoryMB`, `thermalThrottle` | Enables efficiency and stability analysis beyond raw FPS. |
| Extended telemetry | `gpuTempMaxC`, `cpuFreqAvgMHz`, `cpuTempMaxC`, `ffmpegCpuUtilAvg`, `ffmpegCpuUtilMax`, `ffmpegReadMB`, `ffmpegWriteMB`, `ffmpegCpuTimeS`, `batteryPercentStart`, `batteryPercentEnd`, `batteryPercentDrop`, `powerSource`, `sampleCount`, `monitorDurationMs` | Improves confidence scoring, thermal context, and power/runtime interpretation. |
| Tooling metadata | `ffmpegVersion`, `encoderName`, `clientVersion`, `notes` | Aids reproducibility and diagnostics of edge-case runs. |

For canonical V7 artifact-backed runs, environment fingerprints also include exact `physicalMemoryBytes`. Public `/corpus` `ramGB` values are derived from that physical-memory field and are never inferred from CPU core counts.

### What is not collected

- No names, emails, accounts, or profile identifiers.
- No location data.
- No browser cookies or advertising identifiers.
- No filesystem snapshots or unrelated personal files.
- No device serial numbers or MAC addresses in benchmark rows.

For authoritative V7 submissions, the client also uploads the encoded benchmark artifact itself so the server can run pinned analysis. That artifact may be retained in the local queue until upload succeeds or the user explicitly cleans up dead-letter state.

### Why telemetry is important

- It prevents misleading comparisons by preserving workload and hardware context.
- It enables efficiency metrics such as FPS/Watt and quality-per-watt.
- It improves outlier detection and submission confidence.
- It supports hardware recommendation and reliability analysis.

## Client downloads and candidate commands

Published **1.2.0 / client/0.2.0** downloads: [Windows GUI](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.2.0/encodingdb-client-windows.exe),
[Windows console](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.2.0/encodingdb-client-windows-console.exe),
[Linux](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.2.0/encodingdb-client-linux),
and [macOS](https://github.com/oliverdougherC/Encoding_Database/releases/download/1.2.0/encodingdb-client-macos).
These historical builds do not implement the corrected campaign interface below
and cannot establish the protocol 7.1 epoch. Their unsigned/notarization and
translated-helper limits remain in the published release notes.

Application candidate `b3ef24a` now has physical Windows seven-clip software and
NVENC evidence: 63 VALID attempts, 42 measured runs and 21 stable groups across
three campaigns, plus four controlled recovery/failure cases. Hosted Windows
seven-clip console acceptance also passed; final GUI acceptance remains pending.
The [Mac package smoke](docs/collection-readiness/mac-build-b3ef24a/README.md) passed
with native ARM64 helpers and a **macOS 27.0** runtime floor; signing is ad hoc,
with no Developer ID signature or notarization. Both b3 Mac seven-clip campaigns
finished: 46 artifacts verified, with two unstable software groups and six
GPU-suspect hardware measurements retained. Publication remains unverified.
The Linux candidate build, migrations,
trusted TLS and isolated restore passed; final native acceptance is now running
after the capacity trial. These results do not establish collection readiness or validated
PL. See the [current evidence and open gates](docs/FINAL_RELEASE_HANDOFF.md).

From the corrected source checkout with client requirements installed and a
compatible local staging server, run one clip without publication:

```bash
python -m client --base-url http://127.0.0.1:3001 --codec libx264 --presets fast --no-submit
```

Use `--campaign full` for all seven clips with the same recipe. This is separate
from the operator's much larger calibration matrix. The client prints a campaign
ID and enforces attempt, duration and retained-storage budgets. Keep other demanding
work off the measurement host; unsupported encoders fail without substitution.

```bash
python -m client --base-url http://127.0.0.1:3001 --codec libx264 --presets fast --campaign full --no-submit
python -m client --base-url http://127.0.0.1:3001 --resume-campaign CAMPAIGN_ID --no-submit
python -m client --base-url http://127.0.0.1:3001 --resume-campaign CAMPAIGN_ID --submit
python -m client --base-url http://127.0.0.1:3001 --upload-only
python -m client --queue-status
```

Publishing a completed campaign reuses retained measurements and artifacts; it does
not repeat the encode. An upload receipt means analysis is pending, not acceptance.
Offline/backpressured uploads remain queued. Acceptance, SUSPECT/review, rejection,
cancellation and local completion are distinct outcomes. Change the destination to
production only after the reviewed release and production gates are satisfied.

Other useful flags: `--max-attempts`, `--max-duration-minutes`, `--max-storage-mb`,
`--queue-dir`, `--local-metrics` (opt-in diagnostics), `--target-bitrate-kbps` for
native bitrate modes, `--gui`, `--cli` and `--menu`. Use the current candidate's
`python -m client --help`; do not apply these examples to the older downloads.

## Local development

### Prerequisites

- Node.js 20.9+ (CI uses Node 20)
- Docker (for Postgres)
- Python 3.11 (native CI baseline)

### Option A: one-command local stack

```bash
./scripts/local_test.sh
```

This script can stand up DB + API (+ frontend by default), apply migrations, seed test data, and run readiness checks.

To launch the client in its default interactive mode:

```bash
./scripts/client_test.sh
```

### Option B: manual setup

1. Configure env files from `env.example` and `server/env.example`.
2. Start Postgres:

```bash
docker compose up -d db
```

3. Start API:

```bash
cd server
npm ci
npm run build
npx prisma generate
npx prisma migrate deploy
npm run dev
```

4. Start frontend:

```bash
cd frontend
npm ci
cat > .env.local <<'EOF'
INTERNAL_API_BASE_URL=http://127.0.0.1:3001
APP_URL=http://127.0.0.1:3000
EOF
npm run dev
```

5. Run client locally:

```bash
cd client
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --no-submit
```

## API overview

- `POST /submit`: legacy diagnostic payload route; not canonical V7 contribution.
- `GET /query`: fetch accepted aggregate benchmarks with filter/sort/range params.
- `GET /test-videos`: list known benchmark clips.
- `GET /submit-token`, `GET /submit/token`, `GET /health/token`: optional short-lived token issuance.
- `GET /health`, `GET /health/live`, `GET /health/ready`: health checks.
- `POST /v7/benchmark-runs`: idempotently create immutable V7 run/artifact metadata.
- `POST /v7/benchmark-runs/:id/artifacts/ENCODED/upload-authorizations`: issue a short-lived, run-bound upload token.
- `PUT /v7/artifact-uploads/:token`: stream and verify the encoded canonical-suite artifact.
- `GET /v7/benchmark-runs/:id/artifacts/ENCODED/analysis-status`: inspect durable authoritative analysis state.
- `GET /corpus`: browse accepted/suspect V7 aggregates; PL remains unavailable without a validated production context.
- `GET /corpus/:id`: inspect one exact public aggregate.
- `GET /v7/compatibility`: check minimum client, protocol and timing boundary before measurement.
- `POST /v7/operator/analyses/:id/reviews`: authenticated operator adjudication bound to an exact analysis/artifact; credentials are never distributed in clients.
- `GET /health/v7-evidence`: machine-readable storage, queue, failed-analysis, and retained-object health.

## Ingest security modes

Legacy JSON ingest modes are configured via environment:

- `public`: unsigned submissions accepted; token optional.
- `signed`: HMAC signature required.
- `hybrid`: signed preferred; token fallback; unsigned compatibility fallback.

Additional controls:

- global and `/submit` rate limits,
- body size limits,
- optional proof-of-work challenge for token mode,
- replay protection for signatures.

V7 artifact authorization uses `ARTIFACT_UPLOAD_SECRET` only on the server to sign short-lived tokens bound to one immutable run, artifact role, SHA-256, size, content type, and expiry. This secret is never distributed in clients. Public clients request scoped tokens; streamed uploads are independently size/hash checked, rate/concurrency limited, capacity checked, and stored under server-derived content-addressed keys. The service accepts only artifacts produced from manifest-verified EncodingDB suite sources, not arbitrary personal media.

## Version identities

- Published project release: `1.3.0-rc.4` / `2026-09-22` in `release.json`; client/0.3.3, protocol `7.1`.
- Historical project release: `1.2.0` / `client/0.2.0`, protocol `7.0` (historical timing).
- Candidate client implementation/minimum version: `client/0.3.0`.
- Candidate benchmark protocol version: `7.1`, timer boundary `ffmpeg-process-v1`.
- PL formula version: `7.0`.
- Test-suite version: EncodingDB Test Suite v1 (`encodingdb-test-suite-v1`).

These identities are intentionally independent; the release manifest records each one rather than treating the project tag as the protocol or suite version.

## Frontend pages

- `/`: benchmark table with filters, compare panel, PL Score sorting.
- `/results/:id`: direct aggregate details, including measurement basis and retention.
- `/run`: downloads and actual candidate contribution commands.
- `/compare-encoders`: focused encoder comparison dashboard.
- `/leaderboards`: top encoders by speed/quality/compression/PL Score.
- `/hardware`: efficiency and hardware intelligence charts.
- `/plove`: legacy redirect to the current PL Score v7 methodology.

## Build packaged clients

macOS:

```bash
./scripts/build_macos_client.sh
```

Windows (PowerShell):

```powershell
.\scripts\build_windows_client.ps1
```

Linux:

```bash
./scripts/build_linux_client.sh
```

The Windows build now outputs two executables in the repository root:

- `encodingdb-client-windows.exe` (GUI-first for testers)
- `encodingdb-client-windows-console.exe` (console fallback/debug)

Packaged clients also bundle the pinned `vmaf-v1-sdr-1080p` model manifest and JSON under `client/resources/vmaf/`.
Packaging scripts expect platform FFmpeg/ffprobe binaries under `client/bin/<platform>/`.

## Testing and validation scripts

- `server/test/routes.smoke.test.js`: server smoke tests.
- `scripts/local_test.sh`: local DB/API/frontend bring-up with readiness checks.
- `scripts/client_test.sh`: launches the client in default interactive mode.

## Production deployment

Follow [Final Release Handoff](docs/FINAL_RELEASE_HANDOFF.md) for candidate
validation, human review, protected current-main integration, native release
artifacts, backup, deployment, production acceptance, and the evidence epoch.
The older beta-only stopping point is historical; the current goal includes both
dependable collection and empirically validated PL. Never promote an older beta
over newer main.

After separate production approval, configure env files from `env.example` and
`server/env.example`, complete the required backup, and deploy from a clean
checkout of the exact reviewed main SHA:

```bash
./deploy.sh --skip-pull
```

Verify and record the full checkout SHA before and after deployment.
`--skip-pull` prevents an automatic update; it does not verify the reviewed SHA
or a clean worktree. The default `./deploy.sh` fetches and pulls latest `main`,
which may have advanced since review. Do not substitute an unreviewed branch tip.

The deployment host needs Git, Node.js 20+, Docker with Compose v2, network
access to the pinned image/package registries and suite download URL, and disk
space for the 1.51 GB pack, verified cache, both resource trees, staging copies
and application images. Python, its pinned acquisition dependencies, FFmpeg and
ffprobe run in the isolated preparation image; no host Python/client installation
is required. `deploy.sh` acquires the committed frozen pack, validates archive,
clip, notice and tracked suite identities, materializes both trees, builds all
application images (including the server's source/model/media checks), and pulls
service images **before** starting or replacing any service. Preparation failures
exit before rollout; rollout uses prepared images with builds and pulls disabled.

`./deploy.sh --skip-pull --prepare-only` executes that preparation without starting
services. For a direct Compose build, first run
`bash scripts/prepare_production_suite.sh`; a bare clean-checkout server Docker
build deliberately refuses missing references. The verified cache defaults to
`.build/final-suite-cache`; `DEPLOY_SUITE_CACHE_DIR` selects another location.
For offline pack delivery use `DEPLOY_SUITE_PACK_PATH`, or select an exclusive
mirror with `DEPLOY_SUITE_PACK_URL`. These are mutually exclusive, must supply
the exact pinned pack, and fail without silently falling back to another source.
The offline option still needs the preparation/application images and their build
dependencies locally available or reachable.

Run `python3 scripts/test_clean_deployment.py` for the isolated clean-checkout
regression. It uses a fresh clone and empty suite cache, invokes the supported
deployment entry point, verifies all seven source hashes inside the image, and
checks that missing, unreachable and corrupt packs cannot change running services.
Its test volumes, network, ports and credentials are isolated from production.

Production env validation, named-volume backup/restore, pre-V7 migration
rehearsal, and the later PL activation procedure are documented in
[PL production activation](docs/PL_V7_PRODUCTION_ACTIVATION.md). Collection can
operate with PL unavailable after its own acceptance gate, but the full release
objective and PLA-70 remain open until calibrated PL also passes. Genuine reviews,
longer/disjoint holdouts and final production authority cannot be replaced by
unit tests or a completed source-preparation document.

Keep `ARTIFACT_UPLOAD_SECRET` and `V7_OPERATOR_TOKEN` on the server; ordinary
contributors do not need operator accounts or credentials. Set `TRUST_PROXY` to
match the actual reverse-proxy topology. Legacy JSON signing settings do not
replace V7 artifact authorization.

Release gate before promotion:

```bash
./scripts/release_preflight.sh
```

Frontend-only deployment notes are in `frontend/DEPLOYMENT.md`.
Release notes are tracked in `CHANGELOG.md`.

## Notes on benchmark scope

- Canonical suite clip integrity is enforced by SHA256 plus ffprobe-verified media contracts from `client/resources/test_suite_v1/manifest.json`.
- General PL v7 requires complete EncodingDB Test Suite v1 coverage with equal-class weighting; the local quick-test path is content-specific only and is never General PL.
- Rate control is encoder-native and part of the requested/effective recipe identity; a legacy `--crf` UI input is only an explicit edge conversion for encoders whose native mode supports it.
- Some telemetry fields are platform-dependent and may be unavailable on certain systems (for example, GPU power on non-NVIDIA hardware).

## Contributing

Issues and PRs are welcome. When contributing:

- keep changes focused and well-scoped,
- include tests for behavior changes where practical,
- avoid breaking payload/schema compatibility without migration updates.

## License

Apache License 2.0. See `LICENSE` and `NOTICE`.
