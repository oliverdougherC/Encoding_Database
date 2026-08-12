import path from 'node:path';
import { mkdir, readdir, stat, statfs } from 'node:fs/promises';

type CountRow = { storageState?: string; status?: string; _count: { _all: number } };

export type V7EvidenceHealthSnapshot = {
  capturedAt: string;
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
    completedLatencySeconds: { sampleCount: number; p50: number | null; p95: number | null };
  };
  storage: {
    rootAvailable: boolean;
    trackedBytes: number;
    quotaBytes: number | null;
    availableBytes: number | null;
    freeBytes: number | null;
  };
  staging: { entryCount: number; staleEntryCount: number; oldestSeconds: number | null };
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
  let names: string[] = [];
  try { names = await readdir(stagingRoot); } catch { return { entryCount: 0, staleEntryCount: 0, oldestSeconds: null }; }
  const ages = await Promise.all(names.map(async (name) => {
    try { return secondsSince((await stat(path.join(stagingRoot, name))).mtime, now); } catch { return null; }
  }));
  const present = ages.filter((age): age is number => age != null);
  return {
    entryCount: names.length,
    staleEntryCount: present.filter((age) => age >= staleSeconds).length,
    oldestSeconds: present.length ? Math.max(...present) : null,
  };
}

async function countMissingRetainedObjects(rootDir: string, artifacts: Array<{ storageKey: string | null }>): Promise<number> {
  const resolvedRoot = path.resolve(rootDir);
  let missing = 0;
  for (const artifact of artifacts) {
    if (!artifact.storageKey) { missing += 1; continue; }
    const objectPath = path.resolve(resolvedRoot, artifact.storageKey);
    if (objectPath !== resolvedRoot && !objectPath.startsWith(`${resolvedRoot}${path.sep}`)) { missing += 1; continue; }
    try { await stat(objectPath); } catch { missing += 1; }
  }
  return missing;
}

async function inspectStorage(rootDir: string): Promise<{ rootAvailable: boolean; availableBytes: number | null; freeBytes: number | null }> {
  try {
    await mkdir(rootDir, { recursive: true });
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
  if (snapshot.thresholds.storageQuotaBytes != null && snapshot.storage.trackedBytes > snapshot.thresholds.storageQuotaBytes) reasons.push('storage_quota_exceeded');
  if (snapshot.storage.availableBytes != null && snapshot.storage.availableBytes < snapshot.thresholds.storageReserveBytes) reasons.push('storage_reserve_exhausted');
  if (snapshot.staging.staleEntryCount > 0) reasons.push('orphan_staging_entries');
  if (snapshot.derivations.unresolvedSelectedAnalyses > 0) reasons.push('unresolved_derived_members');
  return { status: reasons.length ? 'degraded' : 'ok', reasons, ...snapshot };
}

export async function collectV7EvidenceHealth(prisma: any, options: {
  storageRoot: string;
  now?: Date;
  pendingUploadSeconds?: number;
  pendingAnalysisSeconds?: number;
  orphanStagingSeconds?: number;
  storageQuotaBytes?: number | null;
  storageReserveBytes?: number;
}) {
  const now = options.now ?? new Date();
  const thresholds = {
    pendingUploadSeconds: options.pendingUploadSeconds ?? 900,
    pendingAnalysisSeconds: options.pendingAnalysisSeconds ?? 1800,
    orphanStagingSeconds: options.orphanStagingSeconds ?? 3600,
    storageQuotaBytes: options.storageQuotaBytes ?? null,
    storageReserveBytes: options.storageReserveBytes ?? 512 * 1024 * 1024,
  };
  const [artifactCounts, analysisCounts, oldestPendingArtifact, oldestPendingAnalysis, retainedArtifacts, completedAnalyses, members, staging, trackedBytes, storage] = await Promise.all([
    prisma.artifact.groupBy({ by: ['storageState'], _count: { _all: true } }),
    prisma.qualityAnalysis.groupBy({ by: ['status'], _count: { _all: true } }),
    prisma.artifact.findFirst({ where: { storageState: 'PENDING' }, orderBy: { createdAt: 'asc' }, select: { createdAt: true } }),
    prisma.qualityAnalysis.findFirst({ where: { status: 'PENDING' }, orderBy: { createdAt: 'asc' }, select: { createdAt: true } }),
    prisma.artifact.findMany({ where: { storageState: { in: ['RETAINED', 'VERIFIED'] } }, select: { storageKey: true } }),
    prisma.qualityAnalysis.findMany({
      where: { status: 'COMPLETE', artifact: { uploadedAt: { not: null } } },
      select: { createdAt: true, artifact: { select: { uploadedAt: true } } },
      take: 1000,
      orderBy: { createdAt: 'desc' },
    }),
    prisma.derivedResultMember.findMany({ select: { qualityAnalysis: { select: { id: true, artifactId: true } } } }),
    inspectStaging(options.storageRoot, now, thresholds.orphanStagingSeconds),
    prisma.artifact.aggregate({
      where: {
        storageState: { in: ['UPLOADED', 'VERIFIED', 'RETAINED'] },
        byteSize: { not: null },
      },
      _sum: { byteSize: true },
    }),
    inspectStorage(options.storageRoot),
  ]);
  const latencies = completedAnalyses.flatMap((analysis: any) => {
    const uploadedAt = analysis.artifact?.uploadedAt;
    return uploadedAt ? [Math.max(0, (analysis.createdAt.getTime() - uploadedAt.getTime()) / 1000)] : [];
  });
  const snapshot: V7EvidenceHealthSnapshot = {
    capturedAt: now.toISOString(),
    thresholds,
    artifacts: {
      byState: counts(artifactCounts, 'storageState'),
      pendingOldestSeconds: secondsSince(oldestPendingArtifact?.createdAt, now),
      missingRetainedObjects: await countMissingRetainedObjects(options.storageRoot, retainedArtifacts),
    },
    analyses: {
      byStatus: counts(analysisCounts, 'status'),
      pendingOldestSeconds: secondsSince(oldestPendingAnalysis?.createdAt, now),
      completedLatencySeconds: { sampleCount: latencies.length, p50: percentile(latencies, 0.5), p95: percentile(latencies, 0.95) },
    },
    storage: {
      rootAvailable: storage.rootAvailable,
      trackedBytes: trackedBytes._sum.byteSize ?? 0,
      quotaBytes: thresholds.storageQuotaBytes,
      availableBytes: storage.availableBytes,
      freeBytes: storage.freeBytes,
    },
    staging,
    derivations: {
      unresolvedSelectedAnalyses: members.filter((member: any) => !member.qualityAnalysis?.id || !member.qualityAnalysis?.artifactId).length,
    },
  };
  return evaluateV7EvidenceHealth(snapshot);
}
