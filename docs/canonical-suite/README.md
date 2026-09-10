# Canonical candidate preparation and review

The launch scope is seven SDR references at 1920×1080, 24/1 fps, progressive,
8-bit 4:2:0 BT.709 limited range, without audio/subtitles/data. FFV1 level 3
preserves the prepared reference; it does not undo source ProRes compression,
spatial reduction, color conversion or bit-depth reduction. The pinned quality
model is `vmaf-v1-sdr-1080p`, model SHA
`e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e`.

The development suite already used the v1 label. Final references use new clip
keys, manifestVersion 2, actual source hashes, and a new immutable suite lock.
Never update a registered historical TestClip in place. Historical fixture bytes
remain in Git history; historical pilot/calibration records stay separate and
test-only contexts remain disabled. PL calibration and longer holdouts are
post-release work, not prerequisites for unscored evidence collection.

| Class | Selected source | Range | License |
| --- | --- | --- | --- |
| high-motion-sports | Tears of Steel athletic action with VFX | PNG 11713–11952, 488–498 s | CC BY 3.0 |
| fine-natural-detail | Chimera HDR hillside/vegetation | TIFF 360–599, 24000/1001 fps | CC BY 4.0 |
| film-grain-noise | Nocturne producer-added-grain SDR master | 90–100 s at 60 fps | CC BY 4.0 |
| dark-gradients-shadows | Nocturne producer-added-grain SDR master | 148–158 s at 60 fps | CC BY 4.0 |
| animation-flat-fields | Sol Levante SDR master, smooth face/cel shading | 173–181 s at 24 fps | CC BY 4.0 |
| screen-text | Original offline Atlas browser workflow | frames 0–239 at 24 fps | CC0; font OFL |
| talking-head | Tears of Steel sustained group dialogue | PNG 5761–6000, 240–250 s | CC BY 3.0 |

Source acquisition inventory, exact URLs, original fetched-frame/byte-range hashes,
license snapshots, original media properties and rejected choices are in
[`../canonical-sources/`](../canonical-sources/README.md). A fetched-range hash is
not a checksum of the undownloaded entire movie. TIFF input hashes pin the exact
fetched originals; ToS PNGs additionally match publisher SHA-256 checksums.

## Reproduce

Run from the repository root with Python 3.11+ and the project's client
dependencies. Acquire the six selected source IDs from the committed catalog:

```sh
python3 scripts/acquire_canonical_sources.py tos-action
python3 scripts/acquire_canonical_sources.py chimera-natural
python3 scripts/acquire_canonical_sources.py nocturne
python3 scripts/acquire_canonical_sources.py nocturne-dark
python3 scripts/acquire_canonical_sources.py sol-levante-flat
python3 scripts/acquire_canonical_sources.py tos-dialog
node scripts/capture_canonical_screen.mjs
python3 scripts/prepare_canonical_references.py
```

The preparation script requires the exact retained `ce9d181444` macOS FFmpeg
under `.build/runtime-macos-old/ffmpeg` (or `--ffmpeg`). Obtain it from the
[nonproduction runtime archive](https://github.com/oliverdougherC/Encoding_Database/releases/download/encodingdb-beta-review-assets-20260909/encodingdb-macos-runtime-ce9d181444.tar.gz),
SHA-256 `718e85b630bdcdb93f257a99ffcf6d57bf42645bd0f5bebffc1ac57e64236c64`.
It is used only for reproducible source preparation. The newer shipped runtime
is separately pinned in `client/resources/runtime/ffmpeg-lock.json`; actual
model execution exposed missing CAMBI support in the old runtime.

The screen capture pins Playwright, Chromium, viewport, explicit frame times and
the checked-in OFL font. See `scripts/canonical-screen/README.md`. Reproduction
on other operating-system rasterizers is not asserted bit-identical. Original
PNG hashes, browser and executable identity are retained in the screen evidence.

Preparation writes original-input hashes, exact commands and output hashes to
`.build/canonical-prepared/*-preparation.json`; committed copies are in `evidence/`.
All source and final inputs stay distinct. No loops, interpolation, denoising,
source credits baked into pixels, or metadata-only HDR conversion are used.

Chimera is converted from P3-D65/PQ through linear light at a 100-nit reference
white, BT.709 primaries, Hable tone mapping with explicit 4000-nit input peak,
then BT.709 limited range with error-diffusion reduction to 8-bit 4:2:0. The peak
is a documented preparation choice; it is not invented mastering metadata.
The measured source component maximum in a sampled frame was approximately
4184 nits. Upstream TIFFs are spatially reduced to 1920×1012 during bounded
acquisition to control disk use; these are labeled normalized source excerpts.
Even-pixel rounding changes aspect by less than 0.05%; final 34-pixel bars retain
the full frame. ToS preserves native 1920×800 pixels with 140-pixel letterbox
bars and an explicit display-RGB sRGB-to-BT.709 conversion.

## Actual validation and limits

`scripts/validate_canonical_media.py` executes complete decode/probe, timestamps,
frame hashes and duplicate counts, black-span diagnostics, contact sheets and
detail frames. It runs x264 CRF 20/28/36, x265 CRF 28, auxiliary SVT-AV1 CRF 32,
and actual available VideoToolbox at 2500 kbit/s, then checks encoded frame
identity/timing, packet bitrate, the pinned VMAF frame distribution and XPSNR.
Reports identify the exact runtime used. SVT-AV1 was exercised with the recorded
Homebrew runtime; it is not falsely claimed to be in the macOS Evermeet bundle.
Full reports and playable encoded previews are staged with the candidate.

Visual review is Codex inspection of sampled temporal contact sheets and full
resolution frames, not Oliver's approval or a claimed human playback review.
The action clip is an athletic-action/VFX proxy, not footage of a sporting
event; future sports-specific generalization needs longer holdouts. The natural
clip stresses soil/vegetation texture and camera motion, not a wind-only foliage
scene. Animation uses smooth shaded skin and fine outlines rather than uniform
flat backgrounds. Grain and dark clips share a title but use disjoint ranges;
the producer explicitly added grain. Letterbox regions reduce active pixels
and affect full-frame metrics. These limitations remain visible to the deployment
reviewer and must not be hidden by relabeling the sources.

The review JSON and per-clip notices record evidence-backed candidate acceptance.
Human deployment approval remains pending. The existing finalizer, drift checker,
and acquisition verification retain their fail-closed gates.
