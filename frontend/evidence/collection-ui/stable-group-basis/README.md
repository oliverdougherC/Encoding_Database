# Stable-group measurement basis — isolated UI verification

The new `eligible-stable-groups` basis appears as **Stable groups** in the corpus and **Stable measurement groups** in details. The fixture deliberately retains 12 raw accepted and 2 suspect observations; its PL remains unavailable. This verifies presentation only, not real measurements, calibration, human review or production.

A task-owned fixture API at 127.0.0.1:3112 served synthetic rows to the root production frontend build at 127.0.0.1:3111. Playwright Chromium captured desktop1440×1000 and mobile390×844 screenshots. Mobile document width stayed390; basis and raw counts were present. Parent visual inspection passed95/100. The complete fixture and server harness remain in `output/playwright/stable-basis/`; its hash is in `verification.json`. No database or production received these fixtures.

`npm --prefix frontend test` passed58tests; lint/typecheck and production build passed. There were no browser JavaScript errors; the existing stylesheet-preload warning remains. These screenshots verify the small label addition against the previously archived collection UI layout.
