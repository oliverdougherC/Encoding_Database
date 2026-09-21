# Review-packet provenance (two receipts, one truth)

## Original receipt (kept, historically accurate)
`playable-packet-manifest.json` + `playable-packet-verification.json` + `packet-file-hashcheck.json`
(commit `4c02d36`) proved: bytes on disk == candidate DB hashes, loopback HTTP
Range/206 transport, live UI/API provisional rendering. **They did not prove
browser playability**: the five canonical references are FFV1/yuv420p,
undecodable in any browser, and the manifest mislabeled the suite-lock
fingerprint `41ae332c…` as the release suiteFingerprint. That claim was wrong;
this file is the correction of record.

## Repaired evidence (`repaired/`, by the bounded review-packet worker)
- `manifest.json` / `index.html`: corrected labels (release suiteFingerprint
  `d40bff56…`, suite-lock fingerprint `41ae332c…`, pack SHA-256 `d20407f8…`)
  and distinct preview vs original-FFV1 bindings.
- Lossless browser previews: libx264 `-qp 0`, per-frame MD5 identical to the
  FFV1 masters — 1152/1152 frames (`repaired/tools/evidence/*-{original,preview}.hash`,
  `verify_previews.sh`); masters byte-unchanged (`post-repair-original-hashes.txt`).
- Real-browser proof: headless Chrome over CDP, 7/7 targets PASS with decoded
  frame counts, seek delta 0.000 s, zero dropped frames (`repaired/tools/evidence/browser-proof.json`).
- Decisions worksheet: C1–C6 COMPLETE controls + C7 SUSPECT (limited diagnostic;
  accept/reject UI-locked), blank verdicts + rationale, export to JSON
  (`ui_check.mjs` ALL_PASS). **Not** an all-80-SUSPECT review; no PL validation.
- Original FFV1 masters keep download links in every case; large media is NOT
  archived in this repo (packet lives at `/Users/ofhd/encodingdb-review-packet-20260920`).

Review URL (single): `http://127.0.0.1:8777/index.html`.
