Encoding Database
=================

Encoding Database is an open benchmarking platform for video encoding performance, quality, and efficiency. It combines:

- A cross-platform Python client that runs reproducible FFmpeg benchmarks.
- A Node/Express + Prisma API that validates, scores, and aggregates submissions.
- A Next.js frontend with comparison tools and leaderboards.

The upcoming official V7 release moves the project beyond a simple benchmark script into a multi-component data platform with quality controls, ingest hardening, and hardware telemetry. Its final project release version and date have not yet been assigned in `release.json`.

## Upcoming release changelog

This release documents work completed since `v1.0.2` and reflects a major platform overhaul.

### Client (Python benchmark runner)

- Reworked benchmark execution to avoid double-encoding and measure speed/size/quality from one artifact.
- Added SSIM and PSNR computation (alongside VMAF), including parallelized quality analysis.
- Added native encoder rate-control handling (CRF, CQ/ICQ/QP, and bitrate modes) without treating their numeric controls as interchangeable.
- Improved benchmark throughput with cached encoder discovery, FFmpeg progress parsing, and SHA256 caching.
- Fixed progress accounting and baseline cache behavior (including TTL support).
- Added hardware telemetry capture for GPU utilization/power, CPU utilization, memory peaks, and thermal throttling.

### Server and data pipeline (Node/Express + Prisma)

- Hardened ingest consistency with transactional aggregation, in-transaction audit inserts, and race-condition fixes.
- Replaced fragile running averages with sum/count-based aggregates for safer recomputation and correction.
- Expanded schema and validation for SSIM/PSNR and hardware telemetry metrics.
- Added query-path optimizations: response caching, composite query indexing, and PostgreSQL-native stats helpers.
- Improved ingest edge-case behavior (CORS for non-browser clients, proxy-aware rate-limit keying, bounded token store).

### Frontend (Next.js analytics platform)

- Overhauled large-dataset handling with virtualized benchmark tables, server-side filtering, and pagination.
- Expanded analysis views with SSIM/PSNR histograms, SSIM vs VMAF scatter, and rate-distortion visualization.
- Added/expanded comparison tooling, leaderboards, and encoder dashboard workflows.
- Added hardware intelligence views: efficiency metrics, GPU utilization, power comparison, CPU heatmaps, and recommendations.
- Replaced candidate-relative scoring with the fixed, versioned PL Score v7 Q/B/S utility and explicit evidence requirements.

### Database and integrity model

- Tightened schema integrity with non-null `crf` defaults and normalized `gpuModel` handling.
- Standardized canonical input hash enforcement for reproducible benchmark comparisons.
- Extended benchmark rows with telemetry and quality sample-count fields for higher confidence analysis.
- Added immutable PL-v7 runs, artifacts, authoritative analyses, score contexts, and derived results.

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

No user-identifiable data is collected in benchmark telemetry payloads.  
Only system and benchmark run information is collected for data accuracy, reproducibility, and fairness across hardware.

Interactive client sessions ask once before the first publication and store that consent locally. Noninteractive CLI runs publish only when `--submit` is passed explicitly.

The client submits an explicit allowlist of fields. This prevents accidental inclusion of unrelated machine or user data.

The offline spool is also local and persistent:

- macOS: `~/Library/Application Support/EncodingDB/queue`
- Linux: `$XDG_STATE_HOME/EncodingDB/queue` or `~/.local/state/EncodingDB/queue`
- Windows: `%LOCALAPPDATA%\EncodingDB\queue`

Failed uploads remain in that queue until they are replayed or explicitly cleaned up.

### Telemetry fields collected and why they matter

| Category | Fields | Why this is collected |
| --- | --- | --- |
| System profile | `cpuModel`, `gpuModel`, `ramGB`, `os` | Normalizes comparisons across hardware and OS environments. |
| Workload configuration | `codec`, `preset`, `crf`, `contentClass`, `resolution`, `passes` (fixed to `1`), `inputHash` | Ensures benchmark rows are compared only when workload settings are equivalent. |
| Core benchmark outcome | `fps`, `fileSizeBytes`, `vmaf`, `ssim`, `psnr`, `runMs` | Captures speed, size, and perceptual quality outcomes of each encode. |
| Runtime telemetry (efficiency) | `gpuUtilAvg`, `gpuPowerAvgW`, `gpuMemPeakMB`, `cpuUtilAvg`, `cpuUtilMax`, `peakMemoryMB`, `thermalThrottle` | Enables efficiency and stability analysis beyond raw FPS. |
| Extended telemetry | `gpuTempMaxC`, `cpuFreqAvgMHz`, `cpuTempMaxC`, `ffmpegCpuUtilAvg`, `ffmpegCpuUtilMax`, `ffmpegReadMB`, `ffmpegWriteMB`, `ffmpegCpuTimeS`, `batteryPercentStart`, `batteryPercentEnd`, `batteryPercentDrop`, `powerSource`, `sampleCount`, `monitorDurationMs` | Improves confidence scoring, thermal context, and power/runtime interpretation. |
| Tooling metadata | `ffmpegVersion`, `encoderName`, `clientVersion`, `notes` | Aids reproducibility and diagnostics of edge-case runs. |

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

## Quick start: benchmark client (prebuilt)

1. Download the latest client release from:
   - [GitHub Releases](https://github.com/oliverdougherC/Encoding_Database/releases)
2. Close heavy background apps for cleaner measurements.
3. Run the binary:
   - Windows (GUI-first): `encodingdb-client-windows.exe`
   - Windows (console fallback/debug): `encodingdb-client-windows-console.exe`
   - macOS: `./encodingdb-client-macos`
4. On Windows, choose benchmark options in the GUI and start the run. On console builds/macOS, follow interactive prompts.
5. Interactive runs ask once before first publication. Direct CLI runs stay local unless `--submit` is passed.

## Client CLI options

The client is menu-driven by default and also supports CLI flags:

```bash
python client/main.py \
  --base-url https://encodingdb.platinumlabs.dev \
  --codec libx264 \
  --presets fast,medium \
  --crf 24 \
  --batch-size 0 \
  --submit
```

Common flags:

- `--submit`: publish results in noninteractive CLI mode.
- `--no-submit`: run benchmark but do not upload.
- `--use-token`: use short-lived ingest token flow when server supports it.
- `--queue-dir`: directory for offline retry queue.
- `--queue-status`: show pending/dead-letter queue counts and sizes, then exit.
- `--queue-cleanup`: remove dead-letter files and orphaned managed artifacts without deleting pending queue entries.
- `--pause-on-exit`: keep console open after run (useful on Windows).
- `--menu`: force interactive menu mode even when single-run CLI flags are provided.
- `--gui`: force Windows GUI mode.
- `--cli`: force terminal mode (overrides auto-GUI on Windows packaged builds).

Examples:

```bash
python client/main.py --codec libx264 --presets fast --submit
python client/main.py --codec libx264 --presets fast --no-submit
python client/main.py --queue-status
python client/main.py --queue-cleanup
```

## Local development

### Prerequisites

- Node.js 18+
- Docker (for Postgres)
- Python 3.10+

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

- `POST /submit`: submit one benchmark payload.
- `GET /query`: fetch accepted aggregate benchmarks with filter/sort/range params.
- `GET /test-videos`: list known benchmark clips.
- `GET /submit-token`, `GET /submit/token`, `GET /health/token`: optional short-lived token issuance.
- `GET /health`, `GET /health/live`, `GET /health/ready`: health checks.
- `POST /v7/benchmark-runs`: idempotently create immutable V7 run/artifact metadata.
- `POST /v7/benchmark-runs/:id/artifacts/ENCODED/upload-authorizations`: issue a short-lived, run-bound upload token.
- `PUT /v7/artifact-uploads/:token`: stream and verify the encoded canonical-suite artifact.
- `GET /v7/benchmark-runs/:id/artifacts/ENCODED/analysis-status`: inspect durable authoritative analysis state.
- `GET /corpus`: browse direct accepted/suspect V7 evidence, with PL fields unavailable until production calibration exists.
- `GET /health/v7-evidence`: machine-readable storage, queue, failed-analysis, and retained-object health.

## Ingest security modes

Configured via environment:

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

- Project release version/date: assigned only at release in `release.json`.
- Client implementation/minimum version: `client/0.2.0`.
- Benchmark protocol version: `7.0`.
- PL formula version: `7.0`.
- Test-suite version: EncodingDB Test Suite v1 (`encodingdb-test-suite-v1`).

These identities are intentionally independent; the release manifest records each one rather than treating the project tag as the protocol or suite version.

## Frontend pages

- `/`: benchmark table with filters, compare panel, PL Score sorting.
- `/analytics`: visual analytics (histograms, scatter, rate-distortion, content/resolution charts).
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

1. Configure env files from `env.example` and `server/env.example`.
2. One-command deploy (pull `main`, build, migrate, and start all services):

```bash
./deploy.sh
```

PL v7 production activation, env validation, named-volume backup/restore, and
pre-V7 migration rehearsal are documented in
`docs/PL_V7_PRODUCTION_ACTIVATION.md`.

3. Manual compose alternative:

```bash
./scripts/generate-dev-cert.sh
docker compose -f docker-compose.prod.yml up -d --build
```

Security note: for hardened public deployment, set `INGEST_MODE=signed`, a strong `INGEST_HMAC_SECRET`, and an explicit `TRUST_PROXY` value in `.env` that matches your reverse-proxy topology.

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
