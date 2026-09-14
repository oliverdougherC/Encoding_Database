# Collection operations acceptance

The collection gate remains open until the empirical checks below are complete.
Unit regressions and synthetic load never count as calibration or production
retention evidence.

## Health contract

`/health/live` stays process-only and `/health/ready` stays a database ping.
`/health/v7-evidence` caches one bounded refresh for 30 seconds per server process,
shares concurrent requests, also caches failures, and rate-limits each caller to
30 requests/minute. Each refresh inspects at most 256 retained/verified objects
(keyset pagination) and 256 staging entries, and samples the latest 1000 timestamped
terminal analyses. Object checks roll through the corpus; `integrityScan` reports
batch/cycle coverage and last complete scan. A prior missing-object finding remains
visible until a full clean cycle replaces it. These are existence checks; complete
SHA256 identity verification remains the backup/recovery check. Staging overflow
is explicitly degraded/incomplete instead of claiming the uninspected directory
is clean. Aggregate database counts are cached but still scale with database size;
the scale receipt must include cold refresh cost.

Upload-to-completion latency is `completedAt - artifact.uploadedAt` for COMPLETE,
SUSPECT, REJECTED and FAILED analyses with completion timestamps. Untimestamped
terminal rows are counted separately. Pending depth/oldest age, active and expired
leases, retry deadlines, configured queue/worker/upload limits, tracked byte quota
and filesystem reserve are exposed. `capturedAt` and cache age must accompany any
monitoring interpretation. Multiple server processes have separate caches; the
validated deployment topology must state its process count.

## Resource envelope

Compose now makes service memory limits/reservations configurable. The server
uses `SERVER_MEMORY_LIMIT=16G` by default because the actual P910 production
container was inspected at 17179869184 bytes after historical 512 MiB/4 GiB OOMs.
This is a reproducible historical deployment setting, **not** a measured seven-clip
capacity claim. Set `SERVER_MEMORY_RESERVATION`, `DB_MEMORY_LIMIT`,
`DB_MEMORY_RESERVATION`, `FRONTEND_MEMORY_LIMIT`, `FRONTEND_MEMORY_RESERVATION`,
`NGINX_MEMORY_LIMIT` and `NGINX_MEMORY_RESERVATION` in the deployment environment
as appropriate. Publish measured worker concurrency, seven-clip peak RSS,
throughput/arrival budget, object quota and queue-drain results before advertising
sustained collection capacity. Capacity cannot be inferred from free host RAM.

Run the sustained browser/metadata probe only on isolated loopback services:

```bash
python3 scripts/v7-capacity-probe.py \
  --api-url http://127.0.0.1:3001 --app-url http://127.0.0.1:3000 \
  --fixture-label 'synthetic 100000 metadata rows; source SHA and seed receipt' \
  --concurrency 25 --duration-seconds 600 --p95-budget-ms 1000 \
  --container isolated-server --output /absolute/path/capacity.json
```

The probe measures reads on both surfaces, records periodic Docker stats/health,
and fails on request errors or its predeclared p95 budget. It does not exercise
encode/upload/queue drain. Production URLs are rejected. Synthetic rows must never
enter the production database.

## Backup and recovery

The existing paired P910 backups are real and preserved. The 2026-09-14 isolated
recovery receipt verifies the `before-hotfix-b0f0bc7d12cb` DB/artifact snapshot:
two exact UPLOADED artifact identities, one shared 2539152-byte object, two runs,
two analyses, zero selected derived members. This is historical recovery evidence,
not a new retained corrected-protocol epoch.

`v7-backup.sh` now streams object hashes, snapshots objects into the output
filesystem, and restarts quiesced writers before archive compression. Before
stopping writers it checks the full source-tree size and free staging capacity.
Defaults: 10 GiB artifact envelope, twice the object-tree size plus 1 GiB free reserve,
300 seconds whole-backup timeout and 60 seconds recovery grace. Override using
`V7_BACKUP_MAX_ARTIFACT_BYTES`, `V7_BACKUP_FREE_RESERVE_BYTES`,
`V7_BACKUP_TIMEOUT_SECONDS`, and `V7_BACKUP_RECOVERY_GRACE_SECONDS` only against a
measured supported budget. The supervisor terminates the owned process group on
timeout; the shell EXIT trap restarts previously running writer services. If that
recovery itself stalls, the command fails and explicitly requires operator
recovery. Host/storage failures cannot guarantee automatic restart.

Use `--compose-file` with the actual production writer service list. A filesystem
source without Compose must already be quiesced by its operator for the duration
of DB dump/object snapshot/inventory. All uploads and analysis writers must be
quiesced, including any separately deployed worker. Never use a live tree as an
implicitly consistent backup. The copy creates transient space proportional to
artifacts; the preflight/deadline intentionally refuses unmeasured larger copies.

Discovery found no EncodingDB schedule in the accessible P910 user's crontab or
system timer inventory. Root scheduler scope and external/off-host backup
configuration have not been established. No new production schedule or alert was
installed. Destination, retention, RPO/RTO, approved alert routing, an executed
scheduled backup and restore of nonempty selected memberships remain explicit
production gates. A one-time historic restore does not satisfy them.

## Both-surface smoke

`production_smoke.sh` requires both `API_BASE_URL` and `APP_URL` before any network
request. Blank frontend configuration fails, and the final success line names
both surfaces. Run against the actual external TLS URLs after deployment. The
P910 serving nginx inspected on 2026-09-14 had a 2 GiB canonical upload limit and
900 second proxy read/send timeouts. This does not establish an upstream proxy's
limits or native-client upload success.

## Executed evidence (2026-09-14)

- `evidence/historical-recovery-20260914.json`: original P910 snapshot recovered
  without production mutation; exact DB/object identities verified.
- `evidence/public-smoke-20260914.log`: actual public API **and** frontend passed
  at `https://encodingdb.platinumlabs.dev`; server remained the existing
  `b0f0bc7d12cb127c86a7c76979eb361398e293dd` deployment.
- `evidence/backup-20260914.log`, `backup-restore-drill-20260914.log` and
  `isolated-backup-inventory-20260914.json`: a new isolated paired backup restored
  two retained artifacts and one exact selected member. The additional retention
  state/context/member were **synthetic recovery fixtures** in the separate
  `encodingdb_operations_backup` database, not evidence of production acceptance.
  The backup completed in 0.434 seconds for the 2.54 MB object tree. These numbers
  cannot extrapolate to full-corpus downtime.
- `evidence/backup-timeout-20260914.log`: a one-second supervisor timeout killed
  the owned test command group and ran its recovery trap, exiting 124. This tests
  cancellation mechanics; a production Docker restart failure remains an
  operator recovery condition.

The new isolated backup was invoked directly, not by a production schedule.
Production scheduler/off-host destination/retention and real authorized alert
routing remain unverified and have not been silently counted as passed.

The isolated scheduled acceptance subsequently **passed** via a real macOS
launchd interval job: it ran the current wrapper automatically, backed up the
isolated two-retained-artifact/one-member fixture, restored it into a fresh
PostgreSQL container and verified exact identities. The job was unloaded after
success. See `evidence/scheduled-backup-20260914.json` and its log. The first
scheduled attempt exposed Bash 3 empty-array handling and a false zero status;
both were fixed with a failure-receipt regression, and the failed log is retained.
This proves scheduled local orchestration, not production installation.

`deploy/systemd/encodingdb-backup.service` and `.timer` provide the Linux schedule:
02:00 UTC daily with up to five minutes jitter, persistent missed-run handling,
private `/etc/encodingdb/backup.env`, a dedicated operator user and the installed
checkout at `/opt/encodingdb`. Configure those paths/user for the actual host.
The private environment needs a host-reachable DB URL, artifact volume or
quiesced directory, `V7_BACKUP_COMPOSE_FILE`, `QUIESCE_SERVICES` for all writers,
and durable `V7_BACKUP_DESTINATION`. Seven completed bundles are retained by
default. Every scheduled run verifies an isolated restore unless explicitly
configured otherwise. `last-backup.json` is written atomically for monitoring,
including failure. No notification destination or credentials are embedded.
The draft daily RPO is at most 24 hours plus five minutes **after successful
installation and monitoring**; it is not an established production recovery SLA.

Database shared memory is now configurable with `DB_SHARED_MEMORY_SIZE` (default
256 MiB). The 64 MiB Docker default was exhausted by the earlier parallel corpus
query load; the read-model lane also disabled query-worker fan-out. The larger
Compose setting still requires integrated deployed-topology measurement.

Additional measured health evidence:

- `health-scale-20260914.json`: real PostgreSQL with 100060 synthetic artifact
  metadata rows; cold refresh 42.4 ms, 25 simultaneous monitor calls shared a
  25.0 ms refresh, and 1000 cached calls took 0.667 ms. Node RSS was 76.3 MB.
  Only 256 objects were checked; absent synthetic bytes correctly degraded health.
- `health-real-db-faults-20260914.json`: an isolated PostgreSQL copy with one failed
  worker and one expired lease exposed `failed_analyses`, `expired_analysis_leases`,
  the retry deadline and queue age. Production rows were not changed.
- `health-disk-full-20260914.json` and `.log`: a real isolated 1 MiB Docker tmpfs
  filled until ENOSPC exposed zero available bytes and
  `storage_reserve_exhausted`. Metadata was stubbed for this filesystem fault.

The candidate collector was also executed read-only against the actual P910
Prisma database and object mount, streamed over `docker exec` stdin so no server
files/configuration/data were changed. The old public health endpoint reported
zero latency samples for its four SUSPECT analyses. The candidate reported all
four with true upload-to-completion p50 **34.067 seconds** and p95 **4423.326
seconds**, and checked all four objects. See
`production-health-before-20260914.json` and
`production-health-candidate-readonly-20260914.json`. This validates the query
against production data; it does not claim the new monitoring endpoint is deployed.
The inspected production container had one Node process, a 16 GiB memory limit,
zero restarts and no current OOMKilled flag.


The sustained isolated database sample exceeded the old 512 MiB database limit
(621.5 MiB observed by 313 seconds), so the configurable database default is now
1 GiB. This covers the observed metadata-serving footprint with headroom; the
final receipt records the measured peak. The probe's shared PostgreSQL instance
also hosted isolated acceptance fixtures, so this is a deployment budget decision
from observed pressure, not a per-query allocation estimate.

## Sustained metadata serving result

The [601-second receipt](evidence/sustained-http-durable-20260914.json) and
[compact summary](evidence/sustained-http-summary-20260914.json) record 25
simulated browsers and **124737 requests with zero errors** against the actual
corpus router and production-built frontend. The fixture had over 100000
synthetic metadata rows, with a separate one-chain/second synthetic arrival
stream during most of the run. All four routes passed the predeclared 1000 ms
p95 budget:

| Surface | Requests | p95 |
| --- | ---: | ---: |
| Corpus first page | 31188 | 32.28 ms |
| Frontend corpus proxy | 31182 | 38.00 ms |
| Frontend homepage | 31181 | 18.49 ms |
| Seven-clip catalog | 31186 | 1.40 ms |

Sampled peak RSS was 229752832 bytes for the API and 322191360 bytes for the
frontend. Sampled database Docker memory peaked at 651689984 bytes (621.5 MiB).
These are sampled observations, not OS lifetime high-water marks. The tested
server/read-model source was `5bae5016da74f485e3018df23778238dbe49ecc5`, migration
`20260914012000_corpus_groups`; frontend code was `ddbca7c`. Later final integrated
source still requires its integrated checks.

The standalone corpus-router staging process did not install the evidence health
route, returning 404; `healthAllOk` is explicitly false. This passing result is
for metadata/API/frontend serving, not production monitoring, 25 simultaneous
uploads/encodes, full worker queue drain, or the final TLS/proxy/cgroup topology.
The earlier uncached load is retained as an explicitly aborted attempt rather
than being presented as a complete sustained run.

Three further real scheduled backups and isolated restores ran during this read
load, all passing, with exact two-artifact/one-selected-member restoration and
retention keeping two completed bundles while preserving an unrelated directory.
The job was unloaded afterward. See the
[scheduled retention receipt](evidence/scheduled-retention-final-20260914.json)
and [log](evidence/scheduled-retention-final-20260914.log). Production scheduling
and alert routing remain uninstalled/unverified.
