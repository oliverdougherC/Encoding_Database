import path from 'node:path';
import { opendir, lstat, stat, statfs } from 'node:fs/promises';

type CountRow = { storageState?: string; status?: string; _count: { _all: number } };

export type V7EvidenceHealthSnapshot = {
  capturedAt: string;
  freshness?: { cacheTtlSeconds: number; ageSeconds: number };
  integrityScan?: { batchSize: number; checkedThisBatch: number; checkedThisCycle: number; complete: boolean; cycleStartedAt: string; lastCompletedAt: string | null };
  capacity?: { reservedUploads?: number; unqueuedUploads?: number; analysisAdmissionUsed?: number; pendingUploads: number; pendingAnalyses: number; maxPendingUploads: number; maxPendingAnalyses: number; maxConcurrentUploads: number; maxConcurrentAnalyses: number; activeLeases: number; expiredLeases: number; retryDue: number };
  thresholds: {
    pendingUploadSeconds: number;
    pendingAnalysisSeconds: number;
    orphanStagingSeconds: number;
    storageQuotaBytes: number | null;
    storageReserveBytes: number;
  };
  artifacts: { byState: Record<string, number>; pendingOldestSeconds: number | null; missingRetainedObjects: number };
  analyses: {
    byStatus: Record<string, number>;
    pendingOldestSeconds: number | null;
    completedLatencySeconds: { sampleCount: number; p50: number | null; p95: number | null; terminalStatuses?: string[]; missingCompletionTimestamp?: number };
  };
  storage: {
    rootAvailable: boolean;
    trackedBytes: number;
    reservedBytes?: number;
    remainingQuotaBytes?: number | null;
    quotaBytes: number | null;
    availableBytes: number | null;
    freeBytes: number | null;
  };
  staging: { entryCount: number; staleEntryCount: number; oldestSeconds: number | null; truncated?: boolean; inspectedAt?: string };
  derivations: { unresolvedSelectedAnalyses: number };
};

function secondsSince(value: Date | null | undefined, now: Date): number | null {
  return value ? Math.max(0, (now.getTime() - value.getTime()) / 1000) : null;
}

function percentile(values: number[], fraction: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil(fraction * sorted.length) - 1] ?? null;
}

function counts(rows: CountRow[], key: 'storageState' | 'status'): Record<string, number> {
  return Object.fromEntries(rows.map((row) => [String(row[key]), row._count._all]));
}

async function inspectStaging(rootDir: string, now: Date, staleSeconds: number) {
  const stagingRoot = path.join(rootDir, '.staging');
  const ages: number[] = [];
  let truncated = false;
  try {
    // opendir streams directory entries; readdir would materialize the whole directory.
    const directory = await opendir(stagingRoot);
    for await (const entry of directory) {
      if (ages.length >= 256) { truncated = true; break; }
      try { ages.push(secondsSince((await stat(path.join(stagingRoot, entry.name))).mtime, now) ?? 0); }
      catch { ages.push(0); }
    }
  } catch (error: any) {
    if (error?.code !== 'ENOENT') throw error;
  }
  return {
    entryCount: ages.length,
    staleEntryCount: ages.filter((age) => age >= staleSeconds).length,
    oldestSeconds: ages.length ? Math.max(...ages) : null,
    truncated,
    inspectedAt: now.toISOString(),
  };
}

async function countMissingRetainedObjects(rootDir: string, artifacts: Array<{ storageKey: string | null }>): Promise<number> {
  const resolvedRoot = path.resolve(rootDir);
  let missing = 0;
  for (const artifact of artifacts) {
    if (!artifact.storageKey) { missing += 1; continue; }
    const objectPath = path.resolve(resolvedRoot, artifact.storageKey);
    if (objectPath !== resolvedRoot && !objectPath.startsWith(`${resolvedRoot}${path.sep}`)) { missing += 1; continue; }
    try { if (!(await lstat(objectPath)).isFile()) missing += 1; } catch { missing += 1; }
  }
  return missing;
}

async function inspectStorage(rootDir: string): Promise<{ rootAvailable: boolean; availableBytes: number | null; freeBytes: number | null }> {
  try {
    const root = await stat(rootDir);
    if (!root.isDirectory()) return { rootAvailable: false, availableBytes: null, freeBytes: null };
    const value = await statfs(rootDir);
    const blockSize = Number(value.bsize || 0);
    const availableBlocks = Number((value as { bavail?: number | bigint }).bavail ?? 0);
    const freeBlocks = Number((value as { bfree?: number | bigint }).bfree ?? 0);
    if (!Number.isFinite(blockSize) || blockSize <= 0) {
      return { rootAvailable: true, availableBytes: null, freeBytes: null };
    }
    return {
      rootAvailable: true,
      availableBytes: Math.trunc(availableBlocks * blockSize),
      freeBytes: Math.trunc(freeBlocks * blockSize),
    };
  } catch {
    return { rootAvailable: false, availableBytes: null, freeBytes: null };
  }
}

export function evaluateV7EvidenceHealth(snapshot: V7EvidenceHealthSnapshot) {
  const reasons: string[] = [];
  if (!snapshot.storage.rootAvailable) reasons.push('artifact_root_unavailable');
  if ((snapshot.artifacts.pendingOldestSeconds ?? 0) >= snapshot.thresholds.pendingUploadSeconds) reasons.push('stale_pending_uploads');
  if ((snapshot.analyses.pendingOldestSeconds ?? 0) >= snapshot.thresholds.pendingAnalysisSeconds) reasons.push('stale_pending_analyses');
  if ((snapshot.analyses.byStatus.FAILED ?? 0) > 0) reasons.push('failed_analyses');
  if (snapshot.artifacts.missingRetainedObjects > 0) reasons.push('missing_retained_objects');
  const reservedBytes = snapshot.storage.reservedBytes ?? 0;
  const committedBytes = snapshot.storage.trackedBytes + reservedBytes;
  if (snapshot.thresholds.storageQuotaBytes != null && committedBytes > snapshot.thresholds.storageQuotaBytes) reasons.push('storage_quota_exceeded');
  else if (snapshot.thresholds.storageQuotaBytes != null && committedBytes === snapshot.thresholds.storageQuotaBytes) reasons.push('storage_quota_exhausted');
  if (snapshot.storage.availableBytes != null && snapshot.storage.availableBytes - reservedBytes < snapshot.thresholds.storageReserveBytes) reasons.push('storage_reserve_exhausted');
  if (snapshot.staging.staleEntryCount > 0) reasons.push('orphan_staging_entries');
  if (snapshot.derivations.unresolvedSelectedAnalyses > 0) reasons.push('unresolved_derived_members');
  if (snapshot.staging.truncated) reasons.push('staging_scan_incomplete');
  if ((snapshot.capacity?.expiredLeases ?? 0) > 0) reasons.push('expired_analysis_leases');
  if (snapshot.capacity && (snapshot.capacity.reservedUploads ?? snapshot.capacity.pendingUploads) >= snapshot.capacity.maxPendingUploads) reasons.push('pending_upload_capacity_exhausted');
  if (snapshot.capacity && (snapshot.capacity.analysisAdmissionUsed ?? snapshot.capacity.pendingAnalyses) >= snapshot.capacity.maxPendingAnalyses) reasons.push('pending_analysis_capacity_exhausted');
  return { status: reasons.length ? 'degraded' : 'ok', reasons, ...snapshot };
}

export type V7HealthOptions = {
  storageRoot: string;
  now?: Date;
  pendingUploadSeconds?: number;
  pendingAnalysisSeconds?: number;
  orphanStagingSeconds?: number;
  storageQuotaBytes?: number | null;
  storageReserveBytes?: number;
  batchSize?: number;
  maxPendingUploads?: number;
  maxPendingAnalyses?: number;
  maxConcurrentUploads?: number;
  maxConcurrentAnalyses?: number;
};

type ScanState = { cursor?: string; checked: number; missing: number; previousMissing: number; startedAt: string; lastCompletedAt: string | null };
const scans = new WeakMap<object, ScanState>();

export async function collectV7EvidenceHealth(prisma: any, options: V7HealthOptions) {
  const now = options.now ?? new Date();
  const batchSize = Math.max(1, Math.min(1000, Math.trunc(options.batchSize ?? 256)));
  let scan = scans.get(prisma);
  if (!scan) { scan = { checked: 0, missing: 0, previousMissing: 0, startedAt: now.toISOString(), lastCompletedAt: null }; scans.set(prisma, scan); }
  const thresholds = {
    pendingUploadSeconds: options.pendingUploadSeconds ?? 900,
    pendingAnalysisSeconds: options.pendingAnalysisSeconds ?? 1800,
    orphanStagingSeconds: options.orphanStagingSeconds ?? 3600,
    storageQuotaBytes: options.storageQuotaBytes ?? null,
    storageReserveBytes: options.storageReserveBytes ?? 512 * 1024 * 1024,
  };
  const reserved = { storageState: 'PENDING', OR: [{ reservationExpiresAt: { gt: now } }, { uploadLeaseExpiresAt: { gt: now } }] };
  const [artifactCounts, analysisCounts, oldestPendingArtifact, oldestPendingAnalysis, retainedArtifacts, completedAnalyses, unresolvedMembers, staging, trackedBytes, storage, activeLeases, expiredLeases, retryDue, missingCompletionTimestamp, reservedUploads, unqueuedUploads, reservedTotal] = await Promise.all([
    prisma.artifact.groupBy({ by: ['storageState'], _count: { _all: true } }),
    prisma.qualityAnalysis.groupBy({ by: ['status'], _count: { _all: true } }),
    prisma.artifact.findFirst({ where: { storageState: 'PENDING' }, orderBy: { createdAt: 'asc' }, select: { createdAt: true } }),
    prisma.qualityAnalysis.findFirst({ where: { status: 'PENDING' }, orderBy: { createdAt: 'asc' }, select: { createdAt: true } }),
    prisma.artifact.findMany({ where: { storageState: { in: ['RETAINED', 'VERIFIED'] }, ...(scan.cursor ? { id: { gt: scan.cursor } } : {}) }, orderBy: { id: 'asc' }, take: batchSize, select: { id: true, storageKey: true } }),
    prisma.qualityAnalysis.findMany({
      where: { status: { in: ['COMPLETE', 'SUSPECT', 'REJECTED', 'FAILED'] }, completedAt: { not: null }, artifact: { uploadedAt: { not: null } } },
      select: { completedAt: true, startedAt: true, createdAt: true, status: true, artifact: { select: { uploadedAt: true } } },
      take: 1000,
      orderBy: { completedAt: 'desc' },
    }),
    prisma.derivedResultMember.count({ where: { qualityAnalysis: { artifactId: null } } }),
    inspectStaging(options.storageRoot, now, thresholds.orphanStagingSeconds),
    prisma.artifact.aggregate({
      where: {
        storageState: { in: ['UPLOADED', 'VERIFIED', 'RETAINED', 'REJECTED'] },
        byteSize: { not: null },
      },
      _sum: { byteSize: true },
    }),
    inspectStorage(options.storageRoot),
    prisma.qualityAnalysis.count({ where: { status: 'PENDING', leaseExpiresAt: { gt: now } } }),
    prisma.qualityAnalysis.count({ where: { status: 'PENDING', leaseExpiresAt: { lte: now } } }),
    prisma.qualityAnalysis.count({ where: { status: 'PENDING', nextRetryAt: { lte: now } } }),
    prisma.qualityAnalysis.count({ where: { status: { in: ['COMPLETE', 'SUSPECT', 'REJECTED', 'FAILED'] }, completedAt: null } }),
    prisma.artifact.count({ where: reserved }),
    prisma.artifact.count({ where: { storageState: 'UPLOADED', qualityAnalyses: { none: {} } } }),
    prisma.artifact.aggregate({ where: reserved, _sum: { byteSize: true } }),
  ]);
  const latencies = completedAnalyses.flatMap((analysis: any) => {
    const uploadedAt = analysis.artifact?.uploadedAt;
    return uploadedAt && analysis.completedAt ? [Math.max(0, (analysis.completedAt.getTime() - uploadedAt.getTime()) / 1000)] : [];
  });
  scan.missing += await countMissingRetainedObjects(options.storageRoot, retainedArtifacts);
  scan.checked += retainedArtifacts.length;
  const complete = retainedArtifacts.length < batchSize;
  const missing = complete ? scan.missing : Math.max(scan.previousMissing, scan.missing);
  if (complete) scan.lastCompletedAt = now.toISOString();
  const integrityScan = { batchSize, checkedThisBatch: retainedArtifacts.length, checkedThisCycle: scan.checked, complete, cycleStartedAt: scan.startedAt, lastCompletedAt: scan.lastCompletedAt };
  if (complete) { scan.previousMissing = scan.missing; scan.missing = 0; scan.checked = 0; delete scan.cursor; scan.startedAt = now.toISOString(); }
  else scan.cursor = retainedArtifacts.at(-1)?.id;
  const artifactStates = counts(artifactCounts, 'storageState');
  const analysisStatuses = counts(analysisCounts, 'status');
  const snapshot: V7EvidenceHealthSnapshot = {
    capturedAt: now.toISOString(),
    thresholds,
    integrityScan,
    capacity: { reservedUploads, unqueuedUploads, analysisAdmissionUsed: reservedUploads + unqueuedUploads + (analysisStatuses.PENDING ?? 0), pendingUploads: artifactStates.PENDING ?? 0, pendingAnalyses: analysisStatuses.PENDING ?? 0, maxPendingUploads: options.maxPendingUploads ?? 500, maxPendingAnalyses: options.maxPendingAnalyses ?? 500, maxConcurrentUploads: options.maxConcurrentUploads ?? 4, maxConcurrentAnalyses: options.maxConcurrentAnalyses ?? 2, activeLeases, expiredLeases, retryDue },
    artifacts: {
      byState: counts(artifactCounts, 'storageState'),
      pendingOldestSeconds: secondsSince(oldestPendingArtifact?.createdAt, now),
      missingRetainedObjects: missing,
    },
    analyses: {
      byStatus: counts(analysisCounts, 'status'),
      pendingOldestSeconds: secondsSince(oldestPendingAnalysis?.createdAt, now),
      completedLatencySeconds: { sampleCount: latencies.length, p50: percentile(latencies, 0.5), p95: percentile(latencies, 0.95), terminalStatuses: ['COMPLETE', 'SUSPECT', 'REJECTED', 'FAILED'], missingCompletionTimestamp },
    },
    storage: {
      rootAvailable: storage.rootAvailable,
      trackedBytes: trackedBytes._sum.byteSize ?? 0,
      reservedBytes: reservedTotal._sum.byteSize ?? 0,
      remainingQuotaBytes: thresholds.storageQuotaBytes == null ? null : Math.max(0, thresholds.storageQuotaBytes - (trackedBytes._sum.byteSize ?? 0) - (reservedTotal._sum.byteSize ?? 0)),
      quotaBytes: thresholds.storageQuotaBytes,
      availableBytes: storage.availableBytes,
      freeBytes: storage.freeBytes,
    },
    staging,
    derivations: {
      unresolvedSelectedAnalyses: unresolvedMembers,
    },
  };
  return evaluateV7EvidenceHealth(snapshot);
}

export class V7EvidenceHealthUnavailable extends Error {
  readonly failedAt = new Date().toISOString();
  readonly retryAt: string;
  constructor(ttlMs: number) {
    super('evidence_health_unavailable');
    this.retryAt = new Date(Date.now() + ttlMs).toISOString();
  }
}

/** One bounded refresh per process per interval, regardless of concurrent polling. */
export function createV7EvidenceHealthMonitor(prisma: any, options: V7HealthOptions, ttlMs = 30_000) {
  let cached: Awaited<ReturnType<typeof collectV7EvidenceHealth>> | undefined;
  let expiresAt = 0;
  let failure: unknown;
  let pending: Promise<Awaited<ReturnType<typeof collectV7EvidenceHealth>>> | undefined;
  return async () => {
    if (failure && Date.now() < expiresAt) throw failure;
    if (!cached || Date.now() >= expiresAt) {
      pending ??= collectV7EvidenceHealth(prisma, options).then((value) => {
        failure = undefined;
        cached = value;
        expiresAt = Date.now() + ttlMs;
        return value;
      }).catch((error: unknown) => {
        failure = new V7EvidenceHealthUnavailable(ttlMs); expiresAt = Date.now() + ttlMs; throw failure;
      }).finally(() => { pending = undefined; });
      await pending;
    }
    return { ...cached!, freshness: { cacheTtlSeconds: ttlMs / 1000, ageSeconds: Math.max(0, (Date.now() - Date.parse(cached!.capturedAt)) / 1000) } };
  };
}
