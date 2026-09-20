# Corrected native runtime candidate

The unpublished 1.3.0-rc.1 candidate uses protocol 7.1 and client 0.3.0.
The original 1.2.0 macOS helper is Intel-only and has no SVT-AV1. It remains
historical evidence; it is not relabeled as the new runtime.

On the available Mac, FFmpeg 9.0 is arm64 and exposes libx264, libx265,
libsvtav1 and VideoToolbox. The complete bundle requires **macOS 27.0** according
to its load commands. The September 19 full-library scan corrected the earlier
26.5 claim: FFmpeg requires 26.0 and the rebuilt VMAF library requires 26.5,
but `libpcre2-8.0.dylib` and `libharfbuzz.0.dylib` both declare `minos 27.0`.
The exact `939823e` package manifest records the complete runtime floor; its
embedded-only smoke passed on macOS 27.0 build 26A428.
This is a restricted native candidate, not proof of compatibility with older
macOS, Intel macOS, Windows or Linux. The bundle contains 102 executable/library
files, approximately 93 MB. Every relocated library is ad-hoc signed. This is
neither Developer ID signing nor notarization.

CI uses the reviewed 36 MiB archive at
`client/resources/runtime/archives/macos-arm64-ffmpeg9-vmaf3.2.tar.gz`, SHA256
`1ef24cb8cbf23b9e1dbeeda40a58ff5f0a30e9254a324702f1b81a6953ea0c07`.
Keeping this candidate input alongside its lock avoids a dependency on an
unpublished release asset or broader CI credentials. The archive contains the
dependency hash manifest, installed package notices and pinned Homebrew formula
provenance. The macOS 26 CI job is an additional compatibility probe, not proof of
support below the bundle's declared 27.0 floor. Actual native CI results remain
required. The old Intel runtime release asset is retained.

The first native model test failed: the installed Homebrew libvmaf exposed the
filter but lacked the frozen model's Speed_chroma extractor. The replacement
was built from VMAF 3.2.0, the same pinned source as the server image:
`a28f93f3b4fa65601be324587072e32a6a704a304ba7b1aec9b70b3f709bc1dc`.
The default local macOS 27 SDK failed its compiler sanity check; the available
26.5 SDK compiled successfully. No system SDK or Homebrew files were modified.

Reproduction from the repository root (tools: curl, Meson, Ninja, Apple tools):

```bash
mkdir -p .build/native-vmaf-3.2.0
curl --fail --location https://codeload.github.com/Netflix/vmaf/tar.gz/refs/tags/v3.2.0 \
  --output .build/native-vmaf-3.2.0/source.tar.gz
echo 'a28f93f3b4fa65601be324587072e32a6a704a304ba7b1aec9b70b3f709bc1dc  .build/native-vmaf-3.2.0/source.tar.gz' | shasum -a 256 -c -
tar -xzf .build/native-vmaf-3.2.0/source.tar.gz --strip-components=1 -C .build/native-vmaf-3.2.0
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
  meson setup .build/native-vmaf-3.2.0/libvmaf/build26 .build/native-vmaf-3.2.0/libvmaf \
  --buildtype=release -Denable_tests=false -Denable_docs=false -Denable_float=true -Dbuilt_in_models=true
ninja -C .build/native-vmaf-3.2.0/libvmaf/build26
python3 scripts/bundle_macos_runtime.py --ffmpeg /opt/homebrew/bin/ffmpeg \
  --ffprobe /opt/homebrew/bin/ffprobe \
  --libvmaf .build/native-vmaf-3.2.0/libvmaf/build26/src/libvmaf.3.dylib \
  --output .build/runtime-macos-arm64-vmaf3.2
python3 scripts/verify_runtime_model.py \
  --ffmpeg .build/runtime-macos-arm64-vmaf3.2/ffmpeg \
  --ffprobe .build/runtime-macos-arm64-vmaf3.2/ffprobe \
  --output-dir .test-reports/release-20260914/native-model-vmaf32
```

The bundle directory is create-only. Its manifest records original and relocated
hashes. Lock registration must run after relocation and signing, including every
dylib, before packaging. `build_macos_client.sh` packages the entire `lib/` tree
beside the helpers. A downloaded runtime requires that exact manifest/lock, not
whatever Homebrew happens to provide later.

The actual pinned-model check passed all 240 frames of the frozen athletic clip
with VMAF mean 97.574079. See
[the receipt](release-evidence/20260914/native-macos-model.json). This is runtime
compatibility evidence, not calibration, native contribution certification or
an accepted production run. Distribution licensing/notices and final packaged
launch/recovery are separate release checks.
