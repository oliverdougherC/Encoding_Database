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
FFmpeg decoder/filter/encoder threads, a 20 GiB download/storage limit and 5 GiB free
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

The plan explicitly names remaining grain/natural/screen-source coverage gaps.
Do not count one ballet scene twice to manufacture independent class coverage.
Perceptual scene suitability and downstream codec comparisons remain PENDING.

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
One warmup, two measured attempts and at most two variance-driven additions are
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
