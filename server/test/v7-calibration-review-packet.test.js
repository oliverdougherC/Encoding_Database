import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { validateReviewMediaPath } from '../../scripts/calibration-review-media.mjs';

for (const value of ['javascript:alert(1)', ' javaScript:alert(1)', 'java\nscript:alert(1)', 'jav%61script%3Aalert(1)', '%256aavascript%253Aalert(1)', 'data:text/html,hello', '//evil.test/a.mp4', '%2f%2fevil.test/a.mp4', '\\evil.test\\a.mp4', '../outside.mp4', 'media/%2e%2e/outside.mp4', 'https://user:secret@example.test/a.mp4', 'media/source%20clip.mp4']) {
  test(`review media rejects executable or ambiguous path ${JSON.stringify(value)}`, () => assert.throws(() => validateReviewMediaPath(value)));
}
for (const value of ['media/abc.mp4', 'https://example.test/media.mp4', 'http://127.0.0.1:8765/media.mp4']) {
  test(`review media permits safe location ${value}`, () => {
    assert.equal(validateReviewMediaPath(value), value);
  });
}
test('packet generation rejects an executable original link before creating output', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'pl-review-'));
  try {
    const map = path.join(root, 'map.json'); const output = path.join(root, 'packet');
    writeFileSync(map, JSON.stringify({ ['a'.repeat(64)]: { playbackPath: 'media/safe.mp4', originalPath: 'javascript:alert(document.domain)' } }));
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../../scripts/build-calibration-review-packet.mjs', import.meta.url)), '--evidence', fileURLToPath(new URL('../config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json', import.meta.url)), '--media-map', map, '--output', output], { encoding: 'utf8' });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /Media path/); assert.equal(existsSync(output), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('generator rejects duplicate physical identities before reading a database', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'pl-source-scope-'));
  try {
    const file = path.join(root, 'sources.json');
    writeFileSync(file, JSON.stringify(['machine-a', 'machine-a']));
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../../scripts/generate-calibration-evidence.mjs', import.meta.url)), '--benchmark-protocol-id', 'no-database-query', '--quality-model-id', 'test-only', '--calibration-version', 'test-only', '--physical-source-ids', file, '--output', path.join(root, 'draft.json')], { env: { ...process.env, DATABASE_URL: '' }, encoding: 'utf8' });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /Invalid explicit physical source ID list/); assert.equal(existsSync(path.join(root, 'draft.json')), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
