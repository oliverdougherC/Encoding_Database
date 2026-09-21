# Physical Windows candidate b3ef24a

The separately built physical Windows candidate passed three seven-clip console campaigns, four bounded native fault cases, and the four-phase native GUI acceptance (preparation Stop, complete single run, measured Stop, Close confirmation) using ordinary observed-control mouse clicks. One interrupted-then-resumed campaign proves durable checkpoint reuse with retained bytes unchanged. These receipts are platform execution and retention evidence, not calibration fitting data or authoritative backend quality results.

## Exact candidate and machine

- Clean source: `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`; tree `c40f4b4881c3a880051bb612b78beda9efc0ab13`.
- Console SHA-256: `1ef9d33f3b774c87676d65ec0982499a70b4df4d0755cb123f7d38eb98bc82d1`.
- GUI SHA-256: `6d6cbbefb8656ba76c2eefd0c8107b6461a15e9ef381c86a3a90a0c819f66b0e`.
- Native PE x86_64, Python 3.12.10, unsigned. This is distinct from the hosted-CI binary.
- Windows 11 Pro build 26200, Ryzen 9 7950X, RTX 5090 at NVENC device 0/PCI 01:00.0, NVIDIA driver 616.92.
- One persistent installation: `installation-9e7cd0a8c6158d19d179f0acf79249c6c790b988b8a48f6563952c1c00acca29`.

The source939 package and its failed undersized NVENC probe remain preserved separately. The corrected b3 source uses the reviewed canonical-size NVENC usability probe. The project-declared build dependencies were installed only in isolated venvs. The documented Python build operator avoids Windows PowerShell 5.1's native-stderr pipeline incompatibility while executing the unchanged reviewed packaging arguments. Actual source/tree cleanliness, runtime/model/suite pins, PE headers and embedded-only smoke were checked. Console help and no-submit smoke exited 0 without forced cleanup or surviving owned children. Exact manifests, pins, preparation/build receipts, logs and model result are in [build](build).

## Completed native campaigns

| Recipe | Wall time including preparation | Retained attempts | Counted measurements | Stable groups | Verified frames |
| --- | ---: | ---: | ---: | ---: | ---: |
| x264 fast CRF 23 | 350.500 s | 21 VALID | 14 | 7 | 4,896 |
| NVENC p4 CQ 24 | 325.500 s | 21 VALID | 14 | 7 | 4,896 |
| NVENC p4 VBR 6000 kbps | 317.281 s | 21 VALID | 14 | 7 | 4,896 |
| Total | — | 63 VALID | 42 | 21 | 14,688 |

Every campaign has all seven canonical clips, one warmup per clip, zero failed/skipped work, and the unchanged 3% stability threshold. No outcome was discarded or retried. Independent audits verify retained artifact hashes, 1920×1080/24 fps/BT.709 frames, native timer arithmetic, requested/effective rate-control values, GPU-device binding and finalized group membership. The corrected CPU thread-window or blocking-window provenance is retained. Missing telemetry is explicit in the original records.

See [acceptance](acceptance) for per-recipe summaries, operator receipts and exact original journal exports. Reproduce an audit with `scripts/audit-windows-physical-acceptance.py --directory <this-directory>/acceptance --label b3ef24a --recipe <recipe>` from the repository root.

## Completed bounded faults

| Case | Actual native outcome | Retention evidence |
| --- | --- | --- |
| Offline upload | Exit 10: deferred against a closed loopback endpoint | All 44 original immutable files unchanged |
| Backpressure | Local fixture returned 429 with Retry-After 60; all 14 entries retained; immediate second replay made zero POSTs | All 44 original immutable files unchanged |
| Corrupted pack | Same-size altered pack rejected with exit 3; zero attempts; fallback blocked by an owned loopback proxy without forwarding | Original pack and all 44 original immutable files unchanged |
| Storage budget | Explicit 1 MiB budget rejected with exit 6 before any attempt | All 44 original immutable files unchanged |

Receipts, immutable-file ledgers and logs are in [faults](faults). The storage test exercises the client's declared budget, **not actual Windows disk-full behavior**. The 429 fixture does not represent production or candidate-server ingestion. These fault runs made no P910 contact and no production submission; the later explicitly authorized coordinated upload of completed campaigns is recorded separately in `windows-uploaded.json`. The backpressured upload entries remain retained for later coordinated replay.

## Physical GUI acceptance (click6 run, 2026-09-20)

The GUI driver ran the four phases against the real frozen GUI on the console session with dynamically re-observed controls: exact control/owner/PID binding, visible non-occluded click points, and native dialogs accepted by ID. [gui/receipt.json](gui/receipt.json) records status `PENDING_PARENT_INSPECTION`: every automated gate passed (preparation Stop observed mid-run with the helper's owned-process set non-empty, single-run completion, measured Stop with `measured=true`, Close via native `#32770` Yes, zero surviving owned processes, journal intact), and 16 owned-window screenshots (with UIA/Win32 control dumps and `events.jsonl`) are committed under [gui](gui) for parent visual review before the lane calls it finally accepted. The shortcut/`Alt+R` route is recorded separately as never activated Start on this host; ordinary clicks were the accepted mechanism. No hotkey settings were changed.

## Interruption/resume

A GUI-driven run was interrupted during measured work; the durable checkpoint, attempt journals and retained bytes stayed byte-identical. A re-encode attempt correctly refused (`Campaign already completed before resume; cancellation evidence invalid`) only after a later complete run finished; the direct `--resume-campaign` replay reused the checkpoint (identical artifact hashes, zero re-encode) and completed. The restricted scheduled-task driver hung before preparation on limited tasks (cause retained in receipts/watch logs); completion and verification were proven via the foreground diagnostic execution on the same durable queue. Receipts: `gui-resume-*` under the acceptance directory.

## Remaining work

Earlier focus/SendKeys failures are preserved privately; none is reported as passing. The parent visual review of the retained screenshots is pending. The coordinated candidate upload of the three canonical console campaigns completed strictly upload-only through the documented loopback chain (no re-encode; sealed bytes hash-verified before/after): 35 submissions recorded, 7 honest terminal receipts retained under [gui/upload](gui/upload); full detail in the lane's `windows-uploaded.json`. Release signing/publishing and production remain separate gates. The operator test suite passed eight checks on actual Windows, including exclusive host allocation, safe candidate phase labels, pin/path rejection and evidence preservation.
