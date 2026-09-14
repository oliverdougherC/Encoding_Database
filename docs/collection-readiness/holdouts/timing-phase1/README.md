# Actual P910 timing, first pair

**Qualification:** this source is affected by the subsequently confirmed background-sampler defect. All observations below are exploratory and ineligible for final calibration, including groups that passed timing spread. See `../affected-background-sampler-v1.json`; original receipts and flags remain unchanged.

Two of the declared 42 validation-only cells completed using source commit `0185a001e268b35aad492a8d35c487f5527ac3f5`, the pinned Linux FFmpeg runtime and the shared physical-host state directory. The audited receipt contains exact commands, runtime hashes, environment samples, artifact hashes and frame checks. All eight attempts produced valid 720-frame artifacts; no upload, database import, quality analysis, human judgment or PL activation occurred in this phase.

| Screen source / libx264 fast | Warmup | Counted measurements | Relative spread | Outcome |
| --- | ---: | --- | ---: | --- |
| CRF 18 | 4.690336084 s | 4.742948176, 4.601686875, 4.671802185, 4.646706022 s | 3.02759935% | Ineligible; exceeds 3% after maximum adaptive attempts |
| CRF 28 | 4.675153930 s | 4.696131756, 4.639806455 s | 1.20663397% | Stable timing group |

The failed CRF 18 group remains intact. No attempt was removed to make it pass. A comparison requires at least two eligible choices; this first pair therefore does not yet supply one.

The initial preflight resolved system FFmpeg instead of the locked runtime and exited before encoding. Its log is retained. The successful command prepended the locked runtime directory to PATH. An unrelated preexisting media-thumbnail FFmpeg used approximately one of 88 logical cores and was left untouched. “Quiet allocation” means no competing task-owned jobs; it does not assert that the physical host was idle. Actual environment and stability gates remained enabled.

After both cells completed, the host was handed to operations for final candidate builds and analyzer capacity trials. Remaining 40 cells resume only after the explicit return of that allocation. Stable receipts can later enter the isolated validation database using the exact completed measurement-group receipt; an individual valid attempt alone cannot establish group eligibility.
