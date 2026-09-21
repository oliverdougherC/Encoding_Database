import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import { createArtifactPipelineRouter, DEFAULT_ANALYZER_VERSION, SERVER_CANONICAL_RECIPE_RULES,
  SERVER_CANONICAL_OUTPUT_RULES } from '../dist/v7/artifacts.js';

test('compatibility checks persisted epoch before allowing costly client work', async () => {
  let active = [];
  let unavailable = false;
  const app = express();
  app.use(createArtifactPipelineRouter({
    persistence: { async getCompatibilityProtocols() { if (unavailable) throw new Error('offline'); return active; } },
    analyzer: { async analyze() { throw new Error('compatibility must never analyze media'); } },
  }));
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const url = `http://127.0.0.1:${server.address().port}/v7/compatibility`;
  try {
    const initial = await fetch(url);
    assert.equal(initial.status, 200);
    const contract = await initial.json();
    assert.equal(contract.sourceSuiteVersion, 'encodingdb-test-suite-v1');
    assert.equal(contract.suiteFingerprint, 'd40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e');
    const compatible = { id: 'current', state: 'ACTIVE', protocolVersion: '7.1', sourceSuiteVersion: contract.sourceSuiteVersion,
      minimumClientVersion: 'client/0.3.0', metricWorkerVersion: DEFAULT_ANALYZER_VERSION,
      canonicalRecipeRules: SERVER_CANONICAL_RECIPE_RULES, canonicalOutputRules: SERVER_CANONICAL_OUTPUT_RULES };
    active = [{ ...compatible, protocolVersion: '7.0' }];
    assert.equal((await fetch(url)).status, 409);
    active = [{ ...compatible, metricWorkerVersion: 'retired-worker' }];
    assert.equal((await fetch(url)).status, 409);
    active = [{ ...compatible, state: 'RETIRED' }];
    assert.equal((await fetch(url)).status, 409);
    active = [{ ...compatible, state: 'DRAFT' }];
    assert.equal((await fetch(url)).status, 409);
    active = [compatible, compatible];
    assert.equal((await fetch(url)).status, 409);
    active = [compatible];
    assert.equal((await (await fetch(url)).json()).activeProtocolId, 'current');
    unavailable = true;
    assert.equal((await fetch(url)).status, 503);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
