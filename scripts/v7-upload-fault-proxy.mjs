#!/usr/bin/env node

import { createServer } from 'node:http';
import { writeFileSync } from 'node:fs';

const upstream = new URL(process.env.UPSTREAM_URL || 'http://127.0.0.1:3001');
const port = Number(process.env.PORT || 3011);
const evidencePath = process.env.EVIDENCE_PATH;
if (!evidencePath) throw new Error('EVIDENCE_PATH is required');

const evidence = {
  evidenceVersion: 'encodingdb-upload-interruption/v1',
  upstream: upstream.toString(),
  injectedFailures: 0,
  uploadAttempts: [],
};

function persist() {
  writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, { encoding: 'utf8' });
}

function tokenIdentity(pathname) {
  try {
    const token = pathname.split('/').at(-1) || '';
    const payload = JSON.parse(Buffer.from(token.split('.')[0], 'base64url').toString('utf8'));
    return {
      benchmarkRunId: payload.benchmarkRunId ?? null,
      artifactId: payload.artifactId ?? null,
    };
  } catch {
    return { benchmarkRunId: null, artifactId: null };
  }
}

const server = createServer(async (request, response) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const body = Buffer.concat(chunks);
  const target = new URL(request.url || '/', upstream);
  const isUpload = request.method === 'PUT' && target.pathname.startsWith('/v7/artifact-uploads/');
  const identity = isUpload ? tokenIdentity(target.pathname) : null;

  if (isUpload && evidence.injectedFailures === 0) {
    evidence.injectedFailures = 1;
    evidence.uploadAttempts.push({
      sequence: evidence.uploadAttempts.length + 1,
      ...identity,
      injected: true,
      status: 503,
      byteSize: body.length,
      at: new Date().toISOString(),
    });
    persist();
    response.writeHead(503, { 'content-type': 'application/json', 'retry-after': '0' });
    response.end(JSON.stringify({ error: 'certification-injected-upload-interruption' }));
    return;
  }

  try {
    const headers = { ...request.headers };
    delete headers.host;
    delete headers['content-length'];
    const upstreamResponse = await fetch(target, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method || '') ? undefined : body,
      redirect: 'manual',
    });
    const upstreamBody = Buffer.from(await upstreamResponse.arrayBuffer());
    if (isUpload) {
      evidence.uploadAttempts.push({
        sequence: evidence.uploadAttempts.length + 1,
        ...identity,
        injected: false,
        status: upstreamResponse.status,
        byteSize: body.length,
        at: new Date().toISOString(),
      });
      persist();
    }
    const responseHeaders = Object.fromEntries(upstreamResponse.headers.entries());
    delete responseHeaders['content-encoding'];
    delete responseHeaders['content-length'];
    response.writeHead(upstreamResponse.status, responseHeaders);
    response.end(upstreamBody);
  } catch (error) {
    response.writeHead(502, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
  }
});

persist();
server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`upload fault proxy listening on ${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
