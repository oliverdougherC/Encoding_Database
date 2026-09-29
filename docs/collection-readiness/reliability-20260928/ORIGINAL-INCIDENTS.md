# September 28 original-run evidence, before repair

This is a read-only inventory of the owner's retained runs. It records what the
original files and current backend prove. The original state on each machine
was not cleared or resumed during this inventory. Private byte-for-byte copies
and SHA-256 file inventories are retained locally under
`.test-reports/reliability-20260928/original-{mac,windows,linux}-state/`.
Every copied file was compared by SHA-256 with its original: macOS 5,247/5,247,
Windows 815/815 and Linux 240/240 matched.
The independent read-only `scripts/campaign_conservation.py` reported zero
accounting violations for each preserved campaign; its three JSON outputs are
in `.test-reports/reliability-20260928/`.

| Campaign | Frozen groups | Finished | Unfinished | Unstarted | Eligible measured uploads | Confirmed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| macOS Medium | 98 | 98 | 0 | 0 | 198 | 198 |
| Windows Medium | 126 | 0 | 126 | 0 | 0 | 0 |
| Linux retained Large | 462 | 0 | 42 | 420 | 0 | 0 |

| Machine | Original asset SHA-256 | Preserved state | Matched published asset |
| --- | --- | --- | --- |
| macOS | `cc6c6503293c8f01b223e1fac9a5da56888352d39c5e777cf90d23acec8aa8c6` | 5,247 files, 2,534,742,857 bytes | `1.3.0-rc.5` macOS DMG |
| Windows GUI | `2ec0a4bcb7d94af340e61a1837bfc9380b51b2dd60bbd1f48eb023dfa24c0379` | 815 files, 7,636,096,174 bytes | `1.3.0-rc.5` Windows GUI executable |
| Linux | `b1a68a039ce78a6bc9718adbae99409865326ea8a8b3fc29e47aaa090ef0f4d8` | 240 files, 458,284,784 bytes | `1.3.0-rc.5` Linux archive |

Read-only machine inventory: macOS 27.0 arm64, M4 Pro; Windows 11 Pro build
26200 x64, Ryzen 9 7950X and RTX 5090; Linux 6.8.0-142 x86-64, Xeon
E5-2699 v4 and GTX 1070. Hardware presence does not certify a supported
encoder path in a new package.

The release notes explicitly say rc.5 rebuilt macOS from `b0607f0`, carried
Windows binaries from `5d379c7`, and carried a Linux rc.2-era binary. Matching
the rc.5 release asset is therefore not evidence of shared source parity.
The original campaign manifests bind protocol and pinned FFmpeg/FFprobe SHA-256
values, but these older manifests do not record `clientVersion`. The macOS
submission envelopes independently identify `client/0.3.3`; the Windows and
Linux incomplete runs have no envelopes from which to prove their client
version. Package hashes, local download times and release notes support the
package association but do not replace missing launch provenance.
The original macOS DMG mounted read-only and verified its image checksum. Its
app declares version `1.3.0-rc.5` and macOS minimum `27.0`; the embedded CLI is
Mach-O arm64 with SHA-256
`82c4075927ca62bc18ac8be6cc284ba8454a7b7701f1bf7aa405d4f0a980cde4`.
The app has an ad-hoc code signature and no team ID. It was ejected after
inspection.
The original Windows GUI asset has a PE x86-64 header. The Linux archive's
embedded ELF x86-64 executable has SHA-256
`6793d0892f95dd5334d0faae9d252376a1484cd32d8de33515c72d58116d2e8b`,
matching the already extracted native launcher directory.
Windows `Get-AuthenticodeSignature` reports `NotSigned` for the original GUI
asset; no signature assurance is inferred from its release checksum.

| Original campaign runtime | FFmpeg SHA-256 | FFprobe SHA-256 |
| --- | --- | --- |
| macOS Medium | `ef1da73e929cb11aae5f4770ba0fcab617641d9feb03c5d00bb7c0702ebdf5d2` | `12da1d9d189806ba249f3c44b703f20b804e309a6150b3bef1e0ab4b569e9b66` |
| Windows Medium | `b74bd2209fe38026ae9f73ad676e626599bdc1efd950fe32d40b23184fb1a060` | `70be4ea32723b313df89603ba7cfbd818862e8785c20eb9008c27ef161ae84c0` |
| Linux retained Large | `d223345af606df9ab0c99e4222375376e218976c8e1e4ccaf8292d35d504f782` | `fb1364aa21beb8f514fb1b8cc5a9c5d557f9347c9433541c45bd5f3146ccb719` |

## macOS Medium: `campaign-7e6d70761d73929e`

The frozen manifest names 98 recipe by clip groups with protocol 7.1: one
warmup, two required measured repetitions, and at most two optional adaptive
repetitions per group. Its 296 durable attempts are 98 warmups plus 198 measured
records. Ninety-seven groups have exactly two measured records; one used four.
All 296 recorded attempts have valid client validity. The 198 immutable
submission envelopes each have an accepted marker and a unique server run ID.
The recorded attempts span 05:04:13–05:51:08 UTC; accepted markers span
05:51:12–06:02:16 UTC. These are observed intervals, not a promised duration.

A read-only production database query found exactly those 198 run IDs, with
198/198 artifact hashes matching the local accepted markers. Server disposition:
98 `ACCEPTED` runs with `RETAINED` artifacts and `COMPLETE` analyses; 100
`SUSPECT` runs with `VERIFIED` artifacts and `SUSPECT` analyses. All 100 suspect
runs have the server reason `Metric disagreement diagnostics flagged the run
for review`. Grouping by immutable repetition group gives 47 groups with two
accepted runs, one group with four accepted runs, and 50 groups with two
suspect runs. There is no missing required repetition or pending upload in
this campaign. The UI's
reported 198 is the number of measured uploads, not the number of encodes or
the number of scientifically accepted runs. The reported initial display of
"over 600" has no retained screenshot or log here; this manifest's protocol
range is 294–490 encodes, so the exact origin of that displayed figure remains
unresolved. The terminal implementation also mislabeled an in-memory count as
"submitted" and requires repair independently of this particular campaign's
successful delivery.

## Windows Medium: `campaign-c820031ccf718637`

The original GUI state has a 126-group frozen plan. It durably recorded 126
valid warmups and 40 valid first measured repetitions. No group has its second
required measured repetition, and there are no submission envelopes or
accepted markers. `budget-exhausted-1790573546663034900.json` records a
60-minute measurement checkpoint at 2026-09-28 05:32:26 UTC with attempt 167
in flight. Attempt 167 left output bytes but no durable attempt record; those
bytes are preserved as interrupted evidence, not counted as a valid measured
repetition. The backend has zero runs for this campaign. The first proven
reason for zero submissions at that checkpoint is incomplete measurement
groups; the code publishes only finalizable groups. Why automatic continuation
did not subsequently finish the campaign is unresolved without a retained GUI
event log or operator action record. The original executable and all 166
attempts remain available for resume. No backend create, authorization or PUT
failure for this campaign can be inferred from zero publication attempts.

## Linux reported Medium stall

The retained Linux journals do not include a Medium campaign. The incomplete
overnight journal is **Large** `campaign-125d142f511fadad`, with 462 planned
groups, 42 valid warmups, no measured repetition and no submission envelope.
Its budget record shows a 60-minute measurement checkpoint at 2026-09-28
08:57:17 UTC, attempt 43 in flight. Attempt 43 likewise has output bytes but
no durable attempt record. The other retained Linux journal is a
completed Small campaign. The backend has zero runs for the Large campaign.

At inventory time the Linux host had no EncodingDB client, FFmpeg or FFprobe
process owned by this run, so the process tree and blocked operation from the
reported separate Medium "preparing runtime" stall cannot be reconstructed.
No Medium journal or matching retained terminal log was found. The unbounded
runtime-probe path in source is a confirmed defect, but it is not proof of the
owner's exact blocked substage. The original archive, runtime state, journals,
in-flight marker and retained bytes are preserved for follow-up.

## Adjacent saved-work reconciliation

The same original Windows state holds two completed Small campaigns
(`campaign-52eef614f3c5bd00` and `campaign-be40e3c9e4abe756`), and Linux
holds completed Small `campaign-7f05346afacc4b2e`. Each has 14 submission
envelopes and 14 durable queue receipts, but **zero journal accepted markers**.
The backend contains 14 `ACCEPTED`/`RETAINED` runs with `COMPLETE` analysis for
each campaign; original artifact
paths still exist on their native machines. Recovery must reconcile the queue
receipts with these envelopes by immutable payload identity. Treating each
envelope as pending and adding the queue receipt count would double-count work
already accepted by the server.
All 42 queue receipt run IDs and artifact hashes were matched independently
against read-only backend rows, with zero mismatches.

## Evidence limits

This document is incident diagnosis only. It does not certify a fixed client,
native Medium reruns, campaign recovery, or a new release. Backend status is
the current authoritative analysis disposition, not an assertion that all
uploaded evidence is accepted. Production was queried read-only; no synthetic
data was sent there.
