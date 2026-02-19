Encoding Database
=================

Encoding Database is an open benchmarking platform for video encoding performance, quality, and efficiency. It combines:

- A cross-platform Python client that runs reproducible FFmpeg benchmarks.
- A Node/Express + Prisma API that validates, scores, and aggregates submissions.
- A Next.js frontend with comparison tools and leaderboards.

With the changes brought by version *v1.1.0*, the project has moved well beyond a simple benchmark script into a multi-component data platform with quality controls, ingest hardening, and hardware telemetry.

## Why this project exists

Encoder performance claims are often hard to compare because workloads, settings, and hardware conditions differ. Encoding Database standardizes those dimensions (as best we can) so results are more comparable and useful in real-world decision making:

- Which encoder and preset is fastest on my class of hardware?
- What quality tradeoff am I buying for speed and output size?
- How much power and thermal headroom does a given encode path consume?

## System architecture

1. The client runs benchmark tasks (single run or benchmark batches) against a canonical input clip.
2. The client computes quality and performance metrics and captures optional system telemetry during encode.
3. The client submits an allowlisted payload to `/submit`.
4. The server validates payloads, deduplicates with a hash, scores quality confidence, stores an immutable audit row, and updates aggregate benchmark rows transactionally.
5. The frontend queries `/query` for accepted aggregates and renders analytics/leaderboards.

## Repository layout

- `client/`: Python benchmark runner, hardware detection, FFmpeg orchestration, telemetry sampler.
- `server/`: Express API, Zod validation, Prisma models/migrations, ingest + query pipeline.
- `frontend/`: Next.js 15 app with benchmark table, analytics, leaderboards, and hardware pages.
- `nginx/`: reverse-proxy configuration for production.
- `scripts/`: local testing, e2e checks, hardening checks, packaging, deployment helpers.
- `sample.mp4`: canonical baseline clip used by the benchmark flow.

## Current platform capabilities

- Benchmark dimensions: codec/encoder, preset, CRF, content class, resolution, pass count.
- Core quality/performance: FPS, file size, VMAF, SSIM, PSNR.
- Hardware telemetry: utilization, power, memory, temperatures, CPU frequency, process I/O and CPU time, battery state.
- Data integrity controls: canonical input hash checks, idempotent payload hash, accepted/suspect/rejected submission status.
- Aggregation model: rolling sums/sample counts for stable recomputation and drift-resistant averages.
- Query API: filtering, sorting, ranges, pagination, derived efficiency metrics.
- Frontend analytics: scatter plots, histograms, rate-distortion, content/resolution comparisons, PL Score v6 leaderboards.

## Telemetry and privacy

### Data collection policy

No user-identifiable data is collected in benchmark telemetry payloads.  
Only system and benchmark run information is collected for data accuracy, reproducibility, and fairness across hardware.

The client submits an explicit allowlist of fields. This prevents accidental inclusion of unrelated machine or user data.

### Telemetry fields collected and why they matter

| Category | Fields | Why this is collected |
| --- | --- | --- |
| System profile | `cpuModel`, `gpuModel`, `ramGB`, `os` | Normalizes comparisons across hardware and OS environments. |
| Workload configuration | `codec`, `preset`, `crf`, `contentClass`, `resolution`, `passes`, `inputHash` | Ensures two rows are only compared when workload settings are equivalent. |
| Core benchmark outcome | `fps`, `fileSizeBytes`, `vmaf`, `ssim`, `psnr`, `runMs` | Captures speed, size, and perceptual quality outcomes of each encode. |
| Runtime telemetry (efficiency) | `gpuUtilAvg`, `gpuPowerAvgW`, `gpuMemPeakMB`, `cpuUtilAvg`, `cpuUtilMax`, `peakMemoryMB`, `thermalThrottle` | Enables efficiency and stability analysis beyond raw FPS. |
| Extended telemetry | `gpuTempMaxC`, `cpuFreqAvgMHz`, `cpuTempMaxC`, `ffmpegCpuUtilAvg`, `ffmpegCpuUtilMax`, `ffmpegReadMB`, `ffmpegWriteMB`, `ffmpegCpuTimeS`, `batteryPercentStart`, `batteryPercentEnd`, `batteryPercentDrop`, `powerSource`, `sampleCount`, `monitorDurationMs` | Improves confidence scoring, thermal context, and power/runtime interpretation. |
| Tooling metadata | `ffmpegVersion`, `encoderName`, `clientVersion`, `notes` | Aids reproducibility and diagnostics of edge-case runs. |

### What is not collected

- No names, emails, accounts, or profile identifiers.
- No location data.
- No browser cookies or advertising identifiers.
- No filesystem snapshots, personal files, or media uploads beyond benchmark metrics.
- No device serial numbers or MAC addresses in benchmark rows.

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
   - Windows: `encodingdb-client-windows.exe`
   - macOS: `./encodingdb-client-macos`
4. Follow the menu prompts to run single, small, medium, or full benchmark modes.
5. Results are submitted automatically unless `--no-submit` is enabled.

## Client CLI options

The client is menu-driven by default and also supports CLI flags:

```bash
python client/main.py \
  --base-url https://encodingdb.platinumlabs.dev \
  --codec libx264 \
  --presets fast,medium \
  --crf 24 \
  --batch-size 0 \
  --content-class mixed \
  --resolution 1080p \
  --passes 1
```

Common flags:

- `--no-submit`: run benchmark but do not upload.
- `--use-token`: use short-lived ingest token flow when server supports it.
- `--queue-dir`: directory for offline retry queue.
- `--pause-on-exit`: keep console open after run (useful on Windows).

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
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:3001" > .env.local
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

## Frontend pages

- `/`: benchmark table with filters, compare panel, PL Score sorting.
- `/analytics`: visual analytics (histograms, scatter, rate-distortion, content/resolution charts).
- `/compare-encoders`: focused encoder comparison dashboard.
- `/leaderboards`: top encoders by speed/quality/compression/PL Score.
- `/hardware`: efficiency and hardware intelligence charts.
- `/plove`: PL Score v6 documentation and formula overview.

## Build packaged clients

Windows:

```powershell
scripts/build_windows_client.ps1
```

macOS:

```bash
./scripts/build_macos_client.sh
```

Linux:

```bash
./scripts/build_linux_client.sh
```

All packaging scripts expect platform FFmpeg/ffprobe binaries under `client/bin/<platform>/`.

## Testing and validation scripts

- `server/test/routes.smoke.test.js`: server smoke tests.
- `scripts/e2e.sh`: local end-to-end benchmark flow.
- `scripts/api_hardening_test.sh`: API validation, limits, and resilience checks.

## Production deployment

1. Generate env files:

```bash
./scripts/setup_env.sh --domain your-domain.example
```

2. Build and run:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

3. For scripted updates on a deployment host:

```bash
./scripts/redploy.sh
```

Frontend-only deployment notes are in `frontend/DEPLOYMENT.md`.

## Notes on benchmark scope

- Canonical clip integrity is enforced by SHA256 (`sample.mp4`).
- Multi-content/resolution fields are supported in schema and UI; the canonical sample remains the default guaranteed clip path.
- Some telemetry fields are platform-dependent and may be unavailable on certain systems (for example, GPU power on non-NVIDIA hardware).

## Contributing

Issues and PRs are welcome. When contributing:

- keep changes focused and well-scoped,
- include tests for behavior changes where practical,
- avoid breaking payload/schema compatibility without migration updates.

## License

Apache 2.0

