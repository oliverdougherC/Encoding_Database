# First canonical Mac timing cell — b3ef24a

**Historical checkpoint: 1 of 840 planned canonical cell/sessions completed timing;
0 authoritative quality analyses and 0 human reviews for this cell.** This packet
freezes the first invocation only. Later batches may advance the live ledger; this
snapshot is not a live progress counter or a complete-matrix claim.

The source-pinned packaged client ran `libsvtav1`, preset `6`, native CRF `20`, on
`animation-1080p24-final` with fixed derived seed `25494854976677863`. The selected
cell was the first item in the unchanged frozen order, not a replacement recipe.
The retained campaign is `campaign-c9670ced0b800098`.

| First invocation result | Recorded evidence |
| --- | --- |
| Allocation / execution | One software cell; `--no-submit`; exit 0 |
| Start / end UTC | `2026-09-20T04:19:12.280335+00:00` / `2026-09-20T04:20:30.741508+00:00` |
| Invocation wall time | 78.46 seconds, including cell preparation; not encode-only throughput |
| Retained attempts | One warmup + two measured attempts, all VALID |
| Timing stability | Two counted measurements; relative spread 0.211063%, below unchanged 3% threshold |
| Retained artifacts | 3 files, 43,791,636 bytes total |
| Completed root integrity audit | 3 matching artifact hashes, 192 frames each, 576 frames total; 1920×1080, 24 fps |
| Authoritative quality / human review | 0 / 0 for this cell |

The actual measured encode intervals are 2.791900375 and 2.786013917 seconds;
the warmup is 2.850188708 seconds. The three independent execution records happen
to retain byte-identical media hashes. They remain three original attempts, not
three machines or three distinct content samples.

## Immutable bindings

- Application source: `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2`.
- Packaged executable SHA: `443e293e82f0f042b2017f55d12f1d73c7d5b6944cb43d6c9d70281beef6d70c`.
- Matrix file SHA: `28471be198b342733d57c0dcd75dc3fcef257d9ca96a4adc136d1b2ea812d373`.
- Runner SHA: `63c267aad259b24f50e71d540454b5e7563bf0473ce55a0717e25e8f5a4595bd`.
- Execution-plan hash: `95fa4957bc2f610efabe783933b763c94362bf4fbf2447f5f5fd0986e50d0417`.
- Existing Mac installation: `installation-17a3f0bdfe484d859dc5daf069d82ef5d3580563d7c33e0ed2cbe15b7746b7f6`.
- Master seed/session selection: `20260914`, sessions `1,2`; slots `source-a` and
  `videotoolbox-host` remain in the complete host plan.
- Protected first-ledger SHA: `ea5daccc0da716d15e7ceacc6350a944f46a1bfc81acc84b9de2d3b77ebba57c`.

`mac-first-invocation-ledger.json` is a byte-preserving copy of the coordinator's
protected `mac-first-canonical-ledger.json`, not a reread of the live ledger after
later batches. Its SHA matches the root's completed audit. The snapshot contains
one completed cell and an untouched next-VideoToolbox placeholder with **zero
calls**. That placeholder is not a second execution or completion.

`first-cell/` preserves original campaign manifests, attempts, environment snapshots,
process checkpoints, completion, prepared submission metadata and protocol results.
`operator/` preserves the exact first allocation, preflight, launch script, client
log, outer runner log and root integrity audit. `original-file-bindings.json` binds
each copied metadata file to its original path, byte count and SHA; `files.json`
seals this packet. Absolute original paths are retained without rewriting records.
No MP4, source media, executable or suite pack is included.

## Recorded sequencing amendment and allocation

The original proposal placed publication demonstration before canonical timing.
The coordinator's first-cell allocation explicitly allowed **one independently
journaled no-submit software cell** after exact-package native execution,
retention/fault proof and the full artifact audit, while P910 continued separate
native acceptance. This is a sequencing amendment, not evidence that publication
has passed. Publication demonstration remains mandatory before upload acceptance,
fitting or release; all validity, retention, review and release gates remain intact.
The amendment changes no matrix, recipe, source/runtime, seed/order, repetition or
stability rule. The exact rationale and unchanged fields are in
`operator/mac-first-canonical-allocation.json` and `checkpoint.json`.

This allocation capped execution at one cell, 30 minutes per cell, 45 minutes per
invocation, 8,192 MiB total retained task storage, 1,024 MiB per cell and a 5,120 MiB
real disk reserve. The runner recorded 19,328,630,784 free bytes at admission.
The shared original host measurement lock and persistent identity were used.

The preflight was on AC. Software was VALID at 32.575% observed background CPU.
The simultaneous VideoToolbox preflight was **SUSPECT** at 37.5% GPU load against
35%; that observation is preserved. This first allocation was software-only and
authorized no hardware cell. Later readiness and allocations have separate records
and do not retroactively change this snapshot.

## Storage-only deduplication receipts

The two root receipts are retained verbatim:

- `operator/mac-verified-pack-deduplication.json`: three verified duplicate pack
  copies replaced by relative symlinks; recorded duplicate bytes 4,520,670,054
  (approximately 4.52 GB).
- `operator/mac-canonical-capacity-deduplication.json`: four further verified
  duplicate pack copies replaced by relative symlinks; recorded duplicate bytes
  6,027,560,072 (approximately 6.03 GB). This later storage operation is included
  for provenance and does not advance the first-cell timing count.

Both receipts bind the unchanged pack SHA
`d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150`
to the preserved `package-f673170` original. Only task-created identical pack
copies were deduplicated; encoded evidence, binaries and corrupt-pack evidence
remain preserved. This archival task did not rehash media or packs, probe files,
run tests, launch timing or contact a host. Artifact integrity/frame results above
come from the coordinator's completed audit; archival checks covered only metadata
copies, recorded hashes, bindings and arithmetic.
