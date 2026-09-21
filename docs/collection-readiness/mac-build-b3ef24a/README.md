# Mac b3ef24a packaged build and embedded smoke

The revised native ARM64 package from clean source `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2` built successfully and passed the recorded embedded-runtime smoke. This archive contains original JSON/checksum receipts, selected numbered build-log excerpts and a later read-only signature inspection. It contains no executable or media.

| Recorded command | Exit | Elapsed | Scope |
| --- | ---: | ---: | --- |
| `--help` | 0 | 6.705 seconds | Packaged executable startup and CLI help |
| `--codec libx264 --presets fast --crf 24 --no-submit --max-duration-minutes 10` | 0 | 104.282 seconds | Packaged default suite smoke with retained local results; preparation took 87.899 seconds |

Both commands report no timeout, forced cleanup or surviving owned process. The smoke receipt records `frozen: true`, helpers loaded beneath its actual `_MEI` extraction directory and runtime fingerprint `a3929406d94ea18976b7ba56c5b6991d0d70cf27ec9b544c76c319ad2f0db659`. The original embedded archive audit passed all 102 helper/dependency entries with no issues. No command was rerun for this archival task.

**This is not final seven-clip acceptance for b3ef24a.** That Mac run remains pending because battery readiness held execution. This packet also establishes no hardware-codec timing, successful submission, authoritative quality analysis or PL readiness.

## Source, platform and signing

The original release manifest records candidate version `1.3.0-rc.1`, protocol `7.1`, client `client/0.3.0`, Python `3.14.6` and a clean tracked source checkout. Its source pin agrees with the detached build checkout. The original build log records PyInstaller `6.19.0` on macOS 27.0 ARM64.

The executable is thin ARM64. The package's minimum OS from all inspected headers is **macOS 27.0.0**; the manifest identifies bundled `libpcre2-8.0.dylib` and `libharfbuzz.0.dylib` at that floor. The outer executable alone declares 11.0.0, which does not lower the full package's requirement. The recorded smoke ran on macOS 27.0; no earlier-macOS execution is claimed.

A read-only `codesign -d --verbose=4` inspection of the exact freshly hashed original reports `Signature=adhoc`, `flags=0x2(adhoc)` and `TeamIdentifier=not set`. This is not Developer ID signing or notarization. The original release/signing JSON reports `unsigned` because no release-signing evidence was supplied; those receipts are preserved byte-for-byte, and the separate inspection makes the ad-hoc signature explicit.

## Artifact identities

| Item | SHA-256 |
| --- | --- |
| Packaged executable, 124,388,240 bytes | `443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c` |
| Embedded FFmpeg 9.0 | `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2` |
| Embedded FFprobe 9.0 | `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66` |
| Package-filtered runtime lock file | `5db0f9c3d5178f2bad9a84cced0141df44b82532314c7e5e30f401f47e7262b0` |
| Model `vmaf-v1-sdr-1080p` / `v1.0.16_3d0h` | `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e` |
| Frozen suite pack, 1,506,890,018 bytes | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |

The frozen suite fingerprint remains `d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e`. Helper hashes agree across the original smoke identity and embedded archive audit. The model hash was freshly checked against the pinned source model. The original executable and small checksum-listed receipt files were freshly hashed and matched. To keep archival work bounded, the 1.5 GB suite pack was not reread: its SHA agrees between the existing build checksum receipt and release manifest, and its original file size was checked.

`verification.json` records original paths, the whole original build-log SHA, individual checks, command results and limits. `files.json` seals this archive's documents. The numbered build excerpts preserve build provenance, warnings, target architecture, signing actions and completion while omitting routine dependency-hook chatter. The warnings about unavailable Tk and `libnvidia-ml.so.1` are retained; this Mac CLI smoke makes no Windows GUI or NVML claim.

## Storage provenance after the build

The parent subsequently SHA-verified three task-created duplicate suite packs and
replaced only those copies with relative symlinks to the preserved
`package-f673170/encodingdb-test-suite-v1.tar.gz`, reclaiming 4,520,670,054 bytes.
This includes the b3ef24a and 939823e pack paths. `pack-deduplication.json` preserves
that operation's receipt and matching pack SHA. The b3ef24a relative symlink and
target size were checked while archiving. Pack bytes and all binaries, encoded
artifacts and corrupt-pack evidence remain preserved; the operation changes
storage layout, not the build or smoke result.
