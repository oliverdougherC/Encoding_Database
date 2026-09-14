# Validation-only longer scenes — controlled preparation

These files are a source-preparation record, not calibrated PL or human perceptual
approval. The frozen public suite, source catalog and scoring constants are unchanged.

The declared plan uses already licensed Nocturne, Sol Levante and Tears of Steel
masters. Local retained assets were only short excerpts/stills, so new disjoint
ranges are fetched with bounded HTTP requests. Whole-master SHA-256 is **not known**
for ranged MOVs: each fetched block is hashed, the original video packet-payload
sequence is hashed, and the normalized lossless reference has its own SHA-256.
Publisher PNGs are checked against the retained publisher checksum manifest.

Preparation runs serially on authorized P910 under
`/mnt/NVME/docker/encodingdb-operations/20260914-validation-holdouts`, with two
FFmpeg decoder/filter/encoder threads, an 80 GiB total download allowance, a 20 GiB working-storage limit and 5 GiB free
space reserve. The Mac's constrained disk is used only for small receipts/images.
`media/PAUSE` prevents starting the next scene; coordinate native benchmark timing
with the integrator after all active preparation/worker/build jobs finish.

Normalization mirrors `scripts/prepare_canonical_references.py`: Nocturne 60 fps
uses explicit 24 fps frame selection, documented SDR BT.709 limited ProRes sources
are Lanczos-downsampled to 1080p YUV420P, and PNG RGB/sRGB uses explicit BT.709
transfer/matrix conversion plus cinematic letterboxing. No loops, denoising,
interpolation, metadata-only HDR relabeling or altered public clips are used.
The Linux pinned runtime differs in architecture/build from the old Mac source
preparation runtime; exact hashes/commands are recorded and bit-identical rendering
across runtimes is not asserted.

## Scene and source folds

`plan-v1.json` fixes source-frame ranges, sourceGroupId and sceneGroupId before
encoding or score analysis. Scene-disjoint experiments exclude the full selected
scene from fitting. Source-group experiments exclude the entire master, including
both frozen Nocturne classes when holding out Nocturne. These are distinct claims;
a different frame range in the same movie never establishes master independence.

All seven content classes now have distinct 30-second validation references; see
`source-readiness.json` and the final registered manifest. The ballet, grain and
dark cases use different Nocturne ranges and settings; source-level folds still
exclude the entire Nocturne master. Perceptual suitability and downstream codec
comparisons remain PENDING.

## Controlled measurement and authoritative retention

`build-validation-source-registry.mjs` builds a create-only registered source
manifest from actual completed preparation receipts and matching media bytes.
Registration uses `encodingdb-validation-holdouts-v1` and `validation-*` workload
IDs. Public canonical intake continues to reject these IDs.

```sh
node scripts/build-validation-source-registry.mjs --media-root '<task>/media' --output '<new registry.json>'
python scripts/run-validation-campaign.py --registry '<registry.json>' --workload validation-nocturne-ballet-30s --reference '<task>/media/nocturne-ballet-30s/reference.mkv' --output '<task>/campaigns' --encoder libx264 --preset fast --crf 23
VALIDATION_DATABASE_URL='<isolated encodingdb_validation_* PostgreSQL URL>' node scripts/import-validation-campaign.mjs --campaign '<completed validation-campaign.json>' --registry '<registry.json>' --storage-root '<task>/validation-artifacts'
```

Measurement reuses the corrected client `encode_to_artifact`, `EncodeTiming`,
`execute_protocol_campaign`, environment sampling and fsynced CampaignJournal.
A positive finite `--max-duration-minutes` (default 60) wraps the shared MeasurementBudget.
Exhaustion preserves the journal and returns exit 11; resume with the same saved
seed/recipe/source and an explicit new allowance. One warmup, two measured attempts
and at most two variance-driven additions are
retained; metrics/upload never run between timed attempts. The initial runner
supports explicit libx264/libx265/libsvtav1 CRF cells only. Hardware holdout cells
remain separate required work; no substitute encoder is chosen. Unstable timing
fails closed while preserving the local journal.

The operator importer requires a separately named `encodingdb_validation_*`
database and task-owned storage. It seeds only registered source/run identities
and uses the real ArtifactPipelineService/FfmpegArtifactAnalyzer with durable
queue ownership, lease renewal and exact installed model/worker. Derived score
recomputation is disabled: these observations cannot generate public frontiers.
All measured artifacts and complete authoritative distributions remain retained;
SUSPECT analyses retain their flags and require genuine exact-analysis review.

Calibration exports preserve each row's sourceSuiteVersion, sourceSha256 and
sourceRegistrationHash. Live retention validation checks the installed registry
against actual TestClip data. Validation-only media are permitted only in HOLDOUT;
CALIBRATION remains restricted to the frozen suite. No arbitrary contributor
source upload or operator credentials are added to distributed clients.

Namespace regressions were executed on isolated PostgreSQL: valid registered
HOLDOUT accepted; CALIBRATION relabeling, frozen-suite masquerading, source/hash
mismatch and absent operator registry rejected. Full native runner execution is
still pending the integrator's quiet host window and final integrated code.

The cross-database path is now implemented and rehearsed; see `combined-evidence/README.md`. It preserves measured identities and uses an explicit read-only activation binding. The controlled importer also retains exact fractional milliseconds and the complete observed environment-validity wrapper. Native controlled-runner execution still awaits the coordinated quiet window.


## Executed source results

Seven references total 210seconds/5,040frames, each 30seconds/720frames at 1920×1080,
24 fps YUV420P SDR BT.709. Total normalized reference bytes: 5,499,942,827. Every
reference passed complete decode, exact frame/cadence/duration checks and retained
SHA-256 verification. Final registry hash:
`023d5490161da7c22d0534b7af968630ffaa8fb263b864c7270a7cbee9c5df76`.
The Mac authored screen capture used 329MiB total and no frozen screen PNG hash was
reused. Exact metadata, source records and contacts are in per-scene directories.
Full lossless references are on P910 in the task-owned media tree.

The natural-source pipeline was corrected to match the canonical acquisition order:
resize P3/PQ RGB to 1920×1012 with 16-bit preservation, then the existing tone map.
Earlier 384-frame linear-first intermediates remain quarantined and unregistered.
All 384 original TIFF hashes match the corresponding final acquisition hashes;
this correction changed processing order, not the selected source material.
The authoritative native frame-rate field and executed commands use 24000/1001;
a descriptive typo in the archived plan text is recorded in `visual-inspection.json`.

Attribution: Nocturne and Chimera © Netflix, Inc.; Sol Levante © Netflix, Inc. and
Production I.G, distributed under CC-BY-4.0 via Netflix Open Content. Tears of Steel
© Blender Foundation/Mango Open Movie Project, CC-BY-3.0 via the publisher-checksummed
Xiph archive. Original URLs and license URLs accompany every source receipt.
Authored Atlas content is CC0; the reused IBM Plex Mono font is SIL-OFL-1.1.
These modified excerpts are validation-only and do not imply endorsement.
