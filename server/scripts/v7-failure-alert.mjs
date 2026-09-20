#!/usr/bin/env node
// One-shot failure-alert runner for a scheduled tick (systemd timer or cron).
// `poll` reads the read-only evidence-health endpoint and delivers at most one
// redacted Discord alert, with persistent suppression/rate limiting in the
// state file. `test-connectivity` sends the one approved labelled delivery
// check. Neither mode ever prints, logs, or embeds the webhook credential.
import { loadDiscordWebhookSecret, createFailureAlertMonitor, sendDiscordWebhookAlert, TEST_CONNECTIVITY_CONTENT } from '../dist/v7/failureAlerts.js';

const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

function envNumber(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function validateEndpoint(name, raw) {
  let url;
  try { url = new URL(raw); } catch { throw new Error(`${name}_invalid_url`); }
  if (url.protocol === 'https:') return raw;
  if (url.protocol === 'http:' && LOOPBACK.has(url.hostname)) return raw;
  throw new Error(`${name}_must_be_https_or_loopback`);
}

const mode = process.argv[2];

if (mode === 'test-connectivity') {
  const webhook = loadDiscordWebhookSecret(process.env.V7_ALERT_WEBHOOK_FILE || '', { allowLoopbackHttp: true });
  const result = await sendDiscordWebhookAlert(webhook, TEST_CONNECTIVITY_CONTENT, { timeoutMs: envNumber('V7_ALERT_HTTP_TIMEOUT_MS', 10_000) });
  console.log(JSON.stringify({ test: 'failure-alert-connectivity', delivered: result.delivered, attempts: result.attempts, httpStatus: result.httpStatus, error: result.error, finishedAt: result.finishedAt }));
  process.exitCode = result.delivered ? 0 : 1;
} else if (mode === 'poll') {
  if ((process.env.V7_ALERT_ENABLED ?? '0') !== '1') {
    console.log(JSON.stringify({ action: 'skipped_disabled' }));
  } else {
    const healthUrl = validateEndpoint('health_url', process.env.V7_ALERT_HEALTH_URL || '');
    const webhook = loadDiscordWebhookSecret(process.env.V7_ALERT_WEBHOOK_FILE || '', { allowLoopbackHttp: true });
    const statePath = process.env.V7_ALERT_STATE_FILE || '';
    if (!statePath) throw new Error('V7_ALERT_STATE_FILE_required');
    const monitor = createFailureAlertMonitor({
      environment: process.env.V7_ALERT_ENVIRONMENT || 'production',
      webhookUrl: webhook,
      healthUrl,
      statePath,
      healthTimeoutMs: envNumber('V7_ALERT_HEALTH_TIMEOUT_MS', 10_000),
      httpTimeoutMs: envNumber('V7_ALERT_HTTP_TIMEOUT_MS', 10_000),
      minSendIntervalSeconds: envNumber('V7_ALERT_MIN_SEND_INTERVAL_SECONDS', 300),
      renotifySeconds: envNumber('V7_ALERT_RENOTIFY_SECONDS', 3_600),
      ...(process.env.V7_ALERT_BACKUP_MONITORING === '1' ? { backupMonitoringEnabled: true } : {}),
    });
    const result = await monitor.poll();
    console.log(JSON.stringify({ alertState: result.alertState, reasons: result.reasons, action: result.action, notified: result.notified, capturedAt: result.capturedAt, delivery: result.delivery && { delivered: result.delivery.delivered, attempts: result.delivery.attempts, httpStatus: result.delivery.httpStatus, error: result.delivery.error } }));
    process.exitCode = result.action === 'delivery_failed' ? 1 : 0;
  }
} else {
  console.error('usage: v7-failure-alert.mjs <poll|test-connectivity>');
  process.exitCode = 2;
}
