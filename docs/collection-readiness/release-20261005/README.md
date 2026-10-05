# Published collection release — October 5, 2026

**rc.10 clients and the refreshed website are live. PL is provisional; scheduled backup and failure-alert integration remain incomplete.**

[Release](https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.3.0-rc.10) · [Live downloads](https://encodingdb.platinumlabs.dev/run) · [Current handoff](../../FINAL_RELEASE_HANDOFF.md)

## Source and download identity

Clients and server use `daa3e8e99e17e4cf99fb9440a90f96cbc25bdb2f`; website source is `6ca1b4285d85a3d70b24f91023548b0e9b85de40`. The project tag is `1.3.0-rc.10`, with preserved `client/0.3.9` measurement/journal identity and protocol `7.1`.

[Publication evidence](publication.json) records the four exact artifact sizes and SHA256s, anonymous HTTPS redownload verification, and public manifest/checksum identities. The GitHub release has 30 assets and remains marked prerelease. The four native packages share one clean source revision; the later website commit only selects their published links/hashes and preserves client/build inputs.

## New native and production proof

[Native acceptance](native-acceptance.json) records **16 F8 cases / 32 publication-retry invocations / zero new encodes**. Four cases per executable role exercise first/later missing or hash-mismatched retained artifacts using genuine copied journals and controlled retention fixtures. Per-case raw-proof digests are retained. These cases belong to the new release hashes; the [older rc.9 packet](../overnight-20261004/README.md) retains its separate source/package identities and scope.

[Production acceptance](production-acceptance.json) records **six genuine new production contribution identities**: two from each original Linux, macOS and Windows host. All six reached ACCEPTED/RETAINED/COMPLETE, with default TLS trust, original source IDs and immutable runCreate/payload/artifact bindings. No encode was repeated and original queues were unchanged. Two artifact PUTs were observed; the server reused other already-retained bytes through normal content-addressed deduplication.

Windows GUI then retried the same Windows contributions through its real Retry control. The same production bindings were returned, with **zero additional rows, PUTs or attempt records**, zero pending entries and a clean exit. A separate public TLS read verified all six immutable identities. Public/private host and installation identifiers are intentionally absent from this packet.

The server was updated first while the old frontend/downloads remained, then rc.10 was published and independently downloaded, then the new frontend was deployed. The recorded 507 original bindings were preserved; final cutover counts were 513 runs, artifacts and analyses. The live download page showed rc.10 and four real links. Reviewed 1280-pixel desktop and 390-pixel mobile views had no horizontal overflow; mobile navigation reached six hardware groups and Browse displayed the three newly accepted groups. The [public production smoke workflow](https://github.com/oliverdougherC/Encoding_Database/actions/runs/37361212102) also passed.

## CI and operational boundaries

[CI snapshot](ci.json): all 13 checks passed for the released client/server revision. Website frontend, stack-smoke and preflight passed; the website revision's Windows native build was still in progress at the stated snapshot. Existing published binaries remain bound to the fully checked client source, not that later redundant build.

[Operations evidence](operations.json): the actual approximately 1.98 GB artifact backup plus database restored successfully, with 507 artifacts and 18 tables / 1,904 rows matched. Writer quiescence was 59 seconds. The private off-host copy passed hash verification. No scheduled backup/restore or health-failure delivery integration was installed; the selected monitoring service's configuration reference remains pending.

[PL evidence](../pl-20261004/README.md): 220 qualified fitting and 32 qualified holdout observations are preserved. Objective coverage, independently fitted holdouts, genuine choices and freeze gates remain open. No recommendation-ready score was activated.

## Evidence custody

[Private proof hashes](private-proof-hashes.json) bind the original native, production, cutover, backup, redownload and live-UI records. Logical proof names replace private file paths. Raw installation/source identifiers, host paths, session details and credentials remain with the task owner. Hashes identify retained evidence; they are not independent certification.

Historical packets were not rewritten. The [prior handoff at the release source](https://github.com/oliverdougherC/Encoding_Database/blob/daa3e8e99e17e4cf99fb9440a90f96cbc25bdb2f/docs/FINAL_RELEASE_HANDOFF.md) remains an immutable historical reference.
