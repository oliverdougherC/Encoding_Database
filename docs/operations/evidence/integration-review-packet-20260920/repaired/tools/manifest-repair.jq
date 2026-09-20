.generatedAt = $gen
| .repair = "2026-09-20: lossless browser-preview + provenance-labeling repair (local OMP Qwen3.8-Flash-Next worker)"
| del(.suiteFingerprint)
| .provenance = {
    suiteFingerprint: {value: "d40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e", source: "release suite-pack.json / client release-manifest field suiteFingerprint (canonical release suite inventory)"},
    suiteLockFingerprint: {value: "41ae332c8e4ac7ae49c2a44917729c65d7a062710e4b44961b8125ffe7fb2660", source: "fingerprint field of bundled suite-lock.json (client/server suite lock), e.g. clients/macos/suite_resources/test_suite_v1/suite-lock.json"},
    packArchiveSha256: {value: .suitePackSha256, source: "sha256 of encodingdb-test-suite-v1.tar.gz, release-pinned; unchanged by this repair"},
    correctionNote: "Pre-repair manifest mislabeled the suite-LOCK value as suiteFingerprint. No identity was changed; only labeling corrected. API snapshot identifies the suite by name only (versions.sourceSuiteVersion=encodingdb-test-suite-v1); environment.fingerprint and ffmpegBuildFingerprint in api/corpus-full.json are separate host-level identities, not suite identities."
  }
| .suiteReference = "encodingdb-test-suite-v1 (versions.sourceSuiteVersion of api/corpus-full.json; pack sha256 == release-pinned value)"
| .playability = "FIXED 2026-09-20. Previous claim (references are Matroska playable in Chrome) was FALSE: references are FFV1/yuv420p and decode in no browser; HTTP 206 only proved range transport. Players now use LOSSLESS H.264 previews (libx264 -qp 0, High, yuv420p, GOP 24, +faststart MP4); every decoded frame MD5-identical to the original master (1152/1152 frames). Original FFV1 masters unchanged and still downloadable. Real headless-Chrome software-decode playback+seek proof in tools/evidence/browser-proof.json (7/7 PASS)."
| .playbackEvidence = "tools/evidence/browser-proof.json"
| .pixelEquivalenceEvidence = "tools/evidence/<class>-original.hash vs <class>-preview.hash (per-frame MD5, ffmpeg framehash)"
| .originalIntegrity = {recheckedAt: $gen, evidence: "tools/evidence/post-repair-original-hashes.txt", result: "12/12 reference+encode files recomputed sha256-identical to manifest"}
| .reviewWorksheet = {page: "index.html cases C1-C7 (radio decision + rationale, autosave localStorage key packet-judgments-20260920, Export judgments JSON -> oliver-judgments-b3ef24a-*.json)", caseCount: 7, requiredVerdicts: "C1-C6 one perceptual verdict each; C7 disagreement classification only (accept/reject locked out)", plValidation: "none - packet validates no PL result", policyNote: "no Balanced/Quality tier policy decisions; calibration (canonical-matrix-b3ef24a, phase=timing) still in progress"}
| .items |= map(
    ((.reference.path | split("/") | last | split(".") | first)) as $n
    | { "animation-1080p24-final":      {sha:"9e030c9b6c3b04acbcfe1b1eef2b56d14ce3ab473251e9f5e27d88ad2d7ffbc9", bytes:190968822, frames:192},
        "athletic-action-1080p24-final": {sha:"2a203a411070d011dd7e5d0be97f160aacc28d983b52292e15e4a7a247a1c922", bytes:148429129, frames:240},
        "film-grain-1080p24-final":      {sha:"e8d8a852a376a2b235b80d526d9198022d012a2e47c2499ca22688b32f655121", bytes:352145853, frames:240},
        "natural-detail-1080p24-final":  {sha:"263b9cfb89e6fd251b67861248b84cc954d1b5fc41ecb5c4a5eee58152b7a143", bytes:274568590, frames:240},
        "screen-text-1080p24-final":     {sha:"0abe0651e094bd02dfca3e293301ffbcb3e703c0246af219f89a0c59f5738f58", bytes:2180409, frames:240}}[$n] as $p
    | .reference.codec = "ffv1 yuv420p (verified via ffprobe; NOT browser-decodable)"
    | .referencePreview = {
        path: ("media/previews/" + $n + "-lossless-h264-preview.mp4"),
        sha256: $p.sha, bytes: $p.bytes,
        codec: "h264 libx264 -qp 0 LOSSLESS, High, yuv420p, GOP 24, +faststart",
        equivalence: ($p.frames|tostring) + "/" + ($p.frames|tostring) + " decoded-frame MD5s identical to reference master",
        note: "distinctly labeled preview; original remains downloadable and byte-unchanged"
      }
    | if .class == "environment-suspect" then
        .class = "metric-disagreement-suspect"
        | .classNote = "run SUSPECT: Metric disagreement diagnostics flagged the run for review; informational only, ineligible for quality/timing approval"
      else . end
  )
