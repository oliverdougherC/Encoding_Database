import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  buildActivationPersistencePayloads,
  buildProductionEnvBindings,
  loadProductionActivationPlan,
  persistActivationState,
} from '../../scripts/activate-pl-v7-production.mjs';
import {
  buildReferenceContextBindings,
  parseEnvText,
  validateProductionEnv,
} from '../../scripts/validate-production-env.mjs';
import { parseReferenceContext } from '../dist/v7/referenceContext.js';

const contextFixturePath = new URL('../config/reference-contexts/test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.context.json', import.meta.url);
const draftCalibrationPath = new URL('../config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json', import.meta.url);
const testDir = path.dirname(fileURLToPath(import.meta.url));

function productionContextFixture() {
  const provisional = parseReferenceContext(readFileSync(contextFixturePath, 'utf8'));
  return {
    ...provisional,
    activation: {
      stage: 'PRODUCTION',
      productionActivationAllowed: true,
      note: 'Activated after review.',
      calibrationVersion: 'pla-87-final',
      calibrationReviewHash: 'a'.repeat(64),
    },
    hash: provisional.hash,
  };
}

function activationEvidenceFixture() {
  return [{
    qualityAnalysisId: 'analysis-workload-1',
    analysisWorkerVersion: 'authoritative-analysis/v1',
    benchmarkRunId: 'run-workload-1',
    benchmarkProtocolVersion: '7.0',
    sourceSuiteVersion: 'encodingdb-test-suite-v1',
    workloadId: 'sports-action-960x540-24p',
    testClipId: 'clip-workload-1',
    contentClass: 'high-motion-sports',
    recipeId: 'recipe-1',
    recipeFingerprint: 'recipe-fingerprint',
    environmentId: 'env-1',
    environmentFingerprint: 'environment-fingerprint',
    qualityModelId: 'vmaf-v1-sdr-sd',
    benchmarkRunStatus: 'ACCEPTED',
    qualityAnalysisStatus: 'COMPLETE',
    encodeFps: 120,
    sourceFps: 24,
    realTimeRatio: 5,
    videoBitrateBps: 4_000_000,
    fileSizeBytes: 7_340_032,
    vmafMean: 95,
    vmafP5: 90,
  }];
}

function activationRecomputeFixture() {
  return {
    scoreContexts: [],
    derivedResults: [{
      kind: 'WORKLOAD',
      scopeKey: 'workload:sports-action-960x540-24p',
      benchmarkProtocolVersion: '7.0',
      sourceSuiteVersion: 'encodingdb-test-suite-v1',
      formulaVersion: '7.0',
      scoreContextVersion: 'ctx-v1',
      qualityModelId: 'vmaf-v1-sdr-sd',
      workloadId: 'sports-action-960x540-24p',
      contentClass: 'high-motion-sports',
      recipeId: 'recipe-1',
      environmentId: 'env-1',
      acceptedRunCount: 1,
      suspectRunCount: 0,
      rejectedRunCount: 0,
      repetitionCount: 1,
      centerEncodeFps: 120,
      centerRealTimeRatio: 5,
      centerVideoBitrateBps: 4_000_000,
      centerFileSizeBytes: 7_340_032,
      centerVmafMean: 95,
      centerVmafP5: 90,
      plQuality: 97,
      plBitrate: 100,
      plSpeed: 99,
      plTotal: 98,
      evidenceTier: 'LOW',
      memberBenchmarkRunIds: ['run-workload-1'],
      contributingWorkloadIds: ['sports-action-960x540-24p'],
      recomputationSpec: {
        protocolVersion: '7.0',
        sourceSuiteVersion: 'encodingdb-test-suite-v1',
        workloadId: 'sports-action-960x540-24p',
        recipeFingerprint: 'recipe-fingerprint',
        environmentFingerprint: 'environment-fingerprint',
        formulaVersion: '7.0',
        scoreContextVersion: 'ctx-v1',
        qualityModelId: 'vmaf-v1-sdr-sd',
        scopeKey: 'workload:sports-action-960x540-24p',
        includedStatuses: ['accepted'],
        aggregatorVersion: 'pl-v7-derived-v1',
        selectedAnalysisIds: ['analysis-workload-1'],
        analysisWorkerVersions: ['authoritative-analysis/v1'],
      },
    }, {
      kind: 'GENERAL',
      scopeKey: 'general:encodingdb-test-suite-v1',
      benchmarkProtocolVersion: '7.0',
      sourceSuiteVersion: 'encodingdb-test-suite-v1',
      formulaVersion: '7.0',
      scoreContextVersion: 'ctx-v1',
      qualityModelId: 'vmaf-v1-sdr-sd',
      workloadId: 'general-suite:encodingdb-test-suite-v1',
      contentClass: null,
      recipeId: 'recipe-1',
      environmentId: 'env-1',
      acceptedRunCount: 1,
      suspectRunCount: 0,
      rejectedRunCount: 0,
      repetitionCount: 1,
      centerEncodeFps: null,
      centerRealTimeRatio: null,
      centerVideoBitrateBps: null,
      centerFileSizeBytes: null,
      centerVmafMean: null,
      centerVmafP5: null,
      plQuality: null,
      plBitrate: null,
      plSpeed: null,
      plTotal: 98,
      evidenceTier: 'LOW',
      memberBenchmarkRunIds: ['run-workload-1'],
      contributingWorkloadIds: ['sports-action-960x540-24p'],
      recomputationSpec: {
        protocolVersion: '7.0',
        sourceSuiteVersion: 'encodingdb-test-suite-v1',
        workloadId: 'general-suite:encodingdb-test-suite-v1',
        recipeFingerprint: 'recipe-fingerprint',
        environmentFingerprint: 'environment-fingerprint',
        formulaVersion: '7.0',
        scoreContextVersion: 'ctx-v1',
        qualityModelId: 'vmaf-v1-sdr-sd',
        scopeKey: 'general:encodingdb-test-suite-v1',
        includedStatuses: ['accepted'],
        aggregatorVersion: 'pl-v7-derived-v1',
        selectedAnalysisIds: ['analysis-workload-1'],
        analysisWorkerVersions: ['authoritative-analysis/v1'],
      },
    }],
  };
}

test('activation plan rejects the checked-in draft calibration for production activation', async () => {
  await assert.rejects(
    () => loadProductionActivationPlan({
      referenceContextPath: contextFixturePath.pathname,
      calibrationEvidencePath: draftCalibrationPath.pathname,
    }),
    /not ready for production freeze/,
  );
});

test('buildProductionEnvBindings emits hash-bound PL v7 env keys', () => {
  const bindings = buildProductionEnvBindings(
    productionContextFixture(),
    '/srv/encodingdb/server/config/reference-contexts/production-v7.json',
  );

  assert.equal(bindings.PL_V7_REFERENCE_CONTEXT_VERSION, productionContextFixture().contextVersion);
  assert.equal(bindings.PL_V7_REFERENCE_CONTEXT_PATH, '/srv/encodingdb/server/config/reference-contexts/production-v7.json');
  assert.equal(bindings.ALLOW_TEST_ONLY_REFERENCE_CONTEXTS, '0');
  assert.deepEqual(
    JSON.parse(bindings.PL_V7_REFERENCE_BITRATES_JSON),
    Object.fromEntries(productionContextFixture().workloads.map((workload) => [workload.workloadId, workload.workloadReferenceBitrateBps])),
  );
});

test('buildActivationPersistencePayloads uses exact analysis membership for workload and general derived results', () => {
  const payloads = buildActivationPersistencePayloads({
    benchmarkProtocolId: 'proto-1',
    evidence: activationEvidenceFixture(),
    recomputed: activationRecomputeFixture(),
    scoreContexts: [
      { id: 'score-workload', kind: 'WORKLOAD', workloadId: 'sports-action-960x540-24p' },
      { id: 'score-general', kind: 'GENERAL', workloadId: 'general-suite:encodingdb-test-suite-v1' },
    ],
  });

  assert.equal(payloads.length, 2);
  assert.equal(payloads[0].derivedResult.scoreContextId, 'score-workload');
  assert.deepEqual(payloads[0].members, [{ benchmarkRunId: 'run-workload-1', qualityAnalysisId: 'analysis-workload-1' }]);
  assert.equal(payloads[1].derivedResult.scoreContextId, 'score-general');
  assert.deepEqual(payloads[1].members, [{ benchmarkRunId: 'run-workload-1', qualityAnalysisId: 'analysis-workload-1' }]);
});

test('persistActivationState upserts score contexts and derived results idempotently', async () => {
  const stored = new Map();
  const modules = {
    async persistScoreContextsFromReferenceContext() {
      return [
        { id: 'score-workload', kind: 'WORKLOAD', workloadId: 'sports-action-960x540-24p' },
        { id: 'score-general', kind: 'GENERAL', workloadId: 'general-suite:encodingdb-test-suite-v1' },
      ];
    },
    async persistDerivedResultRecord(_client, derivedResult, members) {
      const key = `${derivedResult.kind}:${derivedResult.scoreContextId}:${derivedResult.scopeKey}`;
      const existing = stored.get(key);
      const id = existing?.id ?? `derived-${stored.size + 1}`;
      stored.set(key, { id, derivedResult, members });
      return id;
    },
  };

  const input = {
    modules,
    benchmarkProtocolId: 'proto-1',
    promotedContext: productionContextFixture(),
    evidence: activationEvidenceFixture(),
    recomputed: activationRecomputeFixture(),
  };

  const first = await persistActivationState({}, input);
  const second = await persistActivationState({}, input);

  assert.equal(first.scoreContexts.length, 2);
  assert.equal(first.derivedResults.length, 2);
  assert.equal(second.derivedResults.length, 2);
  assert.equal(stored.size, 2);
  assert.deepEqual(
    [...stored.values()].map((row) => row.members),
    [
      [{ benchmarkRunId: 'run-workload-1', qualityAnalysisId: 'analysis-workload-1' }],
      [{ benchmarkRunId: 'run-workload-1', qualityAnalysisId: 'analysis-workload-1' }],
    ],
  );
});

test('validateProductionEnv rejects mismatched or unsafe production env contracts', () => {
  const context = productionContextFixture();
  const expected = buildReferenceContextBindings(context, '/srv/production-v7.json');
  const result = validateProductionEnv({
    env: {
      DATABASE_URL: 'postgresql://app:secret@db:5432/benchmarks',
      POSTGRES_USER: 'app',
      POSTGRES_PASSWORD: 'change_me',
      POSTGRES_DB: 'benchmarks',
      INGEST_MODE: 'signed',
      INGEST_HMAC_SECRET: '',
      ARTIFACT_UPLOAD_SECRET: '',
      ARTIFACT_STORAGE_ROOT: '/app/artifacts',
      TRUST_PROXY: '',
      CORS_ORIGIN: '*',
      INTERNAL_API_BASE_URL: 'https://api.example.com',
      APP_URL: 'https://app.example.com',
      ALLOW_TEST_ONLY_REFERENCE_CONTEXTS: '1',
      ...expected,
      PL_V7_REFERENCE_CONTEXT_VERSION: 'wrong-version',
    },
    referenceContext: context,
    referenceContextPath: '/srv/production-v7.json',
  });

  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes('INGEST_HMAC_SECRET')));
  assert.ok(result.errors.some((message) => message.includes('ARTIFACT_UPLOAD_SECRET')));
  assert.ok(result.errors.some((message) => message.includes('POSTGRES_PASSWORD')));
  assert.ok(result.errors.some((message) => message.includes('TRUST_PROXY')));
  assert.ok(result.errors.some((message) => message.includes('CORS_ORIGIN')));
  assert.ok(result.errors.some((message) => message.includes('ALLOW_TEST_ONLY_REFERENCE_CONTEXTS')));
  assert.ok(result.errors.some((message) => message.includes('PL_V7_REFERENCE_CONTEXT_VERSION')));
});

test('parseEnvText ignores comments and preserves explicit values', () => {
  const parsed = parseEnvText(`
# comment
APP_URL=https://app.example.com
TRUST_PROXY=1
PL_V7_REFERENCE_CONTEXT_VERSION=test-context
`);
  assert.equal(parsed.APP_URL, 'https://app.example.com');
  assert.equal(parsed.TRUST_PROXY, '1');
  assert.equal(parsed.PL_V7_REFERENCE_CONTEXT_VERSION, 'test-context');
});

test('production activation doc and deployment wiring mention env validation, activation, backup volume, and migration rehearsal', async () => {
  const [doc, deploy, compose, rootEnv, serverEnv, migrationScript, backupScript] = await Promise.all([
    readFile(path.resolve(testDir, '../../docs/PL_V7_PRODUCTION_ACTIVATION.md'), 'utf8'),
    readFile(path.resolve(testDir, '../../deploy.sh'), 'utf8'),
    readFile(path.resolve(testDir, '../../docker-compose.prod.yml'), 'utf8'),
    readFile(path.resolve(testDir, '../../env.example'), 'utf8'),
    readFile(path.resolve(testDir, '../env.example'), 'utf8'),
    readFile(path.resolve(testDir, '../../scripts/v7-migration-rehearsal.sh'), 'utf8'),
    readFile(path.resolve(testDir, '../../scripts/v7-backup.sh'), 'utf8'),
  ]);

  assert.match(doc, /activate-pl-v7-production\.mjs/);
  assert.match(doc, /validate-production-env\.mjs/);
  assert.match(doc, /encodingdb_prod_artifact_data/);
  assert.match(doc, /v7-migration-rehearsal\.sh/);
  assert.match(doc, /transactionally upserts the\s+matching `DerivedResult`/);
  assert.match(doc, /downtime/);
  assert.match(deploy, /validate-production-env\.mjs/);
  assert.match(deploy, /run_preflight_validation/);
  assert.match(deploy, /@prisma\/client/);
  assert.match(deploy, /\/test-videos/);
  assert.match(deploy, /\/corpus\?limit=1/);
  assert.match(deploy, /\/api\/corpus\?limit=1/);
  assert.match(deploy, /\/health\/v7-evidence/);
  assert.ok(deploy.indexOf('run_preflight_validation') < deploy.indexOf('git fetch --prune'));
  assert.match(compose, /name: encodingdb_prod_db_data/);
  assert.match(compose, /name: encodingdb_prod_artifact_data/);
  assert.match(rootEnv, /PL_V7_REFERENCE_CONTEXT_PATH=/);
  assert.match(rootEnv, /ARTIFACT_VOLUME_NAME=encodingdb_prod_artifact_data/);
  assert.match(serverEnv, /ALLOW_TEST_ONLY_REFERENCE_CONTEXTS=0/);
  assert.match(backupScript, /--compose-file/);
  assert.match(backupScript, /Quiescing writer services for backup consistency/);
  assert.match(backupScript, /Restarting quiesced writer services/);
  assert.match(migrationScript, /qualityAnalysisId backfill failed/);
  assert.match(migrationScript, /legacy Benchmark row did not survive migration/);
  assert.match(migrationScript, /npx tsx src\/index\.ts/);
  assert.match(migrationScript, /\/health\/ready/);
  assert.match(migrationScript, /\/query\?limit=1/);
  assert.match(migrationScript, /\/corpus\?limit=1/);
});

test('activation plan loader accepts repository-relative temp file paths', async () => {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-prod-ops-'));
  const contextCopy = path.join(tempDir, 'context.json');
  const draftCopy = path.join(tempDir, 'draft.json');
  await writeFile(contextCopy, readFileSync(contextFixturePath, 'utf8'));
  await writeFile(draftCopy, readFileSync(draftCalibrationPath, 'utf8'));

  await assert.rejects(
    () => loadProductionActivationPlan({
      referenceContextPath: contextCopy,
      calibrationEvidencePath: draftCopy,
    }),
    /not ready for production freeze/,
  );
});
