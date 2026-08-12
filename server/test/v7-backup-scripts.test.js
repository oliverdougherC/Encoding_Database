import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('v7 backup and isolated restore drill bind database and artifact evidence', async () => {
  const backup = await readFile('../scripts/v7-backup.sh', 'utf8');
  const restore = await readFile('../scripts/v7-restore-drill.sh', 'utf8');
  assert.match(backup, /pg_dump --format=custom/);
  assert.match(backup, /--artifact-volume/);
  assert.match(backup, /--compose-file/);
  assert.match(backup, /docker volume inspect/);
  assert.match(backup, /cp -a \/from\/\. \/to\//);
  assert.match(backup, /Quiescing writer services for backup consistency/);
  assert.match(backup, /docker compose -f "\$COMPOSE_FILE" stop/);
  assert.match(backup, /docker compose -f "\$COMPOSE_FILE" up -d/);
  assert.match(backup, /"mode": "dry-run"/);
  assert.match(backup, /k != "schema"/);
  assert.match(backup, /artifacts\.tar\.gz database\.dump inventory\.json > SHA256SUMS/);
  assert.doesNotMatch(backup, /SHA256SUMS.*SHA256SUMS/);
  assert.match(restore, /postgres:16-alpine/);
  assert.match(restore, /"mode": "dry-run"/);
  assert.match(restore, /pg_restore --no-owner --no-acl --exit-on-error/);
  assert.doesNotMatch(restore, /benchmarks\?schema=/);
  assert.match(restore, /v7-backup-inventory\.mjs/);
  assert.doesNotMatch(restore, /dropdb|DROP DATABASE/);
});
