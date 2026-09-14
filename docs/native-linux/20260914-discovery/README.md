# P910 Linux candidate preparation — 2026-09-14 UTC

Runtime preparation passed. This is **not** final packaged-client, NVENC, seven-clip campaign, or production certification. No production containers, volumes, configurations or records were changed; no benchmarks were submitted. Existing frozen suite bytes were read from the previous operation's cache and extracted into this task's isolated cache.

## Host and isolated workspace

- Authorized host: P910, `ofhd@100.99.6.59`, Linux 6.8.0-139-generic x86_64, glibc 2.39.
- Dual Xeon E5-2699 v4, 44 physical cores / 88 threads, 125 GiB memory. Discovery snapshot: 83 GiB available, 1.6 TiB free on NVMe.
- Device 0: NVIDIA GeForce GTX 1070, 8 GiB, driver 580.173.02; NVENC driver libraries present. Discovery snapshot: 0% GPU utilization, 3 MiB used. Encoder presence is not native RC execution certification. AV1 hardware encoding is not claimed for this GPU.
- Task root: `/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate`.
- `source/discovery-21beba9f` is an archived **intermediate** source snapshot of `21beba9f74919ca0c5041a81edad9a1f5a865b8b`, used only for runtime verification.
- `source/final-candidate` is an empty initialized Git repository reserved for the exact final integrated commit.
- `cache/canonical` contains all seven final references. Every clip hash matched the frozen manifest. Source pack SHA256: `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`.

## Verified native runtime

System FFmpeg 6.1.1 contains x264/x265/SVT/NVENC encoders but lacks libvmaf and XPSNR; it is unsuitable for the locked release.

The existing reviewed Linux bundle is suitable without substitution:

- [BtbN pinned archive](https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-09-14-51/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1.tar.xz), SHA256 `1288c1e46efce263651f5b10755f9ef11419a91558407fe61cc178aa9869fa1b`.
- Native ELF x86_64 FFmpeg and ffprobe; exact hashes match the tracked runtime lock. See `runtime.sha256`, `architecture.txt`, `runtime-lock-verification.json`.
- Verified advertised encoders: libx264, libx265, libsvtav1, h264_nvenc and hevc_nvenc. Verified filters: libvmaf and xpsnr.
- Measured VMAF JSON reports revision `e80d6c5`, resolved to [e80d6c593e6e2327687dccd00b7cc9c91036d79f](https://github.com/Netflix/vmaf/blob/e80d6c593e6e2327687dccd00b7cc9c91036d79f/libvmaf/meson.build), whose Meson project version is **3.2.0**.
- The actual pinned model `e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e` ran on all 240 frames of athletic-action reference `1e06fe0315d0cb90247a3dae2258327989e657496247ca8974ddd8c2431755de`. Mean VMAF 97.550546. This is runtime verification, not calibration evidence. The verifier received an explicit reference path, so its `frozenQuickReference` flag is false; the reference bytes were separately checked against the frozen manifest.

Exact command (exit 0):

```bash
cd /mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate
timeout 180 native-build-venv/bin/python source/discovery-21beba9f/scripts/verify_runtime_model.py \
  --ffmpeg runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin/ffmpeg \
  --ffprobe runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin/ffprobe \
  --reference cache/canonical/athletic-action-1080p24-final.mkv \
  --output-dir evidence/runtime-model
```

The encoded clip, exact model copy, stdout/stderr, metrics and command list remain at `evidence/runtime-model` on P910. Selected reports are archived alongside this receipt.

## Build prerequisites

Host Python 3.12.3 lacks pip and ensurepip. Initial `python3 -m venv` failed for that reason. No system packages were installed.

A self-contained native Python 3.11.16 was downloaded from [python-build-standalone 20260901](https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.11.16%2B20260901-x86_64-unknown-linux-gnu-install_only.tar.gz), archive SHA256 `faa0758583a63f14c5eee516af82738403b59c13edda6fc0a21d953febd89eed`, verified against the GitHub asset digest. It lives at `python/bin/python3` and successfully creates complete venvs. `native-build-venv` has the repository's pinned build requirements, including PyInstaller 6.19.0; see `native-build-dependencies.txt`. An earlier task-only system-Python venv also has bootstrapped pip but should not be used by the build script because its base interpreter still lacks ensurepip.

## Next commands and remaining gates

The integrator must first transfer a Git bundle containing the **final** commit, fetch it into `source/final-candidate`, and check out that exact SHA. Do not build the intermediate discovery snapshot as the final client.

After checking out the final source and verifying its reviewed Linux lock remains the one above:

```bash
cd /mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/source/final-candidate
ln -s /mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/cache/canonical client/resources/test_suite_v1/canonical
PATH=/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/python/bin:$PATH \
ENCODINGDB_FFMPEG_PATH=/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin/ffmpeg \
ENCODINGDB_FFPROBE_PATH=/mnt/NVME/docker/encodingdb-operations/20260914-native-linux-candidate/runtime/ffmpeg-n8.1.2-51-g7ba069f4f1-linux64-gpl-8.1/bin/ffprobe \
bash scripts/build_linux_client.sh
```

The build script may remove its own output pack, so **never** set `ENCODINGDB_SUITE_PACK_PATH` to the existing production/previous-operation pack. Default output remains inside the task-owned final checkout.

Remaining empirical gates: exact final executable/helper/model/lock hashes; clean-cache launch; actual NVENC selected-device/native RC behavior and unsupported choices; seven-clip artifact contribution against an integrator-approved isolated service; cancellation/offline/backpressure/resume and retained-result publication; parent-authorized production submission. Runtime discovery does not certify a broad Linux minimum-version matrix.
