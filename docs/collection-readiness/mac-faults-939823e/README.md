# Final packaged Mac fault acceptance — 939823e

All requested fault regressions were executed against the actual final Mac candidate, source `939823ead2c052572f9deb5c9f91c85435d5661d`, executable SHA-256 `ad01bfd36ad84e0e0d9f45730bd195c1b940a240493d093f6a875faa97a6f2c0`. These are fresh native results, not renamed earlier receipts or help-only checks. No application source changed.

| Native case | Observed outcome |
|---|---|
| Same-size corrupt suite pack | Exit **3**, zero attempt records. A fresh cache rejected the immutable corrupt fixture; localhost supplied invalid replacement bytes and rejected the external HTTPS fallback CONNECT with 502. |
| SIGINT during active encode | Exit **130** after one completed warmup; owned encoder no longer alive. |
| Resume, then SIGKILL during later encode | Exit **−9** with a warmup and measured record already durable; owned encoder observed alive immediately afterward. |
| Resume after SIGKILL | Exit **0**; both prior record and artifact hashes unchanged; old process gone and active receipt removed. |
| Actual filesystem ENOSPC | A private 64 MiB HFS+ image reached zero available bytes, including a fresh one-byte write failing with **ENOSPC 28**. Native completed-journal replay returned **6** during an atomic attempt-file rewrite; all prior record/artifact hashes remained unchanged. |
| Replay after freeing the private volume | Exit **0**, exactly the same retained attempt set and hashes. Volume detached; original task queue restored with hashes unchanged. |
| Separate paused live-orphan recovery | SIGKILL returned **−9**. The identity-matched owned encoder was immediately paused with SIGSTOP, keeping it alive through package preparation. Native resume returned **0**, terminated that still-live owned orphan, removed its active receipt, and preserved the prior warmup record/artifact SHA before harness cleanup. |

The additional paused-orphan case distinguishes actual live-process recovery from merely removing a receipt after an orphan finishes naturally. PID, creation time, full command, ownership ancestry, process-group identity, signal, and paused status are captured. Cleanup only targets recorded PID/creation-time identities. All case deadlines completed without watchdog cleanup.

## Boundaries and unchanged inputs

Both fault sequences held the shared lock at `.build/release-20260914/mac-host-state/measurement.lock`; both release receipts are preserved. The installation pseudonym matches the final seven-clip acceptance: `installation-17a3f0bdfe484d859dc5daf069d82ef5d3580563d7c33e0ed2cbe15b7746b7f6`.

The two isolated queue directories use the same fixed protocol seed and therefore share deterministic campaign ID `campaign-250b62ed5aa9b145`. Queue paths distinguish these diagnostic repetitions. Neither queue should be uploaded or treated as independent collection evidence.

Each completed queue retains one warmup and two measured attempts. All four measured attempts retain `power-source-battery` suspect flags, actual `battery`, threshold `ac`, message “Measured repetition ran off AC power.” The tests ran under the observed battery/GPU conditions and make no calibration, throughput, environment eligibility, or PL claim.

The private filesystem reported 67,067,904 total bytes and zero available bytes after exhausting both large writes and small-file headroom (165 successful one-byte files, then ENOSPC). Before writing filler, the harness required a real mount, a device different from the host filesystem, and capacity no larger than 128 MiB. It never filled the host disk. Only task-owned filler was removed; the image remains as an unmounted local diagnostic artifact.

The final valid suite pack and all seven shared canonical input SHA-256 values match before and after the tests. The pre-existing corrupt fixture was reused read-only and its hash also remained unchanged. No shared pack, canonical media, or symlink target was modified. All original media stays under `.build/native-faults-939823e`; the committed packet contains metadata only.

All eight invocations recorded a frozen runtime within their own packaged `_MEI` directory, with FFmpeg SHA `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2` and ffprobe SHA `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66`. Those extraction directories are gone after native shutdown. No live owned process or mounted fault image remains. External helper/loader overrides were removed.

The platform/signing limits remain those of the [same package's seven-clip acceptance](../mac-seven-939823e/README.md): ARM64, complete runtime floor macOS 27.0, actual build 26A428, ad hoc signature without Developer ID/notarization certification.

## Evidence and reproduction

- `acceptance.json`: independently checked outcomes, retained attempt/flag inventory, cleanup, and input preservation.
- `original/`: 95 byte-preserving receipts, native logs, process/environment sidecars, completed journals, volume commands, and harness output. `original-file-checksums.json` binds copies to original paths and hashes.
- `harness/run_packaged_faults.py`: corrupt pack, interruption/resume, and private-volume execution. It delegates the bounded volume procedure to `run_disk_full.py`.
- `harness/run_live_orphan.py`: the additional live-orphan scenario with explicit SIGSTOP fault injection.
- `harness/seal.py`: read-only verification and metadata copying.

The execution harnesses intentionally use new task-owned paths and refuse reuse of already-created private-volume/live-orphan directories. Reproduction requires another isolated output root; do not overwrite this evidence. Run the seal using the existing release Python environment:

```sh
/Users/ofhd/Developer/Encoding_Database/.venv-release/bin/python docs/collection-readiness/mac-faults-939823e/harness/seal.py
```

Every client invocation used `--no-submit`; the only network interactions were the local corrupt-pack fixture and blocked proxy CONNECT. No P910 contact, real-server recovery, upload, authoritative analysis, or production-readiness certification is claimed.
