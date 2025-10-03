# Development Plan: Crowdsourced Video Encoding Benchmark Database

[cite_start]This plan breaks down the project into a sequential series of tasks, from initial setup to long-term maintenance, based on the development roadmap[cite: 118].

## [cite_start]Phase 1: MVP (Minimum Viable Product) [cite: 119]
[cite_start]**Goal: Establish the core data pipeline[cite: 120].**

### Task 1: Backend & Infrastructure Setup
- [x] Initialize a new Git repository for the project.
- [x] Create a monorepo structure with directories for `client`, `server`, and `frontend`.
- [x] [cite_start]**Server Setup (Node.js/Express.js)[cite: 108]:**
    - [x] Initialize a new Node.js project with TypeScript.
    - [x] Install Express.js and required middleware.
    - [x] Set up Docker and a `docker-compose.yml` file for the backend server and database.
    - [x] [cite_start]**Database Setup (PostgreSQL)[cite: 111]:**
        - [x] Add a PostgreSQL service to `docker-compose.yml`.
    - [x] [cite_start]Use a database migration tool (e.g., Prisma, TypeORM) to define and apply the `benchmarks` table schema [cite: 44-56, 126].
- [x] [cite_start]**API Endpoint (`/submit`)[cite: 124]:**
    - [x] [cite_start]Create a `POST /submit` route in Express.js[cite: 38].
    - [x] [cite_start]Implement data validation logic to ensure incoming JSON matches the required format[cite: 40].
    - [x] Write the database logic to insert validated benchmark data into the PostgreSQL `benchmarks` table.

### [cite_start]Task 2: Benchmarking Client (Windows MVP) [cite: 122]
- [ ] **Project Initialization:**
    - [x] [cite_start]Initialize a new Python project in the `client` directory[cite: 101].
- [ ] **Core Functionality:**
    - [x] [cite_start]Write a script for hardware detection on Windows using `py-cpuinfo` and `wmi` libraries to capture CPU, GPU, RAM, and OS version [cite: 17-20, 106].
    - [ ] [cite_start]Bundle a specific version of `ffmpeg.exe` and `libvmaf` model files with the client source[cite: 23].
    - [x] [cite_start]Implement the minimal test suite: run `ffmpeg` with `libx264` using `fast`, `medium`, and `slow` presets on a standard test video file[cite: 25, 123].
    - [x] [cite_start]Write functions to parse `ffmpeg`'s stderr output to capture encoding speed (FPS) [cite: 27] [cite_start]and file size[cite: 29].
    - [x] [cite_start]Write a function to run the `libvmaf` filter and parse its output to get the final VMAF score[cite: 28].
- [ ] **Data Submission:**
    - [ ] [cite_start]Consolidate all collected hardware info and benchmark results into a single JSON object[cite: 32].
    - [x] [cite_start]Use the `requests` library to `POST` the JSON object to the backend's `/submit` endpoint[cite: 33, 106].
- [ ] **Packaging:**
    - [ ] [cite_start]Configure `PyInstaller` to package the entire Python script, including the bundled `ffmpeg.exe`, into a single standalone executable for Windows[cite: 102].

### Task 3: Basic Frontend & Deployment
- [x] [cite_start]**Frontend Setup (Next.js)[cite: 114]:**
    - [x] Initialize a new Next.js project with TypeScript in the `frontend` directory.
- [x] **API Endpoint (`/query`):**
    - [x] [cite_start]Create a `GET /query` route in the Express.js backend that fetches all records from the `benchmarks` table[cite: 39].
- [ ] **Webpage Development:**
    - [x] [cite_start]Create a single, basic webpage that fetches data from the `/query` endpoint[cite: 127].
    - [x] [cite_start]Render the fetched data in a simple, unstyled HTML `<table>`[cite: 127].
    - [ ] [cite_start]**Deployment[cite: 128]:**
    - [x] [cite_start]Deploy the backend server and database to a cloud platform (e.g., DigitalOcean, AWS) using Docker[cite: 109].
    - [ ] [cite_start]Deploy the frontend Next.js application to Vercel or Netlify[cite: 117].

## [cite_start]Phase 2: Public Beta Launch [cite: 129]
[cite_start]**Goal: Create a usable public platform and expand data collection[cite: 130].**

### [cite_start]Task 4: Client Platform Expansion [cite: 132]
- [ ] Adapt the Python hardware detection scripts to work on macOS (parsing `sysctl` output).
- [ ] Adapt the hardware detection scripts to work on Linux (parsing files in `/proc`).
- [ ] [cite_start]Configure `PyInstaller` to build executables for macOS and Linux[cite: 105].

### [cite_start]Task 5: Full Frontend Interface [cite: 133]
- [ ] [cite_start]Implement UI controls (dropdowns, text inputs) for filtering data by CPU, GPU, and codec [cite: 65-68].
- [ ] [cite_start]Implement UI controls for sorting the displayed results by VMAF score, FPS, and file size [cite: 70-73].
- [ ] [cite_start]Integrate a charting library like Recharts [cite: 116] [cite_start]to display visual comparisons of performance[cite: 134].
- [ ] [cite_start]Design and build a "Download" page with clear links to the client software for all supported operating systems[cite: 137].
- [ ] [cite_start]Design and build a "Contribution Guide" and FAQ page [cite: 80-82, 137].

### Task 6: Test Suite Expansion
- [ ] [cite_start]Update the benchmarking client to include tests for the `libx265` codec[cite: 135].
- [ ] [cite_start]Add tests for at least one hardware encoder, starting with NVIDIA's NVENC (`h264_nvenc`, `hevc_nvenc`)[cite: 136].
- [ ] Update the backend API and database schema as needed to handle the new test parameters.

### Task 7: Launch
- [ ] Perform end-to-end testing on all three platforms.
- [ ] [cite_start]Announce and officially launch the project for public contribution[cite: 137].

## [cite_start]Phase 3: Feature Enrichment [cite: 138]
[cite_start]**Goal: Enhance the user experience and data value[cite: 139].**

### [cite_start]Task 8: User Accounts [cite: 140]
- [ ] Design and implement database tables for user accounts.
- [ ] Implement user registration and JWT-based authentication.
- [ ] [cite_start]Create a user dashboard to view personal submission history[cite: 151].

### [cite_start]Task 9: Public Developer API [cite: 141]
- [ ] [cite_start]Design and document a public version of the `/query` API for developer use[cite: 153].
- [ ] Implement an API key system for authentication and rate-limiting.

### [cite_start]Task 10: Further Test Expansion [cite: 142]
- [ ] Update the client to add tests for the AV1 codec (`libaom-av1`).
- [ ] [cite_start]Modify the client to handle multiple source resolutions (e.g., 1080p and 4K)[cite: 152].

### Task 11: Feature Refinement
- [ ] [cite_start]Implement the "Best For" recommendation engine on the results page[cite: 79, 142].
- [ ] [cite_start]Create a community leaderboard page that queries and ranks contributors[cite: 143, 154].

## [cite_start]Phase 4: Long-Term Growth & Maintenance [cite: 144]
[cite_start]**Goal: Keep the project relevant, accurate, and performant[cite: 145].**

- [ ] **Ongoing Tasks:**
    - [ ] [cite_start]Establish a quarterly schedule to update the bundled `ffmpeg` version in the client[cite: 146].
    - [ ] Monitor database query performance and add indices as the dataset grows.
    - [ ] [cite_start]Create a public feedback mechanism (e.g., GitHub Issues) and actively engage with the community[cite: 148].
    - [ ] [cite_start]Continuously research and add support for new codecs and hardware as they become available in the market[cite: 148].