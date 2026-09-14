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

import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { collectV7EvidenceHealth, createV7EvidenceHealthMonitor } from '../dist/v7/operationalHealth.js';

function database(artifacts = []) {
  const calls = [];
  return {
    calls,
    artifact: {
      groupBy: async () => [{ storageState: 'RETAINED', _count: { _all: artifacts.length } }],
      findFirst: async () => null,
      findMany: async (query) => { calls.push(query); return artifacts.filter((row) => !query.where.id || row.id > query.where.id.gt).slice(0, query.take); },
      aggregate: async () => ({ _sum: { byteSize: 0 } }),
      count: async () => 0,
    },
    qualityAnalysis: {
      groupBy: async () => [{ status: 'SUSPECT', _count: { _all: 1 } }],
      findFirst: async () => null,
      findMany: async (query) => {
        assert.deepEqual(query.where.status.in, ['COMPLETE', 'SUSPECT', 'REJECTED', 'FAILED']);
        assert.equal(query.take, 1000);
        assert.equal(query.orderBy.completedAt, 'desc');
        return [{ status: 'SUSPECT', createdAt: new Date('2026-09-13T00:00:01Z'), completedAt: new Date('2026-09-13T00:20:00Z'), artifact: { uploadedAt: new Date('2026-09-13T00:00:00Z') } }];
      },
      count: async (query) => query.where.leaseExpiresAt?.lte ? 1 : 0,
    },
    derivedResultMember: { count: async () => 0 },
  };
}

test('health measures terminal completion (including SUSPECT), not enqueue time; reports expired leases', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'health-'));
  try {
    const value = await collectV7EvidenceHealth(database(), { storageRoot: root });
    assert.equal(value.analyses.completedLatencySeconds.p50, 1200);
    assert.equal(value.analyses.completedLatencySeconds.p95, 1200);
    assert.ok(value.reasons.includes('expired_analysis_leases'));
    assert.equal(value.integrityScan.complete, true);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('bounded integrity pages cover all objects and retain failures until a complete clean rescan', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'health-'));
  try {
    await writeFile(path.join(root, 'present'), 'ok');
    const db = database([{ id: 'a', storageKey: 'missing' }, { id: 'b', storageKey: 'present' }, { id: 'c', storageKey: 'present' }]);
    const options = { storageRoot: root, batchSize: 2 };
    let value = await collectV7EvidenceHealth(db, options);
    assert.equal(value.integrityScan.checkedThisBatch, 2);
    assert.equal(value.integrityScan.complete, false);
    assert.equal(value.artifacts.missingRetainedObjects, 1);
    value = await collectV7EvidenceHealth(db, options);
    assert.equal(value.integrityScan.checkedThisCycle, 3);
    assert.equal(value.integrityScan.complete, true);
    await writeFile(path.join(root, 'missing'), 'repaired');
    value = await collectV7EvidenceHealth(db, options);
    assert.equal(value.artifacts.missingRetainedObjects, 1);
    value = await collectV7EvidenceHealth(db, options);
    assert.equal(value.artifacts.missingRetainedObjects, 0);
    assert.ok(db.calls.every((query) => query.take === 2));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('25 simultaneous polls share one refresh and subsequent polls use timestamped cache', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'health-'));
  try {
    const db = database();
    const monitor = createV7EvidenceHealthMonitor(db, { storageRoot: root });
    const values = await Promise.all(Array.from({ length: 25 }, () => monitor()));
    await monitor();
    assert.equal(db.calls.length, 1);
    assert.ok(values.every((value) => value.capturedAt === values[0].capturedAt));
    assert.equal(values[0].freshness.cacheTtlSeconds, 30);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('failed refresh is also throttled, rather than retried by every request', async () => {
  const db = database();
  let calls = 0;
  db.artifact.groupBy = async () => { calls++; throw new Error('database unavailable'); };
  const monitor = createV7EvidenceHealthMonitor(db, { storageRoot: '/nonexistent' });
  await assert.rejects(monitor, (error) => error.message === 'evidence_health_unavailable' && Number.isFinite(Date.parse(error.failedAt)) && Number.isFinite(Date.parse(error.retryAt)));
  await assert.rejects(monitor, (error) => error.message === 'evidence_health_unavailable' && Number.isFinite(Date.parse(error.failedAt)) && Number.isFinite(Date.parse(error.retryAt)));
  assert.equal(calls, 1);
});

test('staging scans stop at their explicit bound; missing roots remain unavailable', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'health-'));
  try {
    await mkdir(path.join(root, '.staging'));
    await Promise.all(Array.from({ length: 260 }, (_, i) => writeFile(path.join(root, '.staging', String(i)), '')));
    const value = await collectV7EvidenceHealth(database(), { storageRoot: root, storageReserveBytes: Number.MAX_SAFE_INTEGER });
    assert.equal(value.staging.entryCount, 256);
    assert.equal(value.staging.truncated, true);
    assert.ok(value.reasons.includes('storage_reserve_exhausted'));
    assert.ok(value.reasons.includes('staging_scan_incomplete'));
    const absent = await collectV7EvidenceHealth(database(), { storageRoot: path.join(root, 'absent') });
    assert.equal(absent.storage.rootAvailable, false);
  } finally { await rm(root, { recursive: true, force: true }); }
});


test('health exposes reservations which exhaust admission before an upload or analysis exists', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'health-reservations-'));
  try {
    const db = database();
    db.artifact.count = async () => 1;
    db.artifact.aggregate = async (query) => ({ _sum: { byteSize: query.where.storageState === 'PENDING' ? 900 : 100 } });
    const value = await collectV7EvidenceHealth(db, { storageRoot: root, storageQuotaBytes: 1000, maxPendingAnalyses: 2 });
    assert.equal(value.storage.reservedBytes, 900);
    assert.equal(value.storage.remainingQuotaBytes, 0);
    assert.equal(value.capacity.analysisAdmissionUsed, 2);
    assert.ok(value.reasons.includes('storage_quota_exhausted'));
    assert.ok(value.reasons.includes('pending_analysis_capacity_exhausted'));
  } finally { await rm(root, { recursive: true, force: true }); }
});
