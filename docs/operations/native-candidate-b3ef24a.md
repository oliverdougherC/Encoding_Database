# Isolated candidate preparation at b3ef24a

The existing P910 candidate was prepared from reviewed source
`b3ef24abb020bc6af5b5fe6b849ba3eae8314be2` on September 20, 2026 UTC.
This phase built and verified the images/package; it ran no new native campaign,
benchmark smoke, upload, or quality analysis. Earlier `939823e` evidence keeps its
original source and package identity.

The transferred bundle matched SHA256
`221b4c05b1d17d59ca7477ab76d604066574f6c98538646f52d542bcf31f8bb5`
and prerequisite `939823ead2c052572f9deb5c9f91c85435d5661d`.
Before building, the existing Linux binary was copied into
`operation-evidence/native-b3ef24a/previous-native/encodingdb-client-linux-939823e`
and its SHA256 rechecked as
`46a6dcad789f824909911455b19979a33e4053dae1440f09524da5142ca18dc3`.
The ordinary and excluded instrumented `939823e` queues, artifacts and receipts
remain in their existing case directories.

## Verified preparation

- Exact existing DB/artifact volume guards passed before build and rollout.
- Paired candidate backup and isolated restore passed before checkout, using the
  currently deployed `939823e` image for database inventory. Its empty retained
  corpus remains an explicit limitation of this restore proof.
- Server/frontend builds and the Linux BUILD_ONLY build exited zero. The server
  build exercised its model/source hashes, VMAF and compiled XPSNR input checks.
- Candidate rollout became healthy with worker concurrency explicitly **0**.
- All **29** migration names/checksums matched completed database rows, with no
  additional or unfinished migrations. Counts remained zero runs/artifacts/analyses.
- Actual API and frontend passed trusted TLS checks using the combined public-root
  and candidate certificate bundle, with certificate verification enabled.
- Production container IDs, start times, images, mounts and networks matched the
  pre-update baseline; all eight candidate/production containers were healthy.
- CArchive inspection verified both embedded helper byte hashes and the embedded
  Linux-only runtime lock against the reviewed source/staged bytes. The frozen
  suite pack hash remains unchanged.

| Artifact | Immutable identity |
| --- | --- |
| Server `encodingdb-candidate-server:b3ef24a` | `sha256:589c89b95e471fb32782a374c88b91d8ea2526080b7cdb7bc48608f97eba399a` |
| Frontend `encodingdb-candidate-frontend:b3ef24a` | `sha256:6fef7eda217b05e031f6281a8170e0ecc0ed63e92eb5e06736c99783e1c15432` |
| Linux executable, 198,988,248 bytes | `3abd38ee72fa9f5afd9b81934717b3319f7f6143f2675038f6293798c078bf9a` |
| Suite pack | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |
| Source runtime lock | `8cdbd7b3ebf74286ef0b58146d3f7f89d193793439a8c54a4f281214f7ef7ef3` |

The existing checkout remains
`/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c`.
No production service or existing data-volume binding changed.

## Allocation boundary

At `2026-09-20T03:56:31Z`, all owned builds, rollout/audit work and receipt copies
had completed. No owned media or backup container remained; the shared measurement
lock was verified available. An unrelated Jellyfin FFmpeg process remained
untouched. The host was explicitly handed to the capacity lane for the unchanged
100,000-row / 25-reader / 600-second repeat on the new server image.

No native timing, smoke, upload or analysis may start until that lane returns the
allocation. The next ordinary client acceptance must use this new package in new
owned paths with predeclared candidate-specific seeds, the existing physical-host
state and the same fixed recipes. It must be untraced. Previous data remains
historical evidence and must not be relabeled as `b3ef24a` output.

Full preparation receipts and logs:
[`evidence/native-candidate-b3ef24a`](evidence/native-candidate-b3ef24a).
