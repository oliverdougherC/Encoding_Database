# Packaged client fault evidence — 2026-09-14

These checks are diagnostic under concurrent build/preflight load, not calibration or GUI certification. No production submissions are made.

## Confirmed packaging failure

The Mac executable built from source `84d4086` passed help but failed its local contribution smoke before encoding with `runtime dependency SHA-256, membership or size mismatch`.

The retained CArchive audit in `packaging/failed-84d4086-archive-audit.json` compares the actual executable with the reviewed lock. Both helpers and all 100 dependency files changed despite matching membership and byte sizes. PyInstaller 6.19 reclassified the supplied Mach-O DATA entries as BINARY, then changed their load commands/signatures during PKG assembly.

The correction preserves only the reviewed `bin/mac` helpers/dependencies as DATA after Analysis. PyInstaller 6.19 preserves executable mode for executable DATA without performing its binary transformation. Other Python runtime binaries still undergo normal packaging. Archive verification must match every original helper/dependency hash, the embedded reviewed lock, membership and executable flags before smoke can pass.

The prior native CI environment exposed provisioned external helpers through `FFMPEG_EXE`/`FFPROBE_EXE`. Smoke now removes helper, lock and loader overrides, preserves explicit suite/cache/installation state, and requires a fresh runtime-verification receipt from within the packaged extraction directory. A help-only or external-helper success is not embedded-runtime certification.

Original failing executable remains at `.build/release-20260914/macos-final/encodingdb-client-macos` in the integration checkout. Its original SHA is recorded in the audit. Fault campaigns were postponed until this integrity gate is repaired; no failed package was used for calibration.

## Corrected candidate and executed cases

Source commit `f673170` includes the completed measurement-group client receipt change from `b24d443` and the packaging correction. Later CA and encoder changes are outside this artifact; the integrator must rebuild its final release tree. No source/runtime lock was weakened.

Candidate SHA-256: `c61e106f6b18480224b65f6c7e0137f51d12f26eb9f4b39a9d75f9fa6f8ab908`.
Candidate: `/Users/ofhd/Developer/Encoding_Database/.build/native-faults-20260914/package-f673170/encodingdb-client-macos`.
Its actual archive audit passes all 102 locked helper/dependency members. Actual embedded help and x264-fast local contribution smoke both exited 0. The smoke receipt captures FFmpeg, ffprobe and lock paths inside `_MEI52yvOz`, not external provisioned helpers. Packaging/unit checks: 19 passed.

Exact invocation arrays, controlled environment, timestamps, exit codes and signals are in `acceptance.json` and `cases/`; console transcripts use `.log.txt` so they remain durably tracked; native harness scripts are retained in `harness/`. All invocations use the shared installation state at `/Users/ofhd/Developer/Encoding_Database/.build/release-20260914/mac-host-state`.

| Case | Observed result |
| --- | --- |
| Clean-cache, non-ASCII executable/cache/queue paths | Actual adjacent pack acquired into an initially absent cache; original and cached pack SHA equal `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`. Explicit 0.001-minute measurement allowance returned 11 after acquisition. This is acquisition/budget proof, not a completed measurement claim. No HTTP requests. |
| Corrupt same-size adjacent/explicit pack | Changed SHA rejected; exit 3, no attempt records. A localhost fixture supplied invalid replacement bytes; external fallback CONNECT was blocked by the same localhost failure proxy. No production or real-server HTTP certification. |
| SIGINT during an active encode, after completed warmup | Exit 130; owned encoder stopped. |
| Relaunch then SIGKILL during a later encode | Exit -9; a completed measured attempt already existed and the owned encoder remained alive immediately afterward. |
| Relaunch after SIGKILL | Exit 0; original warmup and measured record files and artifact hashes are unchanged; stale owned-process receipt is gone. Campaign remains `campaign-b92d34ea50b6f8fc`. Only the interrupted attempt needed another encode. |
| Actual OS filesystem exhaustion | A task-owned 64 MiB HFS+ image reached zero available bytes, including failure of a fresh one-byte write with ENOSPC 28. Packaged replay returned 6, preserving all prior record/artifact hashes. Image was detached and the original host queue restored. Host filesystem was never filled. |

The three recovery invocations used distinct extraction roots `_MEI9CjIac`, `_MEIFjxrW1` and `_MEI6gvWzP`; their actual FFmpeg SHA remained `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2`.

The first disk-fill experiment stopped after a 1 MiB write failed but left enough allocation headroom for small cached-journal rewrites; client exit 0 was retained as an inconclusive fault injection, not claimed as failure handling. The exhaustive follow-up consumed small-file headroom too and produced the actual exit-6 failure. Initial deprecated hdiutil syntax failed before image creation; the corrected blank-image invocation used `-type UDIF`. Both observations remain in the evidence.

Persistent cache for subsequent controlled campaigns:
`/Users/ofhd/Developer/Encoding_Database/.build/native-faults-20260914/épreuve 客户端/clean-cache`.
It contains the verified pack and extracted suite; later seven-clip preparation can materialize the remaining canonical cache entries from that pack. Do not delete this warmed cache before the integrator's handoff.

Original encoded artifacts remain under the corresponding `recovery-queue/campaigns/campaign-b92d34ea50b6f8fc` directory. JSON journals and hashes are also committed here. The private full-volume images are under `.build/native-faults-20260914/disk-full*`; neither is mounted now.

CI run `34804203876` reported successful Windows, Linux and macOS native jobs. Its Windows console result supports the writable-descriptor EBADF correction, but inherited external helper overrides prevented those earlier jobs from proving embedded-runtime identity. Refreshed native CI with the corrected smoke isolation remains a final-artifact check. No Windows GUI or unavailable physical hardware certification is claimed here. Interruptions above target active encodes; network upload recovery is outside this local CLI fault scope.
