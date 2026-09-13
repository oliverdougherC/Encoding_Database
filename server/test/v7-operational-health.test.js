import assert from 'node:assert/strict';
import test from 'node:test';
import { evaluateV7EvidenceHealth } from '../dist/v7/operationalHealth.js';

function snapshot() {
  return {
    capturedAt: '2026-08-12T00:00:00.000Z',
    thresholds: {
      pendingUploadSeconds: 900,
      pendingAnalysisSeconds: 1800,
      orphanStagingSeconds: 3600,
      storageQuotaBytes: null,
      storageReserveBytes: 1024,
    },
    artifacts: { byState: { RETAINED: 2 }, pendingOldestSeconds: null, missingRetainedObjects: 0 },
    analyses: {
      byStatus: { COMPLETE: 2 },
      pendingOldestSeconds: null,
      completedLatencySeconds: { sampleCount: 2, p50: 1.2, p95: 1.8 },
    },
    storage: {
      rootAvailable: true,
      trackedBytes: 2048,
      quotaBytes: null,
      availableBytes: 4096,
      freeBytes: 4096,
    },
    staging: { entryCount: 0, staleEntryCount: 0, oldestSeconds: null },
    derivations: { unresolvedSelectedAnalyses: 0 },
  };
}

test('v7 evidence health is healthy when retained objects and derivations resolve', () => {
  assert.deepEqual(evaluateV7EvidenceHealth(snapshot()).reasons, []);
  assert.equal(evaluateV7EvidenceHealth(snapshot()).status, 'ok');
});

test('v7 evidence health reports every release-blocking operational condition', () => {
  const value = snapshot();
  value.artifacts.pendingOldestSeconds = 901;
  value.artifacts.missingRetainedObjects = 1;
  value.analyses.byStatus.FAILED = 2;
  value.analyses.pendingOldestSeconds = 1801;
  value.storage.availableBytes = 512;
  value.storage.rootAvailable = false;
  value.staging.staleEntryCount = 1;
  value.derivations.unresolvedSelectedAnalyses = 1;
  assert.deepEqual(evaluateV7EvidenceHealth(value).reasons, [
    'artifact_root_unavailable',
    'stale_pending_uploads',
    'stale_pending_analyses',
    'failed_analyses',
    'missing_retained_objects',
    'storage_reserve_exhausted',
    'orphan_staging_entries',
    'unresolved_derived_members',
  ]);
});
