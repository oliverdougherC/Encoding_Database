Encoding Database – Open Benchmark Suite for Video Encoding
===========================================================

Overview
--------
Encoding Database is an open-source project that crowdsources real-world, reproducible performance and quality data for video encoding stacks across CPUs and GPUs. The goal is to help the community compare encoders, presets, and hardware on consistent inputs while capturing realistic throughput, quality (VMAF), and file size outcomes.

Repo layout
-----------
- `server/`: Node/Express + Prisma API that accepts benchmark submissions and aggregates results.
- `frontend/`: Next.js app for exploring benchmarks and visualizations.
- `client/`: Cross-platform Python benchmark client (packaged with PyInstaller for end users) that runs standardized FFmpeg pipelines and submits results.
- `nginx/`: Reverse proxy examples for production deployments.
- `scripts/`: Helper scripts for development, building, and operations.

What the benchmark measures
---------------------------
For a fixed, canonical input clip, the client runs a matrix of encoder/preset combinations and reports:
- FPS (throughput)
- File size
- VMAF (if the FFmpeg build has libvmaf)
- Basic hardware info (CPU, GPU/integrated, RAM, OS)
- Encoder used (software/hardware), preset, CRF

The API validates, scores, and aggregates data to present robust medians and highlight outliers.

Quick start – Using the prebuilt client (Windows/macOS)
------------------------------------------------------
1) Download the latest release for your OS from the Releases page.
2) Close other heavy apps to improve measurement quality.
3) Run the client:
   - Windows: double-click `encodingdb-client-windows.exe` (the terminal will pause at the end so you can read results)
   - macOS: run the unix executable or `./encodingdb-client-macos` from Terminal (Gatekeeper may require you to allow execution)
4) Follow the prompts to select a codec/encoder, CRF, and preset (or run a pre-defined small/medium/full benchmark from the menu).
5) If submissions are enabled, results will be uploaded automatically. Otherwise, they will be queued locally for retry.

Client command-line options
---------------------------
The client accepts flags to customize behavior. Common examples:

```
--codec libx264           # force a specific encoder (e.g., libx264, libx265, h264_nvenc)
--presets fast,medium     # presets list (comma-separated)
--crf 24                  # CRF for software encoders (mapped for HW encoders where possible)
--no-submit               # run locally but do not submit to the server
--batch-size 0            # 0=auto: number of physical CPU cores (not threads)
--use-token               # opt-in to short-lived token auth if the server requires it
--base-url https://...    # override API base (defaults to production)
--pause-on-exit           # keep the console window open at the end (Windows)
```

Hardware encoder detection
--------------------------
The client enumerates software encoders and probes hardware encoders using a fast one-frame test. This prevents showing unusable NVENC/QSV/AMF encoders on systems without those capabilities (e.g., integrated-only systems). On Windows, GPU model detection falls back to CIM/WMI when needed, improving support for integrated GPUs like AMD 780M.

Batch sizing
------------
By default the client uses the number of physical CPU cores for parallel VMAF computation. This avoids over-subscription on hyperthreaded CPUs. You can override with `--batch-size N`.

Development – Local environment
-------------------------------
Prereqs:
- Node 18+
- Docker (for Postgres)
- Python 3.10+ (for the client)

Steps:
1) Copy `env.example` to `.env` at repo root and set values as needed. Do the same in `server/env.example`.
2) Start API + DB:
   ```
   docker-compose up --build
   ```
3) Install server deps and generate Prisma client:
   ```
   cd server
   npm ci
   npm run build
   npm run prisma:generate
   npm run dev
   ```
4) Frontend:
   ```
   cd frontend
   npm ci
   npm run dev
   ```
5) Client (Python):
   ```
   cd client
   python -m venv ../.myenv && ../.myenv/Scripts/activate  # Windows
   pip install -r requirements.txt
   python main.py --no-submit --menu
   ```

Building the Windows client
---------------------------
Requirements:
- Windows Python with PyInstaller installed in your venv (`.myenv`), and
- `client/bin/win/ffmpeg.exe` and `ffprobe.exe` present (bundled with the exe)

Build:
```
scripts\build_windows_client.ps1
```
Result: `client/dist/windows/encodingdb-client-windows.exe`

Building the macOS client
-------------------------
Use `scripts/build_macos_client.sh` (requires a native macOS Python and PyInstaller). Codesigning/notarization are not covered here.

Security and submission modes
-----------------------------
The API supports several ingest modes controlled by environment:
- public: accepts unsigned submissions (optionally short-lived tokens)
- signed: requires HMAC signature headers
- hybrid: accepts signed, else token if present, else unsigned (best-effort)

The client can fetch and attach a short-lived token (`--use-token`) when the server is configured for that.

Privacy notes
-------------
Submitted payloads include hardware model strings, OS version, encoder name, and performance metrics. No personal data beyond the above is collected. Do not run the client on machines where this disclosure is unacceptable.

Contributing
------------
Issues and PRs welcome. Please keep code clear and well-typed, and add small targeted tests where sensible.

License
-------
Apache 2.0.


