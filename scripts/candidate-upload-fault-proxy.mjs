#!/usr/bin/env node
// Isolated E2E transport faults only; never reports them as real server pressure.
import https from 'node:https';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const MODES = new Set(['pass', 'offline', 'pressure', 'lost-response-once']);
export function validateTarget(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.pathname !== '/' || url.search || url.hash)
    throw Error('Only an explicit HTTPS IPv4-loopback candidate origin is allowed');
  return url;
}

export function createFaultProxy({ upstream, ca, cert, key, mode, record, maxBytes = 256 * 1024 * 1024, maxResponseBytes = 1024 * 1024, timeoutMs = 300000, maxActive = 4 }) {
  const target = validateTarget(upstream);
  for (const budget of [maxBytes, maxResponseBytes, timeoutMs, maxActive]) {
    if (!Number.isSafeInteger(budget) || budget < 1) throw Error('Proxy budgets must be positive safe integers');
  }
  let active = 0;
  let lostResponseClaimed = false;
  return https.createServer({ cert, key, requestTimeout: timeoutMs, headersTimeout: Math.min(10000, timeoutMs) }, (request, response) => {
    if (active >= maxActive) {
      request.resume();
      response.writeHead(503, { 'retry-after': '1' }).end();
      record({ kind: 'proxy-capacity-limit', injected: true, status: 503 });
      return;
    }
    active++;
    let outgoing;
    let finished = false;
    const deadline = setTimeout(() => {
      record({ kind: 'proxy-deadline', injected: true });
      outgoing?.destroy(); request.destroy(); response.destroy();
    }, timeoutMs);
    deadline.unref();
    const finish = () => { if (!finished) { finished = true; active--; clearTimeout(deadline); } };
    response.on('close', finish);
    response.on('finish', finish);
    request.on('error', () => outgoing?.destroy());
    request.setTimeout(timeoutMs, () => { outgoing?.destroy(); request.destroy(); });
    const pathname = String(request.url || '').split('?')[0];
    if (String(request.url || '').length > 4096 || !pathname.startsWith('/') || pathname.startsWith('//')) {
      request.resume(); response.writeHead(400).end(); return;
    }
    const path = pathname.replace(/(\/artifact-uploads\/)[^/]+/g, '$1<redacted>');
    const isUpload = request.method === 'PUT' && pathname.startsWith('/v7/artifact-uploads/');
    const isWrite = ['POST', 'PUT'].includes(request.method) && pathname.startsWith('/v7/');
    let selected;
    try { selected = mode(); if (!MODES.has(selected)) throw Error(); }
    catch { request.resume(); response.writeHead(503).end(); return; }
    if ((selected === 'offline' && isWrite) || (selected === 'pressure' && pathname.endsWith('/upload-authorizations'))) {
      const status = selected === 'offline' ? 503 : 429;
      request.resume();
      record({ kind: selected, method: request.method, path, injected: true, status });
      response.writeHead(status, { 'content-type': 'application/json', 'retry-after': '2' });
      response.end(JSON.stringify({ error: 'isolated-e2e-injected-transport-fault' }));
      return;
    }
    const reserveLostResponse = selected === 'lost-response-once' && isUpload && !lostResponseClaimed;
    if (reserveLostResponse) lostResponseClaimed = true;
    const headers = { ...request.headers, host: target.host };
    for (const header of ['connection', 'proxy-connection', 'keep-alive', 'upgrade']) delete headers[header];
    let bytes = 0;
    outgoing = https.request(target, { method: request.method, path: request.url, headers, ca, rejectUnauthorized: true, timeout: timeoutMs }, (incoming) => {
      const drop = reserveLostResponse && incoming.statusCode >= 200 && incoming.statusCode < 300;
      if (reserveLostResponse && !drop) lostResponseClaimed = false;
      let responseBytes = 0;
      incoming.on('data', (chunk) => {
        responseBytes += chunk.length;
        if (responseBytes > maxResponseBytes) {
          record({ kind: 'proxy-response-limit', method: request.method, path, injected: true, responseBytes });
          incoming.destroy(); outgoing.destroy(); response.destroy();
        }
      });
      incoming.on('error', () => response.destroy());
      incoming.on('end', () => {
        record({ kind: drop ? 'lost-response-after-upstream-success' : 'forwarded', method: request.method, path,
          injected: drop, status: incoming.statusCode, requestBytes: bytes });
        if (drop) response.destroy();
      });
      if (drop) incoming.resume();
      else { response.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(response); }
    });
    outgoing.on('timeout', () => outgoing.destroy(Error('candidate-request-deadline')));
    outgoing.on('error', () => {
      if (reserveLostResponse) lostResponseClaimed = false;
      record({ kind: 'upstream-connection-failure', method: request.method, path, injected: false });
      if (!response.headersSent) response.writeHead(502);
      response.end();
    });
    response.on('close', () => { if (!response.writableFinished) outgoing.destroy(); });
    request.on('data', (chunk) => {
      bytes += chunk.length;
      if (bytes > maxBytes) {
        record({ kind: 'proxy-body-limit', method: request.method, path, injected: true, requestBytes: bytes });
        outgoing.destroy(); request.destroy(); response.destroy();
      }
    });
    request.pipe(outgoing);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const required = (name) => { if (!process.env[name]) throw Error(`${name} is required`); return process.env[name]; };
  const upstream = required('CANDIDATE_UPSTREAM_URL');
  if (validateTarget(upstream).port !== '3094') throw Error('This candidate lane requires upstream TLS port3094');
  const port = Number(required('CANDIDATE_FAULT_PORT'));
  if (port !== 3096) throw Error('This candidate lane reserves loopback port3096');
  const modeFile = required('CANDIDATE_FAULT_MODE_FILE');
  const evidence = fs.openSync(required('CANDIDATE_FAULT_EVIDENCE'), 'wx', 0o600);
  let events = 0;
  const server = createFaultProxy({ upstream,
    ca: fs.readFileSync(required('CANDIDATE_CA_FILE')),
    cert: fs.readFileSync(required('CANDIDATE_CERT_FILE')),
    key: fs.readFileSync(required('CANDIDATE_KEY_FILE')),
    mode: () => { if (fs.statSync(modeFile).size > 128) throw Error(); return fs.readFileSync(modeFile, 'utf8').trim(); },
    record: (entry) => {
      if (++events > 10000) { server.close(); server.closeAllConnections(); return; }
      fs.writeSync(evidence, JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n');
      fs.fsyncSync(evidence);
    },
  });
  server.listen(port, '127.0.0.1', () => console.log(`Candidate fault proxy listening on loopback:${port}`));
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { server.close(); server.closeAllConnections(); });
}
