import assert from 'node:assert/strict';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const exec = promisify(execFile);
const root = path.resolve(import.meta.dirname, '../..');

test('production smoke rejects omitted frontend before network calls', async () => {
  await assert.rejects(exec('bash', [path.join(root, 'scripts/production_smoke.sh')], { env: { ...process.env, API_BASE_URL: 'http://127.0.0.1:1', APP_URL: '' } }), (error) => error.code === 1 && error.stderr.includes('APP_URL is required'));
});

test('scheduled backup publishes a failing receipt when backup cannot start, including bash3 empty argument arrays', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-schedule-test-'));
  try {
    await assert.rejects(exec('/bin/bash', [path.join(root, 'scripts/v7-scheduled-backup.sh')], { env: { ...process.env, V7_BACKUP_DESTINATION: directory, V7_BACKUP_COMPOSE_FILE: '', DATABASE_URL: '' } }));
    const receipt = JSON.parse(await readFile(path.join(directory, 'last-backup.json'), 'utf8'));
    assert.notEqual(receipt.exitCode, 0);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('backup deadline terminates its own command group and permits the recovery trap', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-deadline-test-'));
  try {
    const script = path.join(directory, 'fixture.sh');
    await writeFile(script, `trap 'touch "${directory}/recovered"; exit 143' TERM\nsleep 30\n`);
    await assert.rejects(exec('python3', [path.join(root, 'scripts/v7-backup-supervisor.py'), script], { env: { ...process.env, V7_BACKUP_TIMEOUT_SECONDS: '1', V7_BACKUP_RECOVERY_GRACE_SECONDS: '3' }, timeout: 6000 }), (error) => error.code === 124);
    assert.equal(await readFile(path.join(directory, 'recovered'), 'utf8'), '');
  } finally { await rm(directory, { recursive: true, force: true }); }
});
