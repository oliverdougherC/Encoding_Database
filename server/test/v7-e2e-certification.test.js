import assert from 'node:assert/strict';
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
    serverAnalytics: { ok: true, sha256: 'feed', rowCount: 2, encoderNames: ['videotoolbox', 'libx264'] },
    frontendAnalytics: { ok: true, sha256: 'feed', rowCount: 2, encoderNames: ['videotoolbox', 'libx264'] },
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
  snapshot.frontendAnalytics.sha256 = 'different';
  assert.throws(
    () => validateCertificationSnapshot(snapshot, ['libx264', 'videotoolbox']),
    /differs from the authoritative server response/,
  );
});
