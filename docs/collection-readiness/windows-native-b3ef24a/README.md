# Windows candidate evidence retained before GUI acceptance

[CI run 35485094474 / Windows job 106009886316](https://github.com/oliverdougherC/Encoding_Database/actions/runs/35485094474/job/106009886316) builds head `b3ef24abb020bc6af5b5fe6b849ba3eae8314be2` through exact merge `14403ea1c1519acce543dc9d76bacb13a2032159`.

The native build succeeded and the unverified candidate uploaded before GUI acceptance (artifact 10597299065, 1,878,178,657 bytes). The independent pre-GUI resource artifact 10597069416 was downloaded and its original JSON is retained here. At 2026-09-20 03:04:08 UTC it records 17,174,360,064 bytes total RAM, 14,295,879,680 bytes available RAM, and 151,634,374,656 bytes free on D:, where both the workspace and extraction parent reside. These are single pre-GUI readings; they do not establish peak resources or explain the earlier hosted-runner communication loss.

This evidence establishes that the early artifact-retention change executed successfully. The candidate remains unverified for GUI and seven-clip acceptance until those independent steps complete and their retained receipts/screenshots are reviewed. No hosted binary was downloaded locally for this evidence-only inspection. Physical Windows packages, if built separately from the same head, retain their own build identities and evidence.
