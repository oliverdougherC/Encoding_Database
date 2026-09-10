// Shell boundary unit tests only. Fake CLI output is never certification evidence.
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const source = await readFile(new URL('../../scripts/certify-beta-corpus.sh', import.meta.url), 'utf8');
const loop = source.slice(source.indexOf('PROCESSED_CLIPS=0'), source.indexOf("rg -q 'Queued payload for retry'"));
async function runFixture(ids, rootSpool = false, crf = '24') {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'beta-shell-unit-'));
  try {
    await mkdir(path.join(dir, 'queue', 'protocol-attempts'), { recursive: true });
    await writeFile(path.join(dir, 'clip-ids.txt'), ids.join('\n') + '\n');
    await writeFile(path.join(dir, 'queue', 'protocol-attempts', 'retained-audit.json'), '{}');
    if (rootSpool) await writeFile(path.join(dir, 'queue', 'pending.json'), '{}');
    const client = path.join(dir, 'fake-client');
    await writeFile(client, `#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$RUN_DIR/calls.txt"
if IFS= read -r unexpected; then
  printf '%s\\n' "$unexpected" >> "$RUN_DIR/consumed-stdin.txt"
fi
`, { mode: 0o755 });
    const result = spawnSync('bash', ['-c', `set -euo pipefail\n${loop}`], { env: { ...process.env, RUN_DIR: dir, CLIENT: client, FAULT_PROXY_PORT: '1', SOFTWARE_CRF: crf }, encoding: 'utf8' });
    const calls = await readFile(path.join(dir, 'calls.txt'), 'utf8').catch(() => '');
    const consumed = await readFile(path.join(dir, 'consumed-stdin.txt'), 'utf8').catch(() => '');
    return { ...result, calls: calls.trim().split('\n').filter(Boolean), consumed };
  } finally { await rm(dir, { recursive: true, force: true }); }
}
const ids = Array.from({ length: 7 }, (_, i) => `real-${i}`);
test('all seven invocations submit explicitly, cannot consume clip-list stdin, and ignore retained nested audit JSON', async () => {
  const result = await runFixture(ids);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.calls.length, 7);
  assert.equal(result.consumed, '');
  result.calls.forEach((call, index) => {
    assert.match(call, /(?:^| )--submit(?: |$)/);
    assert.ok(call.includes(`--v7-suite-clip ${ids[index]} `));
  });
});
test('the predeclared native rate point is passed unchanged to every clip', async () => {
  const result = await runFixture(ids, false, '12');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.calls.length, 7);
  assert.ok(result.calls.every(call => call.includes('--crf 12 ')));
});
test('pending root submission JSON still fails certification', async () => {
  const result = await runFixture(ids, true);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Unrecovered client queue/);
});
test('fewer than seven processed IDs fails certification', async () => {
  const result = await runFixture(ids.slice(0, 6));
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Expected seven processed canonical clips/);
});
test('empty clip IDs fail before invoking client', async () => {
  const result = await runFixture([ids[0], '', ...ids.slice(1)]);
  assert.notEqual(result.status, 0);
  assert.equal(result.calls.length, 1);
  assert.match(result.stderr, /Empty canonical clip ID/);
});
