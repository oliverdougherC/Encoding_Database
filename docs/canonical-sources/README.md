# Canonical source acquisition evidence

These are acquired source excerpts for the beta candidate. They are not a claim
that the final suite or deployment gates have passed. Final normalized media and
visual acceptance are recorded separately by the suite preparation workflow.

## Rights and provenance

* **Sol Levante SDR** — Netflix, Inc. / Production I.G, official Netflix
  `SolLevante/sdr/SolLevante_SDR_UHD_24fps.mov`. The actual object is SDR ProRes HQ,
  3840×2160, 24 fps, 10-bit 4:2:2, BT.709 limited range. The title-local license
  grants CC BY 4.0. This is the SDR master, not the HDR asset or a viewing preview.
* **Nocturne with film grain, SDR** — Netflix, Inc., official
  `Nocturne/nocturne_filmgrain/nocturne_60fps_uhd_filmgrain_sdr.mov`. The producer's
  readme expressly connects this asset to its title-local CC BY 4.0 license and
  documents added Filmbox Vision3 grain and ACES 2.0 conversion to Rec.709. This
  upstream SDR conversion is used, with no locally invented HDR conversion.
  Master properties: 3840×2160, 60 fps, ProRes, 10-bit 4:2:2, limited-range
  BT.709 matrix/primaries. Transfer metadata is absent; the producer documents
  the SDR conversion to 709. Audio/timecode are excluded from acquired excerpts.
* **Tears of Steel** — `(CC) Blender Foundation | mango.blender.org`. The Xiph
  `tearsofsteel-1080-png` readme identifies these as lossless original-render
  1920×800, 24 fps, 8-bit PNG frames and explicitly allows redistribution under
  CC BY 3.0. Each downloaded original frame is checked against the publisher's
  SHA256SUMS. The selected ranges contain no opening/end credits or sponsor
  logos. The license excludes logos/trademarks; portrait/privacy rights remain
  with the actors. These ordinary film excerpts carry no endorsement claim.

CC BY 3.0/4.0 allow sharing and adaptations, including prepared references and
retained benchmark encodes, subject to attribution, license and modification
notices. Preserve the title/creator/source links, original notices in `notices/`,
and the fact that excerpts are trimmed, losslessly repackaged and subsequently
normalized/encoded for benchmarking. Do not apply the software license or CC0
to these third-party media. Credits belong beside the pack, not burned into
benchmark frames. Source audio is not used.

## Alternative decisions

The Xiph per-asset notices for BoxingPractice, WindAndNature, BarScene and
Narrator say **CC BY-NC-ND 4.0**, despite Netflix's newer general open-content
page using CC BY 4.0. Those precise Xiph assets were rejected; the older notices
are preserved to make the decision auditable. No implied relicense was assumed.
BoxingPractice also contains only 254 frames (about 4.24 seconds), and Narrator
300 (about 5 seconds), insufficient for the selected ten-second scope.

NTIA SpeedBag/Aspen were considered and rejected because their notices restrict
use to research. They are not inputs to the distributed candidate.

The live-action Tears of Steel action excerpt is an **athletic-action proxy**
for high-motion-sports, with actor running/turning and fast camera/body movement
plus VFX, not literal sports footage. Its suitability must be supported by the
final visual review; the class label does not make the content actual sport.
Multiple ranges from one film reduce cinematographic diversity and are an
explicit candidate limitation. No scene is looped to extend duration.

## Reproduce and resume

Run from a checkout with the repository's pinned macOS FFmpeg present:

```
python3 scripts/acquire_canonical_sources.py sol-levante-flat
python3 scripts/acquire_canonical_sources.py nocturne
python3 scripts/acquire_canonical_sources.py tos-action
python3 scripts/acquire_canonical_sources.py tos-dialog
python3 scripts/acquire_canonical_sources.py nocturne-dark
python3 scripts/acquire_canonical_sources.py chimera-natural
```

Use `--ffmpeg /path/to/locked/ffmpeg` on another platform and record that binary's
hash. `catalog.json` pins source URLs and selected ranges. The script reserves
5 GiB by default, bounds network retries to three, and verifies cached hashes.
Completed media are reused only when their recorded SHA256 matches; corruption
is an explicit failure, never silently accepted. PNG acquisition resumes per
original frame. MOV acquisition resumes using eight-MiB byte blocks, each
independently hashed; failed partial Matroska files are regenerated from the
verified source-block cache. Conditional range requests use the source ETag.

The source cache is under `.build/canonical-sources/`, excluded from Git. The
acquisition JSON records every retrieved byte range or complete PNG input,
source-object reported size, original/final hashes, FFmpeg binary hash and exact
command. A remote MOV is **partially downloaded**; `whole_master_sha256: null`
means the entire 16/95-GB file was not fetched and no whole-master hash is
invented. The excerpt checksum describes the local repackaging, not the remote
master. The PNG inputs are complete individual frames from a partial movie.

Large sources and final references must be placed in the approved durable
candidate artifact storage by the release workflow. This directory's acquisition
records alone do not prove artifact publication, retention or clean acquisition.

## Selection revisions after actual inspection

The original exploratory source IDs remain immutable in the catalog/evidence and
where staged. They are not accepted merely because they were downloaded:

| Current candidate | Range | Selection basis |
| --- | --- | --- |
| `sol-levante-flat` | 173–181 s, 192 frames | Cel character/face, smooth fields and hair lines; ends before extended abstract effects. Eight seconds avoids substituting effects for flat fields. |
| `nocturne` | 90–100 s | Producer-added film grain; parent normalization/crop review determines preservation. |
| `nocturne-dark` | 148–158 s | Dark staircase/window, blue-purple gradients, silhouetted piano/interior, separate range from grain. |
| `tos-action` | PNG11713–11952 inclusive (488–498 s) | Live-action athletic movement/camera action with VFX; transparent sports-action proxy. |
| `tos-dialog` | PNG5761–6000 inclusive (240–250 s) | Sustained three-face medium close-up, skin/beard and speaking motion. |
| `chimera-natural` | TIFF360–599 inclusive (15.015–25.025 s at 24000/1001) | Natural hillside/ground/foliage and camera movement. Real HDR→SDR preparation still required. |

Rejected exploratory ranges: `sol-levante`90–100 s is turbulent lava/effects,
`tos-dark`530–540 s is too well-lit, `tos-talking`290–300 s cuts away from faces,
and `tos-natural`25–35 s has defocused foliage behind actors. Their retained
metadata documents the real selection process and must not be confused with
final accepted references. The final preparation/visual report is authoritative.

Chimera uses the official title-local CC BY 4.0 license, not the rejected Xiph
WindAndNature ND asset. Its graded RGB48 TIFFs are identified as DCI4k2398p
HDR P3/PQ by the official catalog/object names. The TIFFs have no embedded color
metadata or mastering peak; no peak-nit mastering claim is made. Capacity-aware
acquisition decodes exact TIFF inputs, records hashes and then spatially reduces
them to 1920×1012 RGB16 PQ (Lanczos, square pixels), retaining a separate
**spatially normalized HDR source excerpt**. This is not called a lossless copy
of the original 4K master. Storage of the resulting samples is lossless FFV1;
parent preparation must perform real documented tone mapping and SDR conversion.
Each 24-frame segment is hash-verified for resumption; original TIFF container
files are removed after the segment is recorded, with exact input hashes kept.
The publisher remains the recovery source for original TIFF bytes.

`staged-source-artifacts.json` lists actual prerelease-staged source MKVs,
matching GitHub API SHA256/size and anonymous range-download checks. Large raw
cache directories for those staged files may be removed after verification;
the local and durable MKVs plus exact original fetched-input hashes remain.
Staging an exploratory source is not final class acceptance.
