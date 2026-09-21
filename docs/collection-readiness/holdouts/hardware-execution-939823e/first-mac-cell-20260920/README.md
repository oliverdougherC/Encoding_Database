# First Mac private hardware cell — guard refusal

The explicitly allocated first cell **did not encode**. The unchanged reviewed operator exited **1** at its actual pre-run environment gate on 20 September 2026. There is no cell ledger, attempt record, media artifact, or boundary-pause file. No retry or second cell was started.

Frozen cell: `validation-nocturne-lowlight-30s--h264_videotoolbox--default--vbr4000`, global order 1, seed `202609142801`, 720 frames / 30 seconds, VideoToolbox/default, native VBR 4000 kbps. Source remains `939823ead2c052572f9deb5c9f91c85435d5661d`; it is not relabeled b3.

| Actual preflight observation | Result |
|---|---|
| Power | AC |
| Background CPU | **46.8%**, `background-cpu-suspect`, threshold 35.0 |
| Background GPU | **79.5%**, `background-gpu-high`, invalid threshold 75.0 |
| Overall validity | **invalid** |
| GPU provenance | Two trustworthy samples, `videotoolbox:system`, `gpu_ioreg_agx_system_utilization_v1` |
| CPU provenance | `cpu_psutil_thread_window_v1` |
| Free memory | 5309.390625 MiB |
| Memory pressure | 78.39603424072266% |
| Temperature | CPU/GPU unavailable; no values invented |

The exact command, allocation including its local-native sequencing amendment, source/operator/execution identities, process PID/creation time, timestamps, and scoped cleanup scan are in `receipt.json`. `operator.log.txt` preserves the original refusal and raw snapshot. The scoped media scan found **zero survivors**, and the operator exited before handback. No attempt existed to interrupt or preserve; completed canonical measurements elsewhere were untouched.

The reviewed operator reached this environment gate only after passing its preceding allocation/physical-identity/lock, archive/checkout/runner/model, filtered runtime, registry/reference-byte, and storage-reserve checks. `guard-refusal.json` explicitly identifies those as control-flow evidence; it does not invent separate probe receipts or hardware measurements.

`supervisor.py` contains the executed exactly-one-cell wrapper. It would latch the existing boundary pause only after observing the first RUNNING ledger, without interrupting measured work. That condition never occurred, so no pause was created. The shared physical identity and host lock remain those from the frozen packet.

This is a **preflight refusal**, not a completed holdout, a failed timing measurement, calibration evidence, or collection-ready certification. The Mac timing allocation was explicitly returned to the parent. A later attempt needs a new explicit handoff and fresh valid conditions; no threshold, recipe, order, seed, source, or runtime pin changed.

The original frozen packet and historical preparation seals are unchanged. `original-file-checksums.json` binds the copied supervisor, allocation, receipt, and native log to their exact local bytes. No media, source archive, or shared input was copied or modified by this archival step.
