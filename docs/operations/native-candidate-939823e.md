# Isolated candidate preparation at 939823e

The P910 candidate was updated successfully on September 20, 2026 UTC. This is
preparation evidence, not native benchmark acceptance or a production release.
The executable has not yet been launched for acceptance, and no benchmark uploads
or authoritative analysis were performed in this phase.

## Source and deployed identity

Reviewed source: `939823ead2c052572f9deb5c9f91c85435d5661d`.
The transferred Git bundle SHA256 was
`bce601d1c401d4abc410d5e86871c1b473bb6e51222562e3e8f8dfa079386dc4`,
with prerequisite `84d4086e4679566cfa6a7d10678be74a0a8993ab`.
Both bundle integrity and fetched commit were verified before checkout.

| Artifact | Verified immutable identity |
| --- | --- |
| Server image `encodingdb-candidate-server:939823e` | `sha256:f3acd4ee49ff07ab14645a85bdbe55f94de5cbd2c3a91176612128c8874663ee` |
| Frontend image `encodingdb-candidate-frontend:939823e` | `sha256:92affa067a7a4a101458cb9c787fa9a9c8fe774dd5f9677c746e77029ff377b1` |
| Linux executable, 198,985,184 bytes | `46a6dcad789f824909911455b19979a33e4053dae1440f09524da5142ca18dc3` |
| Frozen external suite pack, 1,506,890,018 bytes | `d20407f8d78f152f06c3b7271881d8b3f07d2b76cf3a2642b241162d666ac150` |

The existing candidate checkout and Compose project remain
`/mnt/NVME/docker/encodingdb-operations/20260914-candidate-730de3c` and
`encodingdb-candidate-730de3c`. Exact DB/artifact volume guards passed before the
build and again immediately before rollout. The private previous Compose file is
retained on P910; it was not copied into this repository.

The server and frontend builds exited zero in 215.75 and 45.02 seconds. Server
image gates verified the frozen model hash, all canonical source hashes, actual
VMAF execution and an XPSNR invocation through the compiled normalization helper.
Build timing and reported maximum RSS describe their command processes; they are
not measurements of production analyzer throughput or Docker daemon memory.

## Backup, migrations and preserved state

A paired candidate backup and isolated restore passed before checkout in 32.68
seconds. The inventory contained zero artifacts, derived members or public corpus
groups, matching the empty candidate database. This does not substitute for a
post-contribution restore with retained media.

The first backup invocation failed because the inherited PostgreSQL Docker wrapper
bind did not include the new evidence directory. The supervisor failed closed and
restarted the exact candidate writer after 22 seconds. The corrected invocation
set `V7_BACKUP_DOCKER_WORK_ROOT` to the existing candidate root, without changing
the private configuration file. Both attempt logs are retained.

Rollout preserved the existing named volumes and isolated network. All eight
candidate/production containers were healthy afterward. Every production container
ID, start time, image, mount and network matched the pre-update baseline.

All **29** expected migration names and SHA256 checksums matched completed database
rows, with no unexpected, unfinished or rolled-back migration. Prisma additionally
reported the schema up to date. Run, artifact and quality-analysis counts remained
zero. Candidate analysis concurrency is explicitly **0** until the parent grants
the subsequent analysis phase.

## Linux package preparation

`ENCODINGDB_BUILD_ONLY=1 bash scripts/build_linux_client.sh` exited zero in 287.01
seconds using the existing Python and reviewed Linux FFmpeg runtime. No runtime
registration override was set. The package is an ELF x86-64 executable.

A CArchive inspection verified the actual embedded FFmpeg and FFprobe bytes against
the reviewed source lock. It also verified that the embedded lock equals the
staged bytes and the source lock's Linux platform entry. The distribution
intentionally filters other platforms from its embedded lock. The existing
holdout runtime/source/reference/artifact paths were preserved.

This BUILD_ONLY artifact has no claim of completed release-sidecar smoke, code
signing, GUI execution, seven-clip collection, TLS publication or recovery replay.
Those remain separate acceptance work using these exact bytes.

## Allocation handoff and next phase

At `2026-09-20T01:29:17Z`, all owned build, rollout and archive-audit sessions had
exited, no owned backup containers remained, and the shared measurement lock was
successfully acquired and released. An unrelated FFmpeg process was observed and
left untouched. The host was handed to the independent capacity lane for its
isolated 100,000-row/25-reader repeat on the final server image. No native timing,
uploads or quality analysis may overlap that allocation.

After the capacity handback and integrated-test confirmation, follow
[the native acceptance runbook](native-candidate-next-run.md): trusted TLS checks,
embedded-runtime executable smoke, predeclared seven-clip software/NVENC campaigns,
then a separate upload/fault/replay/drain phase with immutable ledger and exact
database/object reconciliation. Production deployment is outside this preparation.

All receipts and complete build/backup/rollout logs are in
[`evidence/native-candidate-20260919`](evidence/native-candidate-20260919).
