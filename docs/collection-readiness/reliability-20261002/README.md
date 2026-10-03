# PR #23 correction evidence — October 2, 2026

Source corrections for PLA-578–580 and dependency remediation for PLA-582.
Base: `ff9034acb0c3a357e65e06c260d3ec0377a1bdd6`. Keep draft and unmerged.
This is source verification, **not final-package online certification**.

## Corrected behavior

- Corrupt accepted markers no longer hide intact measured artifacts. Recovery
  preserves original identities, reconstructs missing envelopes without encoding,
  and requires verified acknowledgment before retirement. Unresolved journal
  corruption remains visible as non-success after healthy siblings upload.
- Historical 404/410 and transient metadata failures have separate dispositions.
  Neither prevents independent saved envelopes or queued work from progressing.
  Accepted siblings with retired bytes do not become missing-artifact failures.
- Retry receipt maintenance and queue cleanup take host publication exclusion
  before filesystem mutation. Refused retry preserves evidence; after collector
  release, receipt recovery and replay finish idempotently.

## Verification

Local agents implemented and tested the changes; Codex reviewed the production
and test diffs, requested one substantive revision, and independently reran the
16 new recovery/real-process exclusion tests (16 passed).

| Check | Result |
| --- | --- |
| Full final client suite, Python 3.11.15/macOS arm64 | 748 passed; exit 0 |
| New recovery/exclusion tests | 16 passed; exit 0 |
| Revision regressions against pre-revision code | 6 failed, 10 passed; exit 1 |
| Original new tests against PR base | 8 failed, 2 passed (agent evidence) |
| Existing recovery, durability, acknowledgment, progress and timing regressions | 116 passed; exit 0 |
| Changed Python module compilation and whitespace checks | Passed |
| Frontend tests after dependency updates | 78 passed |
| Frontend lint/typecheck and production build | Passed |
| Server tests/build | 237 passed, 6 existing skips |
| Independent frontend and server npm audits | Both zero vulnerabilities |

Client commands use `python -m pytest tests -q` from `client/`; focused tests
are `test_publication_recovery_integrity.py` and
`test_publication_exclusion_ordering.py`. The latter exercise real process
locking for both acquisition orders, same/different queues, and an imported
Windows GUI Retry consumer. They are not physical Windows GUI execution.
Attached logs contain complete final summaries and exit codes. The client
suite's local HTTP fault fixture prints a request-handler exception while its
assertions and the full suite pass; no passing result is inferred from that text.
An earlier incomplete background run is excluded from the evidence.

## Dependency choices

Next 16.3.4 → 16.3.8, Vitest 3.2.7 → 4.1.11, transitive brace-expansion
1.1.21/5.0.12, and Morgan 1.12.0 → 1.12.1. No audit waivers or gate changes.
Raw before/after audit JSON identifies advisories and dependency paths.
Vitest's patched major also updates Vite to 8; local tests passed unmodified.
The lockfile installs with npm 10.9.8 using `npm ci`; regeneration used npm 11
to avoid an npm 10 peer-resolution failure. Vite requires Node ≥20.19 or
≥22.12; final CI must confirm the supported toolchain.

## Open acceptance gate: PLA-581

Final-source CI, four exact package hashes and physical full ONLINE Medium
contribution/recovery remain separate. Previous local-only campaigns do not
prove server receipt or analysis reconciliation. The final packages still need
Windows GUI/console, macOS app/Terminal and Linux launcher execution, frozen
Windows metadata IPC, native Stop/Close fault cases and stable-ID recovery
against a compatible isolated backend. Preserve original queues, existing
backend keyframe fix, TLS, quotas and scientific validation. No merge, public
release, production rollout or certification is claimed here.
