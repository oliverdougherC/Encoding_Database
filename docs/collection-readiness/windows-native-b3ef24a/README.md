# Windows candidate evidence retained before GUI acceptance

[CI run 35485094474 / Windows job 106009886316](https://github.com/oliverdougherC/Encoding_Database/actions/runs/35485094474/job/106009886316) builds head `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2` through exact merge `14403ea1c1519acce543dc9d76bacb13a2032159`.

The native build succeeded and the unverified candidate uploaded before GUI acceptance (artifact 10597299065, 1,878,178,657 bytes). The independent pre-GUI resource artifact 10597069416 was downloaded and its original JSON is retained here. At 2026-09-20 03:04:08 UTC it records 17,174,360,064 bytes total RAM, 14,295,879,680 bytes available RAM, and 151,634,374,656 bytes free on D:, where both the workspace and extraction parent reside. These are single pre-GUI readings; they do not establish peak resources or explain the earlier hosted-runner communication loss.

This evidence establishes that the early artifact-retention change executed successfully. The final console result is described below; the full GUI gate remains blocked on the native Close harness correction. No hosted binary was downloaded locally for this evidence-only inspection. Physical Windows packages, if built separately from the same head, retain their own build identities and evidence.

## Final hosted acceptance result

The seven-clip console campaign passed its fail-closed verifier at 2026-09-20 03:34:42 UTC: actual packaged execution exited 0, no forced cleanup or owned survivors, seven warmups and fourteen measured attempts covering all seven canonical clips. Embedded helper hashes matched the reviewed lock. Exact hosted console executable SHA256 is `3412235e7d8df9aabeed2cd80b0ab523940eeb9abb5d2626b95db5e6c4f8ef3f`.

The full native acceptance archive (artifact 10597512085, 174,375,799 compressed bytes) was then downloaded separately from the 1.8GB binary candidate. An independent local audit mapped the original Windows artifact paths to the extracted archive without rewriting receipts and verified all fourteen measured console artifacts against their original SHA256 records. It also verified six completed measured artifacts retained across GUI completion, Stop and the blocked Close phase, plus embedded-helper attestations and canonical timing/frame-count metadata. This audit does not repeat the encoder or claim calibration/throughput validity.

The overall CI job is **failed solely at GUI acceptance**: its first three phases exited cleanly, but Close was blocked by the duplicate native Yes button UIA observation described in `gui-blocked/README.md`. The old forced-cleanup result remains blocked and is not upgraded by the proposed harness correction. Console success is limited to virtualized Windows software execution; it is not physical GPU certification. Final source-pin GUI acceptance must be demonstrated separately with the corrected operator harness.
