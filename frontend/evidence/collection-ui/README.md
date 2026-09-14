# Collection UI acceptance — 2026-09-14

This is isolated UI verification, not production/native-client certification. A local fixture API on 127.0.0.1:3102 served synthetic public corpus rows to the production frontend on 127.0.0.1:3101. Fixtures never entered a database or production. Browser: Playwright Chromium, desktop 1440×1000 and mobile 390×844.

- `npm --prefix frontend test`: exit 0, 56 tests / 13 files passed.
- `npm --prefix frontend run lint`: exit 0, ESLint and TypeScript passed.
- `ENABLE_QUERY_MOCK=1 ./node_modules/.bin/next build --webpack` (frontend directory): exit 0. Webpack was used because the isolated worktree shares the main checkout's node_modules symlink.
- `git diff --check`: exit 0.
- Browser corpus cases: suspect-only (0 accepted / 4 suspect), accepted-only, mixed, sparse, all with null PL. All page widths equal their viewport width at both sizes; scrolling is confined to the table.
- Compatible different-recipe comparison: two metric highlights (FPS and VMAF), no sample-count highlight. Incompatible workload comparison: zero metric highlights and explicit warning. Unit tests also cover environment, protocol, source-suite and quality-model differences.
- Direct `/results/{id}`: accepted, mixed, sparse and suspect rows open the exact details; withdrawn id returns HTTP 404. UI separates measurement basis, verified bytes, artifact retention, evidence tier, PL and confidence.
- `/run`: published 1.2.0 asset names/URLs verified with `gh release view 1.2.0 --repo oliverdougherC/Encoding_Database --json assets,body`. Corrected source-client commands are explicitly client/0.3.0; no nonexistent 1.3.0 asset is linked.

## Screenshots

Screenshots are local durable artifacts in the frontend worktree's `output/playwright/frontend/` directory. Selected images are copied alongside this receipt for source-review access:

- `suspect-desktop.png`, `mixed-mobile.png`: truthful corpus totals and responsive containment.
- `direct-suspect-mobile.png`, `direct-mixed-mobile.png`: distinct center, integrity and retention.
- `compatible-desktop.png`, `incompatible-mobile.png`: per-metric comparison behavior.
- `run-mobile.png`: download and source-command separation.

Full set also includes accepted/sparse corpus screenshots at both sizes, accepted/sparse direct detail screenshots, all comparison sizes, and run desktop.

## Limits and integration

Requires the integrated backend's `GET /corpus/:id` endpoint (same public row or 404), implemented by the corpus lane. The final client commands must be verified against the integrated client lane. No final downloadable platform, hardware or production collection certification is claimed here. The published release remains 1.2.0 until the release gate passes.

The development server's existing strict CSP blocks webpack hot-reload eval; browser acceptance therefore used the production build. Production rendering had no JavaScript errors. Chromium reported a stylesheet-preload warning; the intentional missing-result check produced the expected 404 console entry.
