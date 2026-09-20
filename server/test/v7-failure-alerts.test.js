import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, writeFile, chmod, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  redactSecretText,
  loadDiscordWebhookSecret,
  sendDiscordWebhookAlert,
  evaluateFailureAlertRules,
  buildFailureAlertMessage,
  createFailureAlertMonitor,
  TEST_CONNECTIVITY_CONTENT,
} from '../dist/v7/failureAlerts.js';

const execFileAsync = promisify(execFile);

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
}

/** Mock Discord webhook: per-request replies from a queue (204 default), capturing every body. */
function startWebhookMock(replies = []) {
  const received = [];
  const server = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (chunk) => { raw += chunk; });
    req.on('end', () => {
      received.push({ raw, headers: req.headers, body: raw ? JSON.parse(raw) : null });
      const reply = replies.length > 0 ? replies.shift() : { status: 204 };
      if (reply.status === 204) { res.writeHead(204); res.end(); return; }
      const payload = JSON.stringify(reply.body ?? {});
      res.writeHead(reply.status, { 'content-type': 'application/json', ...(reply.headers ?? {}) });
      res.end(payload);
    });
  });
  return { received, url: listen(server), server };
}

/** Mock /health/v7-evidence: replies queue (200 ok default). */
function startHealthMock(replies = []) {
  const server = http.createServer((_req, res) => {
    const reply = replies.length > 0 ? replies.shift() : { status: 200, body: { status: 'ok', reasons: [], capturedAt: '2026-09-20T00:00:00.000Z' } };
    const payload = JSON.stringify(reply.body ?? {});
    res.writeHead(reply.status, { 'content-type': 'application/json' });
    res.end(payload);
  });
  return { server, url: listen(server) };
}

function degradedBody(reasons) {
  return {
    status: 'degraded', reasons, capturedAt: '2026-09-20T00:00:00.000Z',
    capacity: { pendingUploads: 3, pendingAnalyses: 2, expiredLeases: 1, retryDue: 4 },
    artifacts: { missingRetainedObjects: 0 }, storage: { availableBytes: 1_073_741_824 }, staging: { staleEntryCount: 0 },
  };
}

async function tempState() {
  return path.join(await mkdtemp(path.join(tmpdir(), 'v7-failure-alert-')), 'state.json');
}

async function writeWebhookFile(url) {
  const dir = await mkdtemp(path.join(tmpdir(), 'v7-alert-secret-'));
  const file = path.join(dir, 'webhook');
  await writeFile(file, `${url}\n`, { mode: 0o600 });
  await chmod(file, 0o600);
  return file;
}

function clocked(startIso) {
  const clock = { t: Date.parse(startIso) };
  return { clock, now: () => new Date(clock.t), advance: (seconds) => { clock.t += seconds * 1_000; } };
}

test('webhook delivery succeeds only on 2xx and disables all mention parsing', async () => {
  const mock = await startWebhookMock();
  try {
    const result = await sendDiscordWebhookAlert(await mock.url, '[EncodingDB test] FAILURE (degraded)\nreasons: failed_analyses');
    assert.deepEqual({ delivered: result.delivered, attempts: result.attempts, httpStatus: result.httpStatus, error: result.error }, { delivered: true, attempts: 1, httpStatus: 204, error: null });
    const sent = mock.received[0].body;
    assert.deepEqual(sent.allowed_mentions, { parse: [] });
    assert.match(sent.content, /\[EncodingDB test\] FAILURE/);
    assert.match(mock.received[0].headers['user-agent'], /encodingdb-failure-alert/);
  } finally { mock.server.close(); }
});

test('non-2xx delivery reports failure with redacted context and never a false success', async () => {
  const leaked = 'https://discord.com/api/webhooks/1234567890/abcdefghijklmnop';
  const mock = await startWebhookMock([{ status: 500, body: { detail: `internal ${leaked} at /Users/ops/.codex/private/key` } }]);
  try {
    const url = await mock.url;
    const result = await sendDiscordWebhookAlert(url, 'boom', { maxAttempts: 1, redact: [leaked] });
    assert.equal(result.delivered, false);
    assert.equal(result.httpStatus, 500);
    assert.match(result.error, /webhook_http_500/);
    for (const needle of ['discord.com', 'abcdefghijklmnop', '/Users', leaked]) assert.ok(!result.error.includes(needle), `error leaked ${needle}`);
  } finally { mock.server.close(); }
});

test('429 waits for retry_after then succeeds within bounded attempts', async () => {
  const slept = [];
  const mock = await startWebhookMock([{ status: 429, body: { retry_after: 0.2 } }]);
  try {
    const result = await sendDiscordWebhookAlert(await mock.url, 'boom', { sleep: async (ms) => { slept.push(ms); } });
    assert.deepEqual({ delivered: result.delivered, attempts: result.attempts }, { delivered: true, attempts: 2 });
    assert.deepEqual(slept, [200]);
    assert.equal(mock.received.length, 2);
  } finally { mock.server.close(); }
});

test('persistent 429 stops at the attempt bound without claiming delivery', async () => {
  const mock = await startWebhookMock([{ status: 429, body: { retry_after: 5 } }, { status: 429, body: { retry_after: 5 } }, { status: 429, body: { retry_after: 5 } }]);
  try {
    const result = await sendDiscordWebhookAlert(await mock.url, 'boom', { sleep: async () => {}, maxAttempts: 3 });
    assert.equal(result.delivered, false);
    assert.equal(result.attempts, 3);
    assert.equal(result.httpStatus, 429);
    assert.match(result.error, /rate_limited/);
    assert.equal(mock.received.length, 3);
  } finally { mock.server.close(); }
});

test('transport failure is bounded and redacted of the webhook endpoint', async () => {
  const result = await sendDiscordWebhookAlert('https://127.0.0.1:1/api/webhooks/1/unreachable-endpoint-token', 'boom', { maxAttempts: 2, sleep: async () => {}, timeoutMs: 1_000 });
  assert.equal(result.delivered, false);
  assert.equal(result.attempts, 2);
  assert.ok(!JSON.stringify(result).includes('unreachable-endpoint-token'));
});

test('unchanged failure alerts once and re-notifies only after the renotify window, across processes', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock();
  const health = await startHealthMock([{ status: 503, body: degradedBody(['failed_analyses']) }, { status: 503, body: degradedBody(['failed_analyses']) }, { status: 503, body: degradedBody(['failed_analyses']) }]);
  const { now, advance } = clocked('2026-09-20T12:00:00.000Z');
  try {
    // Each poll uses a fresh monitor instance with the same state file = separate scheduled processes.
    const pollConfig = { environment: 'test', webhookUrl: await webhook.url, healthUrl: await health.url, statePath, now, sleep: async () => {}, minSendIntervalSeconds: 60, renotifySeconds: 3_600 };
    const first = await createFailureAlertMonitor(pollConfig).poll();
    assert.equal(first.action, 'sent');
    assert.equal(first.notified, true);
    const body = webhook.received[0].body.content;
    assert.match(body, /\[EncodingDB test\] FAILURE \(degraded\)/);
    assert.match(body, /reasons: failed_analyses/);
    assert.match(body, /context: pending_uploads=3 pending_analyses=2 expired_leases=1 retry_due=4 disk_available_mib=1024/);

    const second = await createFailureAlertMonitor(pollConfig).poll();
    assert.equal(second.action, 'suppressed_unchanged');
    assert.equal(webhook.received.length, 1);

    advance(3_601);
    const third = await createFailureAlertMonitor(pollConfig).poll();
    assert.equal(third.action, 'sent');
    assert.equal(webhook.received.length, 2);
  } finally { webhook.server.close(); health.server.close(); }
});

test('failed delivery is not marked sent and re-alerts after the retry backoff', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock([{ status: 500, body: { error: 'down' } }, { status: 204 }]);
  const health = await startHealthMock([{ status: 503, body: degradedBody(['missing_retained_objects']) }, { status: 503, body: degradedBody(['missing_retained_objects']) }]);
  const { now, advance } = clocked('2026-09-20T12:00:00.000Z');
  try {
    const monitor = createFailureAlertMonitor({ environment: 'test', webhookUrl: await webhook.url, healthUrl: await health.url, statePath, now, sleep: async () => {}, maxAttempts: 1, minSendIntervalSeconds: 30, retryBackoffSeconds: 30, renotifySeconds: 3_600 });
    const failed = await monitor.poll();
    assert.equal(failed.action, 'delivery_failed');
    assert.equal(failed.notified, false);
    const state = JSON.parse(await readFile(statePath, 'utf8'));
    assert.equal(state.episode.lastSentAt, null);
    assert.equal(state.episode.attempts, 1);

    advance(31);
    const retried = await monitor.poll();
    assert.equal(retried.action, 'sent');
    assert.equal(webhook.received.length, 2);
  } finally { webhook.server.close(); health.server.close(); }
});

test('recovery clears the episode and a later failure alerts again', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock();
  const health = await startHealthMock([
    { status: 503, body: degradedBody(['orphan_staging_entries']) },
    { status: 200, body: { status: 'ok', reasons: [], capturedAt: '2026-09-20T12:01:00.000Z' } },
    { status: 503, body: degradedBody(['orphan_staging_entries']) },
  ]);
  const { now, advance } = clocked('2026-09-20T12:00:00.000Z');
  try {
    const monitor = createFailureAlertMonitor({ environment: 'test', webhookUrl: await webhook.url, healthUrl: await health.url, statePath, now, sleep: async () => {}, minSendIntervalSeconds: 30, renotifySeconds: 3_600 });
    assert.equal((await monitor.poll()).action, 'sent');
    const recovered = await monitor.poll();
    assert.equal(recovered.action, 'recovered');
    assert.equal(webhook.received.length, 1);
    advance(31);
    assert.equal((await monitor.poll()).action, 'sent');
    assert.equal(webhook.received.length, 2);
  } finally { webhook.server.close(); health.server.close(); }
});

test('a second distinct failure inside the send floor is held, not burst', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock();
  const health = await startHealthMock([
    { status: 503, body: degradedBody(['failed_analyses']) },
    { status: 503, body: degradedBody(['storage_reserve_exhausted']) },
  ]);
  const { now } = clocked('2026-09-20T12:00:00.000Z');
  try {
    const monitor = createFailureAlertMonitor({ environment: 'test', webhookUrl: await webhook.url, healthUrl: await health.url, statePath, now, sleep: async () => {}, minSendIntervalSeconds: 300, renotifySeconds: 3_600 });
    assert.equal((await monitor.poll()).action, 'sent');
    const held = await monitor.poll();
    assert.equal(held.action, 'held_rate_limit');
    assert.deepEqual(held.reasons, ['storage_reserve_exhausted']);
    assert.equal(webhook.received.length, 1);
  } finally { webhook.server.close(); health.server.close(); }
});

test('backup absence never alerts under the accepted initial-launch policy', () => {
  const suppressed = evaluateFailureAlertRules({ status: 'degraded', reasons: ['backup_schedule_missing', 'failed_analyses'] });
  assert.deepEqual(suppressed.reasons, ['failed_analyses']);
  const onlyBackup = evaluateFailureAlertRules({ status: 'degraded', reasons: ['backup_schedule_missing'] });
  assert.equal(onlyBackup.alert, false);
  const enabled = evaluateFailureAlertRules({ status: 'degraded', reasons: ['backup_schedule_missing'] }, { backupMonitoringEnabled: true });
  assert.equal(enabled.alert, true);
});

test('health outage alerts as unreachable and cannot deliver false success', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock();
  const deadHealth = await startHealthMock();
  const deadUrl = await deadHealth.url;
  await new Promise((resolve) => deadHealth.server.close(resolve));
  const { now } = clocked('2026-09-20T12:00:00.000Z');
  try {
    const monitor = createFailureAlertMonitor({ environment: 'test', webhookUrl: await webhook.url, healthUrl: deadUrl, statePath, now, sleep: async () => {}, minSendIntervalSeconds: 300, renotifySeconds: 3_600 });
    const result = await monitor.poll();
    assert.equal(result.alertState, 'unreachable');
    assert.equal(result.action, 'sent');
    assert.match(webhook.received[0].body.content, /FAILURE \(unreachable\)/);
    assert.match(webhook.received[0].body.content, /health_unreachable/);
    assert.ok(!webhook.received[0].body.content.includes('127.0.0.1'));
  } finally { webhook.server.close(); }
});

test('non-health HTTP status classifies by status code without leaking the endpoint', async () => {
  const webhook = await startWebhookMock();
  const health = await startHealthMock([{ status: 500, body: { message: `internal at http://127.0.0.1:9999/health/v7-evidence` } }]);
  const { now } = clocked('2026-09-20T12:00:00.000Z');
  try {
    const monitor = createFailureAlertMonitor({ environment: 'test', webhookUrl: await webhook.url, healthUrl: await health.url, statePath: await tempState(), now, sleep: async () => {} });
    const result = await monitor.poll();
    assert.deepEqual(result.reasons, ['health_http_500']);
    assert.equal(webhook.received[0].body.content.includes('9999'), false);
  } finally { webhook.server.close(); health.server.close(); }
});

test('webhook secret file must be a regular file with no group or world access', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'v7-alert-secret-'));
  const open = path.join(dir, 'open');
  await writeFile(open, 'https://discord.com/api/webhooks/1/abc\n', { mode: 0o644 });
  await chmod(open, 0o644);
  assert.throws(() => loadDiscordWebhookSecret(open), /group_or_world_accessible/);
  assert.throws(() => loadDiscordWebhookSecret(dir), /not_regular_file/);

  const good = await writeWebhookFile('http://127.0.0.1:9/api/webhooks/1/abc');
  assert.equal(loadDiscordWebhookSecret(good, { allowLoopbackHttp: true }), 'http://127.0.0.1:9/api/webhooks/1/abc');
  assert.throws(() => loadDiscordWebhookSecret(good), /must_be_https/);

  const external = path.join(dir, 'external');
  await writeFile(external, 'http://example.invalid/api/webhooks/1/abc', { mode: 0o600 });
  await chmod(external, 0o600);
  assert.throws(() => loadDiscordWebhookSecret(external, { allowLoopbackHttp: true }), /must_be_https/);
});

test('redaction removes URLs, secrets, hashes and absolute paths', () => {
  const secret = 'https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz012345';
  const out = redactSecretText(`connect ${secret} token aaaaaaaaaaaaaaaaaaaa.bbbbbbbbbb.cccccccccccccc sha ${'a'.repeat(64)} file /Users/ops/.config/private/blob.bin`, [secret]);
  for (const needle of ['discord.com', 'abcdefghij', '/Users', 'aaaa']) assert.ok(!out.includes(needle), `leaked ${needle}`);
  assert.match(out, /\[url\]|\[redacted\]/);
});

test('alert content stays inside the Discord limit under a reason storm', async () => {
  const webhook = await startWebhookMock();
  try {
    const content = buildFailureAlertMessage({ environment: 'test', status: 'degraded', reasons: Array.from({ length: 300 }, (_u, i) => `reason_${i}`), capturedAt: '2026-09-20T00:00:00.000Z' });
    const result = await sendDiscordWebhookAlert(await webhook.url, content);
    assert.equal(result.delivered, true);
    assert.ok(webhook.received[0].body.content.length <= 2_000);
    assert.match(webhook.received[0].body.content, /\+288 more/);
  } finally { webhook.server.close(); }
});

test('CLI poll delivers through the private secret file end to end', async () => {
  const statePath = await tempState();
  const webhook = await startWebhookMock();
  const health = await startHealthMock([{ status: 503, body: degradedBody(['expired_analysis_leases']) }]);
  const secretFile = await writeWebhookFile(await webhook.url);
  try {
    const { stdout } = await execFileAsync(process.execPath, [new URL('../scripts/v7-failure-alert.mjs', import.meta.url).pathname, 'poll'], {
      env: {
        PATH: process.env.PATH,
        V7_ALERT_ENABLED: '1',
        V7_ALERT_ENVIRONMENT: 'cli-test',
        V7_ALERT_HEALTH_URL: await health.url,
        V7_ALERT_WEBHOOK_FILE: secretFile,
        V7_ALERT_STATE_FILE: statePath,
        V7_ALERT_MIN_SEND_INTERVAL_SECONDS: '0',
        V7_ALERT_HEALTH_TIMEOUT_MS: '2000',
        V7_ALERT_HTTP_TIMEOUT_MS: '2000',
      },
    });
    const result = JSON.parse(stdout);
    assert.equal(result.action, 'sent');
    assert.equal(result.notified, true);
    assert.match(webhook.received[0].body.content, /\[EncodingDB cli-test\] FAILURE \(degraded\)/);
    // A disabled run must not touch the network at all.
    const { stdout: skipped } = await execFileAsync(process.execPath, [new URL('../scripts/v7-failure-alert.mjs', import.meta.url).pathname, 'poll'], {
      env: { PATH: process.env.PATH, V7_ALERT_ENABLED: '0' },
    });
    assert.deepEqual(JSON.parse(skipped), { action: 'skipped_disabled' });
  } finally { webhook.server.close(); health.server.close(); }
});

test('connectivity test content is the single approved label', () => {
  assert.equal(TEST_CONNECTIVITY_CONTENT, '[EncodingDB TEST] Failure-alert delivery check. No production outage is being reported.');
});
