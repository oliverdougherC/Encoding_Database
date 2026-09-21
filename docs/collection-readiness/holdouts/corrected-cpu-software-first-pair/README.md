# Corrected sampler, first actual pair

Source `f3ef468c831e60f7a02576cd57ebc6ec0f1b2c59` and plan `7c488c7d1b5cd95d38f3b2c41815970af746be41ff86feb17ae1a80a96ce4730` completed the first two newly seeded screen/x264/fast cells. Each has one warmup and two counted measured attempts. All six retained artifacts passed hash, 720-frame and exact timing/FPS checks.

| Native CRF | Timing spread | Fresh observed background CPU | Timing result |
| --- | ---: | --- | --- |
| 18 | 2.36804% | 4.25%, 6.75% | Stable |
| 28 | 0.055184% | 6.7%, 8.5% | Stable |

Every counted snapshot retains `cpu_psutil_thread_window_v1`. These are observed values; no quiet-host assumption or substituted zero was used. Physical source identity remains unchanged. The outer operator lock covered preflight, timing and validation, and the first-pair inspection completed before the remaining 40 cells began.

These are timing/provenance checks only. Authoritative quality analysis, human review and calibration are still pending. The 17 observations from the affected earlier source remain separately preserved and ineligible; no historical marker or validity flag was rewritten.
