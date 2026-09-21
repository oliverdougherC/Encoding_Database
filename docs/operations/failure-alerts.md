# Failure alerts (Discord webhook, read-only health poll)

## Accepted initial-launch policy (2026-09-20, owner decision)

- Discord failure alerts are authorized for the owner-supplied webhook. The
  destination is a secret-file reference only; the credential lives outside
  the repository at a mode-0600 path and is read into process memory only.
- **No new backups for the initial launch**, explicitly accepted while data
  needs are measured. Existing backups and recovery evidence are preserved.
  Consequently `backup*` health reasons are filtered by default
  (`V7_ALERT_BACKUP_MONITORING=0`) and a missing backup **cannot fire an
  alert**. When a real schedule exists, flipping that one variable re-enables
  the filter; no code change is involved. This does not revoke any earlier
  recovery evidence and no off-host destination is a launch blocker.
- Nothing is enabled by this change alone: `V7_ALERT_ENABLED` defaults to `0`,
  the systemd units are not installed, and no production schedule or service
  was created. Enabling happens only with the approved rollout.

## Mechanism

`server/scripts/v7-failure-alert.mjs poll` runs once per scheduled tick
(systemd timer or cron):

1. `GET` the existing read-only `/health/v7-evidence` contract (bounded
   timeout, no auth needed, no mutation). HTTP/transport faults become
   `health_http_<status>` / `health_unreachable`; a 503 without a snapshot
   body becomes `evidence_health_unavailable`.
2. `evaluateFailureAlertRules` (in `server/src/v7/failureAlerts.ts`) maps
   degraded reasons to an alert, applying the backup-filter policy.
3. One message is delivered per failure episode via
   `sendDiscordWebhookAlert`, with persistent state in a 0600 file
   (episode identity, last send time, delivery-failure backoff) so separate
   processes share duplicate suppression (`suppressed_unchanged`), a
   cross-key send floor (`held_rate_limit`), and failed-delivery backoff
   (`held_backoff`). Recovery clears the episode silently; a later failure
   alerts again.

Guarantees: every request has a bounded timeout; Discord `429` honors
`retry_after` up to a cap with a bounded attempt count; `allowed_mentions`
is `{parse: []}` so nothing can ping; error text is redacted of URLs,
credential-shaped strings, hashes, and absolute paths; the alert contains
only the environment label, machine reason codes, capture time, and numeric
counts (no raw logs, media/storage object names, credentials, or contributor
data). `notified`/exit status is true/zero only on a confirmed 2xx — a failed
delivery is never reported as success.

## Configuration reference (server/env.example)

| Variable | Default | Meaning |
| --- | --- | --- |
| `V7_ALERT_ENABLED` | `0` | Master switch; anything else skips without touching the network |
| `V7_ALERT_ENVIRONMENT` | `production` | Label in the alert title |
| `V7_ALERT_HEALTH_URL` | — | Health endpoint (https, or loopback http for tests) |
| `V7_ALERT_WEBHOOK_FILE` | — | Private mode-0600 webhook file **outside the repo**; rejected if group/world-readable |
| `V7_ALERT_STATE_FILE` | `/var/lib/encodingdb-failure-alerts/state.json` | Persistent suppression/rate-limit state |
| `V7_ALERT_HEALTH_TIMEOUT_MS` / `V7_ALERT_HTTP_TIMEOUT_MS` | `10000` | Bounded timeouts |
| `V7_ALERT_MIN_SEND_INTERVAL_SECONDS` | `300` | Floor between any two send attempts |
| `V7_ALERT_RENOTIFY_SECONDS` | `3600` | Repeat interval for an unchanged failure |
| `V7_ALERT_BACKUP_MONITORING` | `0` | `1` only once a real backup schedule exists |

## Candidate enablement (integration-owned host; requires rollout approval)

```bash
# On the candidate host, as root, with the installed checkout at /opt/encodingdb:
install -m 0644 deploy/systemd/encodingdb-failure-alert.{service,timer} /etc/systemd/system/
# Private env file (never commit; webhook file stays outside the repo at 0600):
install -m 0600 /dev/null /etc/encodingdb/failure-alert.env
# then edit /etc/encodingdb/failure-alert.env to set:
#   PATH=/mnt/NVME/docker/encodingdb-operations/20260913-release-1.2.0/bin:/usr/bin:/bin
#   V7_ALERT_ENABLED=1
#   V7_ALERT_ENVIRONMENT=candidate
#   V7_ALERT_HEALTH_URL=https://<candidate-entry>/health/v7-evidence
#   V7_ALERT_WEBHOOK_FILE=/etc/encodingdb/discord-failure-webhook   (owner-supplied, 0600)
#   V7_ALERT_STATE_FILE=/var/lib/encodingdb-failure-alerts/state.json
systemctl daemon-reload
# One manual tick first (no schedule yet):
systemctl start encodingdb-failure-alert.service
journalctl -u encodingdb-failure-alert.service -n 5 --no-pager
# Enable only after that poll is reviewed:
systemctl enable --now encodingdb-failure-alert.timer
```

## Rollback (complete, zero application impact)

```bash
systemctl disable --now encodingdb-failure-alert.timer
systemctl stop encodingdb-failure-alert.service 2>/dev/null || true
rm /etc/systemd/system/encodingdb-failure-alert.{service,timer}
systemctl daemon-reload
rm -f /etc/encodingdb/failure-alert.env
rm -rf /var/lib/encodingdb-failure-alerts
```

The poller is read-only against a health endpoint; removal changes nothing in
the app, database, volumes, or existing backups. No git revert is needed if
files remain uninstalled.

## Verified locally (mock endpoints only)

`server/test/v7-failure-alerts.test.js` runs against loopback mock health and
webhook servers: 2xx-only success with `allowed_mentions.parse=[]`; 500 with
redacted error and persisted retry-backoff state; `429` wait-then-deliver and
bounded-attempt exhaustion; cross-process unchanged suppression and renotify;
failure-then-retry; recovery-then-re-alert; send-floor hold; backup-reason
suppression under policy; secret-file mode enforcement (`0644` rejected);
redaction; 2000-char bound; CLI end-to-end plus disabled no-op.

## Live connectivity receipt

One approved labelled delivery check
(`v7-failure-alert.mjs test-connectivity`, content
`[EncodingDB TEST] Failure-alert delivery check. No production outage is being reported.`)
was sent to the owner-supplied webhook and confirmed: **HTTP 204, attempt 1,
2026-09-20T22:34:13Z**. That is the only message ever sent; no URL, token or
channel identifier is recorded here, in code, or in the shared handoff.
