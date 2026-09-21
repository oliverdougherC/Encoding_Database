/**
 * Failure-alert monitor for the v7 evidence-health contract.
 *
 * Polls the read-only `/health/v7-evidence` endpoint, maps degraded reasons to a
 * concise Discord webhook alert, and persists duplicate suppression plus rate
 * limiting on disk so separate scheduled invocations cannot spam the channel.
 * The webhook credential lives only in a private mode-0600 file outside the
 * repository and only ever in process memory; nothing here logs or embeds it.
 * Delivery is reported honestly: `delivered` is true only after a 2xx response.
 */
import { lstatSync, openSync, readSync, closeSync } from 'node:fs';
import { mkdir, open, rename, chmod, readFile } from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

const LOOPBACK_HOSTS: Record<string, true> = { '127.0.0.1': true, localhost: true, '[::1]': true };
const OUTGOING_CONTENT_LIMIT = 1900;

export type AlertFetchInit = { method: string; headers?: Record<string, string>; body?: string; signal: AbortSignal };

export type AlertResponseLike = {
  status: number;
  headers?: { get(name: string): string | null } | undefined;
  text?: (() => Promise<string>) | undefined;
  json?: (() => Promise<unknown>) | undefined;
};

export type AlertFetch = (url: string, init: AlertFetchInit) => Promise<AlertResponseLike>;

export type DiscordDeliveryResult = {
  delivered: boolean;
  attempts: number;
  httpStatus: number | null;
  error: string | null;
  finishedAt: string;
};

/** Replace URLs, credential-shaped runs, absolute paths and control text. Bounded length. */
export function redactSecretText(value: unknown, extraSecrets: string[] = []): string {
  let out = String(value ?? '');
  for (const secret of extraSecrets) if (secret && secret.length >= 6) out = out.split(secret).join('[redacted]');
  out = out
    .replace(/https?:\/\/\S+/gi, '[url]')
    .replace(/\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g, '[token]')
    .replace(/\b[a-f0-9]{40,}\b/gi, '[hash]')
    .replace(/\b[A-Za-z0-9+/_-]{40,}={0,2}\b/g, '[secret]')
    .replace(/(?:[A-Za-z]:)?(?:[/\\][\w.@-]+){2,}/g, '[path]')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return out.length > 200 ? `${out.slice(0, 200)}…` : out;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function defaultSleep(ms: number): Promise<void> {
  // Executor form kept: Promise.withResolvers requires Node 22 and the P910 runtime is pinned to Node 20.
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Read the webhook URL from a private file. Rejects group/world access bits,
 * non-regular files, and any non-https endpoint except loopback http, which is
 * only useful for local mock delivery checks.
 */
export function loadDiscordWebhookSecret(filePath: string, options?: { allowLoopbackHttp?: boolean }): string {
  const info = lstatSync(filePath);
  if (!info.isFile()) throw new Error('webhook_secret_not_regular_file');
  if (info.mode & 0o077) throw new Error('webhook_secret_group_or_world_accessible');
  let fd: number | undefined;
  try {
    fd = openSync(filePath, 'r');
    const buffer = Buffer.alloc(8192);
    const read = readSync(fd, buffer, 0, buffer.length, 0);
    const value = buffer.subarray(0, read).toString('utf8').trim();
    if (!value) throw new Error('webhook_secret_empty');
    if (/\s/.test(value)) throw new Error('webhook_secret_contains_whitespace');
    let url: URL;
    try { url = new URL(value); } catch { throw new Error('webhook_secret_not_url'); }
    const loopback = options?.allowLoopbackHttp === true && url.protocol === 'http:' && LOOPBACK_HOSTS[url.hostname] === true;
    if (url.protocol !== 'https:' && !loopback) throw new Error('webhook_secret_url_must_be_https');
    if (!url.hostname) throw new Error('webhook_secret_url_missing_host');
    return value;
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}

async function safeBodySnippet(response: AlertResponseLike, secrets: string[]): Promise<string> {
  try {
    if (typeof response.text !== 'function') return '';
    const raw = (await response.text()) ?? '';
    return redactSecretText(raw.slice(0, 400), secrets);
  } catch { return ''; }
}

async function retryAfterSeconds(response: AlertResponseLike, maxSeconds: number): Promise<number> {
  let seconds: number | null = null;
  try {
    if (typeof response.json === 'function') {
      const body = await response.json() as { retry_after?: unknown } | null;
      const value = Number(body?.retry_after);
      if (Number.isFinite(value) && value >= 0) seconds = value;
    }
  } catch { /* fall through to header */ }
  if (seconds == null) {
    try {
      const header = response.headers?.get?.('retry-after');
      const value = Number(header);
      if (header != null && Number.isFinite(value) && value >= 0) seconds = value;
    } catch { /* ignore */ }
  }
  // No usable hint: still back off, bounded and small.
  return clamp(seconds ?? 1, 0.05, maxSeconds);
}

export type DiscordSendOptions = {
  timeoutMs?: number;
  maxAttempts?: number;
  maxRetryAfterSeconds?: number;
  fetchImpl?: AlertFetch;
  sleep?: (ms: number) => Promise<void>;
  /** Extra literal secrets to scrub from any error text (e.g. the webhook URL). */
  redact?: string[];
};

/**
 * POST a Discord webhook message with `allowed_mentions.parse=[]` so no ping is
 * possible. Bounded timeout per attempt; 429 is retried respecting `retry_after`
 * (capped); network errors retry with bounded backoff. Never reports success
 * without a 2xx. The webhook URL is never included in any returned field.
 */
export async function sendDiscordWebhookAlert(
  webhookUrl: string,
  content: string,
  options?: DiscordSendOptions,
): Promise<DiscordDeliveryResult> {
  const fetchImpl = options?.fetchImpl ?? (globalThis.fetch as unknown as AlertFetch | undefined);
  if (typeof fetchImpl !== 'function') throw new Error('fetch_unavailable');
  const sleep = options?.sleep ?? defaultSleep;
  const timeoutMs = clamp(Math.trunc(options?.timeoutMs ?? 10_000), 1_000, 30_000);
  const maxAttempts = clamp(Math.trunc(options?.maxAttempts ?? 3), 1, 5);
  const maxRetryAfterSeconds = clamp(options?.maxRetryAfterSeconds ?? 30, 0.05, 120);
  const secrets = [webhookUrl, ...(options?.redact ?? [])];
  let outgoing = String(content ?? '');
  if (outgoing.length > OUTGOING_CONTENT_LIMIT) outgoing = `${outgoing.slice(0, OUTGOING_CONTENT_LIMIT - 12)}…[truncated]`;
  const body = JSON.stringify({ content: outgoing, allowed_mentions: { parse: [] } });

  let lastStatus: number | null = null;
  let lastError: string | null = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetchImpl(webhookUrl, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'user-agent': 'encodingdb-failure-alert/1.0' },
        body,
        signal: AbortSignal.timeout(timeoutMs),
      });
      lastStatus = response.status ?? null;
      if (lastStatus != null && lastStatus >= 200 && lastStatus < 300) {
        return { delivered: true, attempts: attempt, httpStatus: lastStatus, error: null, finishedAt: new Date().toISOString() };
      }
      if (lastStatus === 429) {
        lastError = 'webhook_rate_limited';
        if (attempt < maxAttempts) {
          await sleep((await retryAfterSeconds(response, maxRetryAfterSeconds)) * 1000);
          continue;
        }
        return { delivered: false, attempts: attempt, httpStatus: lastStatus, error: lastError, finishedAt: new Date().toISOString() };
      }
      const snippet = await safeBodySnippet(response, secrets);
      return {
        delivered: false,
        attempts: attempt,
        httpStatus: lastStatus,
        error: redactSecretText(`webhook_http_${lastStatus}${snippet ? `: ${snippet}` : ''}`, secrets),
        finishedAt: new Date().toISOString(),
      };
    } catch (error) {
      const name = error instanceof Error ? error.name : 'unknown';
      lastStatus = null;
      lastError = redactSecretText(/timeout|abort/i.test(name) ? `request_${name.toLowerCase()}` : `request_failed_${name}`, secrets);
      if (attempt < maxAttempts) await sleep(Math.min(500 * attempt, 2_000));
    }
  }
  return { delivered: false, attempts: maxAttempts, httpStatus: lastStatus, error: lastError ?? 'delivery_exhausted', finishedAt: new Date().toISOString() };
}

/**
 * Map a health snapshot to alert-worthy reasons. Under the accepted initial
 * launch policy backups are intentionally not configured, so `backup*` reasons
 * are dropped until `backupMonitoringEnabled` is set (the policy is a config
 * switch, not a code change, and its absence must never fire an alert).
 */
export function evaluateFailureAlertRules(
  health: { status?: unknown; reasons?: unknown },
  options?: { backupMonitoringEnabled?: boolean },
): { alert: boolean; key: string; reasons: string[] } {
  const allowBackupReasons = options?.backupMonitoringEnabled === true;
  const all = Array.isArray(health.reasons) ? health.reasons.map((reason) => String(reason)) : [];
  const reasons = allowBackupReasons ? all : all.filter((reason) => !/^backup/i.test(reason));
  const unique = [...new Set(reasons)];
  const key = [...unique].sort().join(',');
  return { alert: health.status !== 'ok' && unique.length > 0, key, reasons: unique };
}

function num(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : null;
}

function contextFacts(body: Record<string, unknown>): string[] {
  const capacity = (body.capacity ?? {}) as Record<string, unknown>;
  const artifacts = (body.artifacts ?? {}) as Record<string, unknown>;
  const storage = (body.storage ?? {}) as Record<string, unknown>;
  const staging = (body.staging ?? {}) as Record<string, unknown>;
  const tokens: string[] = [];
  const add = (name: string, value: unknown): void => {
    const parsed = num(value);
    if (parsed != null && parsed > 0) tokens.push(`${name}=${parsed}`);
  };
  add('pending_uploads', capacity.pendingUploads ?? capacity.reservedUploads);
  add('pending_analyses', capacity.pendingAnalyses ?? capacity.analysisAdmissionUsed);
  add('expired_leases', capacity.expiredLeases);
  add('retry_due', capacity.retryDue);
  add('missing_retained', artifacts.missingRetainedObjects);
  add('stale_staging', staging.staleEntryCount);
  const available = num(storage.availableBytes);
  if (available != null) tokens.push(`disk_available_mib=${Math.round(available / 1_048_576)}`);
  return tokens.slice(0, 7);
}

/** Concise operator-facing alert text: label, reasons, capture time, numeric context. */
export function buildFailureAlertMessage(input: {
  environment: string;
  status: string;
  reasons: string[];
  capturedAt: string | null;
  context?: string[];
}): string {
  const environment = (redactSecretText(input.environment).replace(/[^A-Za-z0-9 ._ -]/g, '').trim() || 'unknown').slice(0, 32);
  const reasons = input.reasons.slice(0, 12);
  const overflow = input.reasons.length - reasons.length;
  const lines = [
    `[EncodingDB ${environment}] FAILURE (${input.status})`,
    `reasons: ${reasons.join(', ')}${overflow > 0 ? ` +${overflow} more` : ''}`,
    `captured: ${redactSecretText(input.capturedAt ?? 'unavailable')}`,
  ];
  if (input.context && input.context.length > 0) lines.push(`context: ${input.context.join(' ')}`);
  const content = lines.join('\n');
  return content.length > OUTGOING_CONTENT_LIMIT ? `${content.slice(0, OUTGOING_CONTENT_LIMIT - 12)}…[truncated]` : content;
}

export const TEST_CONNECTIVITY_CONTENT = '[EncodingDB TEST] Failure-alert delivery check. No production outage is being reported.';

type EpisodeState = {
  key: string;
  reasons: string[];
  startedAt: string;
  lastSentAt: string | null;
  attempts: number;
  lastFailureAt: string | null;
  lastError: string | null;
};

type AlertStateFile = { version: 1; episode: EpisodeState | null; lastSendAt: string | null };

const EMPTY_STATE: AlertStateFile = { version: 1, episode: null, lastSendAt: null };

function parseState(raw: string): AlertStateFile {
  try {
    const value = JSON.parse(raw) as Partial<AlertStateFile>;
    if (value.version !== 1) return { ...EMPTY_STATE };
    const episode = value.episode;
    if (episode !== null && episode !== undefined) {
      if (typeof episode !== 'object' || typeof episode.key !== 'string' || !Array.isArray(episode.reasons)) return { ...EMPTY_STATE };
      if (episode.lastSentAt !== null && typeof episode.lastSentAt !== 'string') return { ...EMPTY_STATE };
    }
    return { version: 1, episode: (episode ?? null) as EpisodeState | null, lastSendAt: typeof value.lastSendAt === 'string' ? value.lastSendAt : null };
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function readAlertState(statePath: string): Promise<AlertStateFile> {
  try {
    return parseState(await readFile(statePath, 'utf8'));
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function writeAlertState(statePath: string, state: AlertStateFile): Promise<void> {
  await mkdir(path.dirname(statePath), { recursive: true });
  const temp = `${statePath}.${randomBytes(6).toString('hex')}.tmp`;
  const handle = await open(temp, 'wx', 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(state)}\n`, 'utf8');
    await handle.sync();
  } finally {
    await handle.close();
  }
  await chmod(temp, 0o600);
  await rename(temp, statePath);
}

export type FailureAlertPollResult = {
  alertState: 'ok' | 'degraded' | 'unreachable';
  reasons: string[];
  action: 'none' | 'recovered' | 'sent' | 'suppressed_unchanged' | 'held_backoff' | 'held_rate_limit' | 'delivery_failed';
  notified: boolean;
  capturedAt: string;
  delivery: DiscordDeliveryResult | null;
};

export type FailureAlertConfig = {
  environment: string;
  webhookUrl: string;
  healthUrl: string;
  statePath: string;
  healthTimeoutMs?: number;
  httpTimeoutMs?: number;
  maxAttempts?: number;
  maxRetryAfterSeconds?: number;
  /** Floor between any two send attempts, all keys, persisted across runs. */
  minSendIntervalSeconds?: number;
  /** Repeat-notify interval for an unchanged failure episode. */
  renotifySeconds?: number;
  /** Wait after a failed delivery before re-attempting the same episode. */
  retryBackoffSeconds?: number;
  backupMonitoringEnabled?: boolean;
  fetchImpl?: AlertFetch;
  sleep?: (ms: number) => Promise<void>;
  now?: () => Date;
};

async function readHealth(fetchImpl: AlertFetch, healthUrl: string, timeoutMs: number): Promise<{ httpStatus: number | null; body: Record<string, unknown> | null; transportError: boolean }> {
  try {
    const response = await fetchImpl(healthUrl, { method: 'GET', headers: { accept: 'application/json' }, signal: AbortSignal.timeout(timeoutMs) });
    if (response.status !== 200 && response.status !== 503) return { httpStatus: response.status ?? null, body: null, transportError: false };
    let body: Record<string, unknown> | null = null;
    try {
      if (typeof response.json === 'function') {
        const parsed = await response.json();
        if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
      }
    } catch { /* non-JSON degraded body; classified below */ }
    return { httpStatus: response.status ?? null, body, transportError: false };
  } catch {
    return { httpStatus: null, body: null, transportError: true };
  }
}

/**
 * Persistent single-shot failure-alert monitor. Designed to be run once per
 * scheduled tick: state (episode identity, last send time, delivery failures)
 * lives in a 0600 file so separate processes share suppression/rate limits.
 */
export function createFailureAlertMonitor(config: FailureAlertConfig) {
  const requestedFetch = config.fetchImpl ?? (globalThis.fetch as unknown as AlertFetch | undefined);
  if (typeof requestedFetch !== 'function') throw new Error('fetch_unavailable');
  const fetcher: AlertFetch = requestedFetch;
  const sleep = config.sleep ?? defaultSleep;
  const now = config.now ?? (() => new Date());
  const healthTimeoutMs = clamp(Math.trunc(config.healthTimeoutMs ?? 10_000), 1_000, 60_000);
  const minSendIntervalSeconds = Math.max(0, config.minSendIntervalSeconds ?? 300);
  const renotifySeconds = Math.max(0, config.renotifySeconds ?? 3_600);
  const retryBackoffSeconds = Math.max(0, config.retryBackoffSeconds ?? minSendIntervalSeconds);

  async function poll(): Promise<FailureAlertPollResult> {
    const current = now();
    const capturedAt = current.toISOString();
    const state = await readAlertState(config.statePath);

    const health = await readHealth(fetcher, config.healthUrl, healthTimeoutMs);
    let alertState: FailureAlertPollResult['alertState'];
    let reasons: string[];
    let alert: boolean;
    let key: string;
    let context: string[] = [];
    if (health.transportError) {
      alertState = 'unreachable'; reasons = ['health_unreachable']; alert = true; key = 'health_unreachable';
    } else if (health.httpStatus != null && health.httpStatus !== 200 && health.httpStatus !== 503) {
      alertState = 'unreachable'; reasons = [`health_http_${health.httpStatus}`]; alert = true; key = reasons[0]!;
    } else if (health.body && Array.isArray(health.body.reasons)) {
      const evaluated = evaluateFailureAlertRules({ status: String(health.body.status ?? 'degraded'), reasons: health.body.reasons }, ...(config.backupMonitoringEnabled !== undefined ? [{ backupMonitoringEnabled: config.backupMonitoringEnabled }] : []));
      if (health.body.status === 'ok') { alertState = 'ok'; reasons = []; alert = false; key = ''; }
      else { alertState = 'degraded'; reasons = evaluated.reasons; alert = evaluated.alert; key = evaluated.key; context = contextFacts(health.body); }
    } else if (health.httpStatus === 503) {
      alertState = 'degraded'; reasons = ['evidence_health_unavailable']; alert = true; key = 'evidence_health_unavailable';
    } else {
      alertState = 'ok'; reasons = []; alert = false; key = '';
    }

    if (!alert) {
      if (state.episode) {
        await writeAlertState(config.statePath, { version: 1, episode: null, lastSendAt: state.lastSendAt });
        return { alertState: 'ok', reasons: [], action: 'recovered', notified: false, capturedAt, delivery: null };
      }
      return { alertState, reasons, action: 'none', notified: false, capturedAt, delivery: null };
    }

    const episode = state.episode;
    const sameEpisode = episode != null && episode.key === key;
    if (sameEpisode && episode.lastSentAt != null) {
      const sinceSentSeconds = (current.getTime() - Date.parse(episode.lastSentAt)) / 1_000;
      if (Number.isFinite(sinceSentSeconds) && sinceSentSeconds < renotifySeconds) {
        return { alertState, reasons, action: 'suppressed_unchanged', notified: false, capturedAt, delivery: null };
      }
    }
    if (sameEpisode && episode.lastSentAt == null) {
      const sinceFailureSeconds = (current.getTime() - Date.parse(episode.lastFailureAt ?? episode.startedAt)) / 1_000;
      if (Number.isFinite(sinceFailureSeconds) && sinceFailureSeconds < retryBackoffSeconds) {
        return { alertState, reasons, action: 'held_backoff', notified: false, capturedAt, delivery: null };
      }
    }
    if (state.lastSendAt != null) {
      const sinceAnySendSeconds = (current.getTime() - Date.parse(state.lastSendAt)) / 1_000;
      if (Number.isFinite(sinceAnySendSeconds) && sinceAnySendSeconds < minSendIntervalSeconds) {
        return { alertState, reasons, action: 'held_rate_limit', notified: false, capturedAt, delivery: null };
      }
    }

    const content = buildFailureAlertMessage({
      environment: config.environment,
      status: alertState === 'unreachable' ? 'unreachable' : 'degraded',
      reasons,
      capturedAt: typeof health.body?.capturedAt === 'string' ? health.body.capturedAt : capturedAt,
      context,
    });
    // Attempt time counts against the shared floor even if delivery fails, so a
    // broken webhook cannot turn every scheduled tick into a fresh attempt burst.
    await writeAlertState(config.statePath, { version: 1, episode: state.episode, lastSendAt: capturedAt });
    const delivery = await sendDiscordWebhookAlert(config.webhookUrl, content, {
      ...(config.httpTimeoutMs != null ? { timeoutMs: config.httpTimeoutMs } : {}),
      ...(config.maxAttempts != null ? { maxAttempts: config.maxAttempts } : {}),
      ...(config.maxRetryAfterSeconds != null ? { maxRetryAfterSeconds: config.maxRetryAfterSeconds } : {}),
      fetchImpl: fetcher,
      sleep,
      redact: [config.healthUrl],
    });
    const nextEpisode: EpisodeState = {
      key,
      reasons,
      startedAt: sameEpisode ? episode.startedAt : capturedAt,
      lastSentAt: delivery.delivered ? capturedAt : (sameEpisode ? episode.lastSentAt : null),
      attempts: sameEpisode && !delivery.delivered ? episode.attempts + 1 : delivery.delivered ? 0 : 1,
      lastFailureAt: delivery.delivered ? null : capturedAt,
      lastError: delivery.error,
    };
    await writeAlertState(config.statePath, { version: 1, episode: nextEpisode, lastSendAt: capturedAt });
    return {
      alertState,
      reasons,
      action: delivery.delivered ? 'sent' : 'delivery_failed',
      notified: delivery.delivered,
      capturedAt,
      delivery,
    };
  }

  return { poll };
}
