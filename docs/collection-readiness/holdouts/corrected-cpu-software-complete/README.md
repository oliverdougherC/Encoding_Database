# Corrected software holdouts: complete timing evidence

All 42 predeclared software cells completed on P910 between **2026-09-14 06:20:47Z and 09:03:47Z**. The process continued after the coordinating session was interrupted. On September 19, read-only liveness checks found no remaining task-owned timing process and an available outer measurement lock. No cell was rerun.

The frozen source is `f3ef468c831e60f7a02576cd57ebc6ec0f1b2c59`; the unchanged plan hash is `7c488c7d1b5cd95d38f3b2c41815970af746be41ff86feb17ae1a80a96ce4730`. All cells retain the same physical installation identity, requested recipes, original seeds, one warmup, two required measured attempts, at most two adaptive attempts, and a 3% relative timing-spread threshold.

| Outcome | Cells | Measured attempts |
| --- | ---: | ---: |
| Stable | 37 | 74 |
| Unstable and ineligible | 5 | 20 |
| Total | 42 | 94 |

All 136 retained attempts (including 42 warmups) retain their original valid environment/structural flags. Timing instability is an independent rejection: the five unstable cells remain excluded despite valid environment snapshots. Fresh background CPU observations range from 3.25% to 10.95%, with the corrected `cpu_psutil_thread_window_v1` provenance marker on every counted observation. Encoded artifacts occupy 7,125,734,037 bytes.

| Unstable cell | Measured attempts | Relative spread |
| --- | ---: | ---: |
| TOS outdoor dialogue / x264 fast / CRF 28 | 4 | 6.175979% |
| Sol cave forest / x265 fast / CRF 28 | 4 | 3.087688% |
| Nocturne grain / SVT-AV1 preset 6 / CRF 36 | 4 | 4.300396% |
| Nocturne grain / x264 fast / CRF 18 | 4 | 4.830853% |
| Chimera fountain / x264 fast / CRF 28 | 4 | 6.092271% |

## Evidence and verification

`original-receipts.tar.gz` preserves the original campaign JSON, per-attempt checkpoints, operator reports and logs. Its SHA-256 is `28e44e80b9792a1e8d367f9e6d8a5ab64a9a4de7f343cbe0446ec073f5eb4252`. Original absolute paths are retained; the archive contains no encoded media.

`receipt-mathematical-audit.json` independently recomputes means, spreads, stable flags, FPS, real-time multiples and sample membership from all 42 original receipts, and checks the predeclared recipe/seed mapping plus all 136 requested/effective/executed native recipes. `audit.py` verifies the frozen source archive, runner and operator driver, all seven reference hashes, exact report/receipt identities, artifact hashes, corrected CPU markers, monotonic timing tuples and every retained file's fresh 720-frame 1920×1080/24-fps decode. `audit.json` records the completed checks per attempt; `audit.log` records progress. Verification finished successfully on 2026-09-20 at 01:08:46Z (September 19 local time). `host-handoff.json` confirms the available measurement lock and absence of an audit process at 01:09:47Z.

The fresh frame audit holds the same outer measurement lock to prevent a new timed phase. It uses four independent single-thread ffprobe processes and deterministic result order. The initial serial audit was deliberately interrupted after six cells to shorten post-timing verification; its script/log are retained. Only that audit and its owned ffprobe were terminated, and a process-table check confirmed both were gone before the four-probe audit began. The termination wait encountered a psutil pidfd `EINVAL`; the direct process-table verification established termination. No campaign process or retained artifact was changed. Isolated staging builds may overlap this post-timing audit; no new timing, analysis or upload phase may overlap it.

## Limits

These results establish software execution, retention, timing stability and frame/byte coverage. Authoritative VMAF/XPSNR analysis, quality curves, held-out ranking, human review and PL activation remain separate gates. The 28 hardware holdout cells and canonical calibration matrix are separate phases.

**Process CPU utilization is unavailable as trustworthy evidence for these historical receipts.** Every attempt reports `ffmpegCpuUtilAvg=0.0` and `ffmpegCpuUtilMax=0.0`: the process sampler recreated psutil process objects instead of preserving their CPU-delta baselines. This does not affect the separate corrected background-CPU snapshots, monotonic wall time or frame counts. Original fields have not been rewritten or backfilled. They must not be used as evidence of zero encoding CPU consumption.

The 17 earlier cells from source `0185a00` remain exploratory and excluded because their background-CPU sampler was affected; this complete corrected experiment does not rehabilitate that earlier data. One physical host also does not establish independent-machine confidence.
