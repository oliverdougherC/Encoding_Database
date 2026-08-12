import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { validateCertificationSnapshot } from '../scripts/verify-v7-e2e.mjs';

function run(id, encoder, environmentId) {
  return {
    id,
    status: 'ACCEPTED',
    environmentId,
    recipe: { encoderImplementation: encoder },
    artifacts: [{ id: `artifact-${id}`, role: 'ENCODED', storageState: 'RETAINED', sha256: 'a'.repeat(64), byteSize: 42 }],
    qualityAnalyses: [{
      id: `analysis-${id}`,
      status: 'COMPLETE',
      analysisWorkerVersion: 'authoritative-analysis/v1',
      analysisProvenance: {
        pipelineVersion: 'encodingdb-artifact-pipeline/v1',
        contractVersion: 'encodingdb-quality-analysis/v1',
        modelSha256: 'b'.repeat(64),
        referencePath: '/retained/reference.mkv',
      },
      vmafDistribution: { frameCount: 72 },
      vmafMean: 95,
      vmafP5: 91,
      videoBitrateBps: 2_000_000,
    }],
    derivedMembers: [{ derivedResultId: `derived-${id}`, derivedResult: { acceptedRunCount: 2 } }],
  };
}

function validSnapshot() {
  return {
    runs: [
      run('software-1', 'libx264', 'env-software'),
      run('software-2', 'libx264', 'env-software'),
      run('hardware-1', 'videotoolbox', 'env-hardware'),
      run('hardware-2', 'videotoolbox', 'env-hardware'),
    ],
    serverAnalyticsScopes: [
      { ok: true, sha256: 'soft', rowCount: 1, encoderNames: ['libx264'] },
      { ok: true, sha256: 'hard', rowCount: 1, encoderNames: ['videotoolbox'] },
    ],
    frontendAnalyticsScopes: [
      { ok: true, sha256: 'soft', rowCount: 1, encoderNames: ['libx264'] },
      { ok: true, sha256: 'hard', rowCount: 1, encoderNames: ['videotoolbox'] },
    ],
    frontendPage: { ok: true },
  };
}

test('certification accepts a complete software and hardware authority chain', () => {
  const paths = validateCertificationSnapshot(validSnapshot(), ['libx264', 'videotoolbox']);
  assert.equal(paths.length, 2);
  assert.deepEqual(paths.map((path) => path.kind), ['software', 'hardware']);
});

test('certification rejects client/server evidence without authoritative analysis', () => {
  const snapshot = validSnapshot();
  snapshot.runs[0].qualityAnalyses[0].analysisProvenance.pipelineVersion = 'client-local';
  assert.throws(
    () => validateCertificationSnapshot(snapshot, ['libx264', 'videotoolbox']),
    /lacks authoritative server provenance/,
  );
});

test('certification rejects a hardware path that never reached aggregation', () => {
  const snapshot = validSnapshot();
  snapshot.runs[2].derivedMembers = [];
  assert.throws(
    () => validateCertificationSnapshot(snapshot, ['libx264', 'videotoolbox']),
    /did not reach PL aggregation/,
  );
});

test('certification rejects frontend data that differs from the server', () => {
  const snapshot = validSnapshot();
  snapshot.frontendAnalyticsScopes[0].sha256 = 'different';
  assert.throws(
    () => validateCertificationSnapshot(snapshot, ['libx264', 'videotoolbox']),
    /differs from the authoritative server response/,
  );
});

test('certificate checksum manifest cannot hash itself', async () => {
  const script = await readFile(new URL('../../scripts/certify-v7-e2e.sh', import.meta.url), 'utf8');
  assert.match(script, /! -name SHA256SUMS/);
  assert.doesNotMatch(script, /-print0[^\n]*\|[^\n]*>"\$RUN_DIR\/SHA256SUMS"/);
});

test('certificate records explicit native rate-control settings', async () => {
  const script = await readFile(new URL('../../scripts/certify-v7-e2e.sh', import.meta.url), 'utf8');
  assert.match(script, /--software-crf/);
  assert.match(script, /--hardware-target-bitrate-kbps/);
  assert.match(script, /"softwareRateControl"/);
  assert.match(script, /"hardwareRateControl"/);
});
