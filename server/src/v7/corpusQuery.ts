import { Prisma, type PrismaClient } from '@prisma/client';
import { measurementGroupStateHashSql, measurementGroupScopeForDerived } from './measurementGroup.js';
import { DEFAULT_ANALYZER_VERSION } from './artifacts.js';
import { buildPublicCorpusRows, getPublicReferenceContextVersions, type PublicCorpusRow } from './corpus.js';

/** Hard bounds apply to detail, list and hydration, irrespective of HTTP input. */
export const MAX_PUBLIC_CORPUS_PAGE_SIZE = 100;
const HARDWARE_SUFFIXES = ['_videotoolbox', '_nvenc', '_qsv', '_amf', '_vaapi', '_v4l2m2m', '_omx'];
type CorpusQuery = Record<string, string | undefined>;
type GroupSummary = {
  id: string; runId: string; artifactId: string; analysisId: string; derivedId: string | null; verifiedDerivedId?: string | null;
  accepted: number; suspect: number; repetitions: number; independentSources: number; machines: number;
  fps: number | null; sourceFps: number | null; vmaf: number | null; vmafP5: number | null;
  videoBitrateBps: number | null; fileSizeBytes: number | null; artifactState: PublicCorpusRow['status']['artifactState'];
};
type PageSummary = { totalCount: bigint; groups: GroupSummary[] };

function containsPattern(value: string): string {
  // Match the existing Prisma contains/ILIKE wildcard semantics.
  return `%${value}%`;
}

/** All user values are SQL parameters; the only SQL identifiers below are fixed whitelists. */
export function buildPublicCorpusPageSql(query: CorpusQuery, take: number, skip: number, contexts: readonly string[], id?: string) {
  const filters: Prisma.Sql[] = [];
  for (const [key, column] of [
    ['cpu', 'e."cpuModel"'], ['gpu', 'e."gpuModel"'], ['preset', 'p."preset"'],
  ] as const) {
    if (query[key]?.trim()) filters.push(Prisma.sql`${Prisma.raw(column)} ILIKE ${containsPattern(query[key]!.trim())}`);
  }
  if (query.encoderType === 'hardware' || query.encoderType === 'software') {
    const hardware = Prisma.join(HARDWARE_SUFFIXES.map(s => Prisma.sql`right(p."encoderImplementation", ${s.length}::int) = ${s}`), ' OR ');
    filters.push(query.encoderType === 'hardware' ? Prisma.sql`(${hardware})` : Prisma.sql`NOT (${hardware})`);
  }
  if (query.search?.trim()) {
    const value = containsPattern(query.search.trim());
    filters.push(Prisma.sql`(${Prisma.join([
      'g."workloadId"', 'e."cpuModel"', 'e."gpuModel"', 'e."osName"', 'e."osVersion"',
      'p."encoderImplementation"', 'p."codecFamily"', 'p."preset"',
    ].map(column => Prisma.sql`${Prisma.raw(column)} ILIKE ${value}`), ' OR ')})`);
  }
  if (id != null) filters.push(Prisma.sql`g.id = ${id}`);
  const filter = filters.length ? Prisma.sql`AND ${Prisma.join(filters, ' AND ')}` : Prisma.empty;
  const sorts: Record<string, string> = {
    cpuModel: '"cpuModel"', gpuModel: 'coalesce("gpuModel", \'\')', codec: '"encoderName"',
    preset: 'coalesce("preset", \'default\')', fps: '"displayFps"', vmaf: '"displayVmaf"',
    fileSizeBytes: 'round("displayFileSizeBytes"::numeric)', videoBitrateBps: '"displayVideoBitrateBps"', samples: 'accepted',
  };
  const sort = Prisma.raw(sorts[query.sort ?? ''] ?? '"createdAt"');
  const direction = Prisma.raw(query.dir === 'asc' ? 'ASC' : 'DESC');
  const pageSize = Math.max(1, Math.min(MAX_PUBLIC_CORPUS_PAGE_SIZE, Math.floor(take) || 25));
  const offset = Math.max(0, Math.min(Number.MAX_SAFE_INTEGER, Math.floor(skip) || 0));
  return Prisma.sql`
    WITH grouped AS MATERIALIZED (
      SELECT g.* FROM "PublicCorpusGroup" g
      JOIN "BenchmarkProtocol" b ON b.id = g."benchmarkProtocolId"
      JOIN "Environment" e ON e.id = g."environmentId"
      JOIN "Recipe" p ON p.id = g."recipeId"
      WHERE b.state = 'ACTIVE' ${filter}
    ), candidates AS MATERIALIZED (
      SELECT grouped.*, candidate.id AS "derivedId",
        CASE WHEN candidate."evidenceSummary"->'measurementGroupSnapshot' IS NOT NULL THEN candidate."centerEncodeFps" ELSE grouped.fps END AS "displayFps",
        CASE WHEN candidate."evidenceSummary"->'measurementGroupSnapshot' IS NOT NULL THEN candidate."centerVmafMean" ELSE grouped.vmaf END AS "displayVmaf",
        CASE WHEN candidate."evidenceSummary"->'measurementGroupSnapshot' IS NOT NULL THEN candidate."centerVideoBitrateBps" ELSE grouped."videoBitrateBps" END AS "displayVideoBitrateBps",
        CASE WHEN candidate."evidenceSummary"->'measurementGroupSnapshot' IS NOT NULL THEN candidate."centerFileSizeBytes" ELSE grouped."fileSizeBytes" END AS "displayFileSizeBytes"
      FROM grouped LEFT JOIN LATERAL (
        SELECT d.* FROM "DerivedResult" d JOIN "ScoreContext" c ON c.id = d."scoreContextId" JOIN "BenchmarkProtocol" b ON b.id = d."benchmarkProtocolId"
        WHERE d.kind = 'WORKLOAD' AND d."invalidatedAt" IS NULL AND d."plTotal" IS NOT NULL
          AND d."benchmarkProtocolId" = grouped."benchmarkProtocolId" AND d."workloadId" = grouped."workloadId" AND d."recipeId" = grouped."recipeId" AND d."environmentId" = grouped."environmentId"
          AND c."qualityModelId" = grouped."metricModelId" AND c."contextVersion" = ANY(${[...contexts]}::text[])
          AND (b."protocolVersion" <> '7.1' OR (d."evidenceSummary"->'measurementGroupSnapshot'->>'version' = 'measurement-group-state/v2'
            AND (d."evidenceSummary"->'measurementGroupSnapshot'->>'rawAcceptedCount')::int = grouped.accepted
            AND d."evidenceSummary"->'measurementGroupSnapshot'->>'rawAcceptedMembershipHash' = grouped."acceptedMembershipHash"
            AND EXISTS (SELECT 1 FROM "DerivedResultGroupDependency" dependency WHERE dependency."derivedResultId" = d.id)
            AND NOT EXISTS (SELECT 1 FROM "DerivedResultGroupDependency" dependency WHERE dependency."derivedResultId" = d.id AND dependency."invalidatedAt" IS NOT NULL)))
        ORDER BY d."createdAt" DESC, d.id DESC LIMIT 1
      ) candidate ON true
    ), page AS (
      SELECT * FROM candidates ORDER BY ${sort} ${direction} NULLS LAST, id ASC LIMIT ${pageSize} OFFSET ${offset}
    ), hydrated AS (
      SELECT page.*, d.id AS "verifiedDerivedId" FROM page LEFT JOIN LATERAL (
        SELECT d.id FROM "DerivedResult" d JOIN "ScoreContext" c ON c.id = d."scoreContextId" JOIN "BenchmarkProtocol" scoredProtocol ON scoredProtocol.id = d."benchmarkProtocolId"
        WHERE d.id = page."derivedId" AND d.kind = 'WORKLOAD' AND d."invalidatedAt" IS NULL AND d."benchmarkProtocolId" = page."benchmarkProtocolId"
          AND d."workloadId" = page."workloadId" AND d."recipeId" = page."recipeId" AND d."environmentId" = page."environmentId"
          AND c."qualityModelId" = page."metricModelId" AND c."contextVersion" = ANY(${[...contexts]}::text[])
        AND page.accepted > 0
          AND (
            (scoredProtocol."protocolVersion" <> '7.1'
              AND (SELECT count(*) FROM "DerivedResultMember" m WHERE m."derivedResultId" = d.id) = page.accepted
              AND (SELECT encode(sha256(convert_to(coalesce(jsonb_agg(m."qualityAnalysisId" ORDER BY m."qualityAnalysisId"), '[]'::jsonb)::text, 'UTF8')), 'hex') FROM "DerivedResultMember" m WHERE m."derivedResultId" = d.id) = page."acceptedMembershipHash")
            OR (scoredProtocol."protocolVersion" = '7.1'
              AND d."evidenceSummary"->'measurementGroupSnapshot'->>'version' = 'measurement-group-state/v2'
              AND (d."evidenceSummary"->'measurementGroupSnapshot'->>'rawAcceptedCount')::int = page.accepted
              AND d."evidenceSummary"->'measurementGroupSnapshot'->>'rawAcceptedMembershipHash' = page."acceptedMembershipHash"
              AND (d."evidenceSummary"->'measurementGroupSnapshot'->>'qualifiedCount')::int > 0
              AND (SELECT count(*) FROM "DerivedResultMember" m WHERE m."derivedResultId" = d.id) = (d."evidenceSummary"->'measurementGroupSnapshot'->>'qualifiedCount')::int
              AND (SELECT encode(sha256(convert_to(coalesce(jsonb_agg(m."qualityAnalysisId" ORDER BY m."qualityAnalysisId" COLLATE "C"), '[]'::jsonb)::text, 'UTF8')), 'hex') FROM "DerivedResultMember" m WHERE m."derivedResultId" = d.id) = d."evidenceSummary"->'measurementGroupSnapshot'->>'qualifiedMembershipHash'
              AND ${measurementGroupStateHashSql(measurementGroupScopeForDerived(Prisma.raw('d.id')))} = d."evidenceSummary"->'measurementGroupSnapshot'->>'stateHash')
          )
        ORDER BY d."createdAt" DESC, d.id DESC LIMIT 1
      ) d ON true
    )
    SELECT (SELECT count(*) FROM grouped) AS "totalCount",
      coalesce((SELECT jsonb_agg(to_jsonb(hydrated) ORDER BY ${sort} ${direction} NULLS LAST, id ASC) FROM hydrated), '[]'::jsonb) AS groups`;
}

export function buildPublicCorpusAggregationSql(filter: Prisma.Sql) {
  const median = (column: string) => {
    const value = Prisma.raw(column);
    return Prisma.sql`CASE WHEN bool_or(accepted) THEN
      percentile_cont(0.5) WITHIN GROUP (ORDER BY ${value}) FILTER (WHERE accepted AND ${value} > '-Infinity'::float8 AND ${value} < 'Infinity'::float8)
      ELSE percentile_cont(0.5) WITHIN GROUP (ORDER BY ${value}) FILTER (WHERE ${value} > '-Infinity'::float8 AND ${value} < 'Infinity'::float8) END`;
  };
  return Prisma.sql`
    WITH selected AS MATERIALIZED (
      SELECT r.id AS "runId", r."createdAt", r."benchmarkProtocolId", r."workloadId", r."recipeId", r."environmentId",
        a.id AS "analysisId", a."metricModelId", f.id AS "artifactId", f."storageState",
        concat_ws('::', r."benchmarkProtocolId", r."workloadId", r."recipeId", r."environmentId", a."metricModelId") AS id,
        concat_ws('::', r."benchmarkProtocolId", r."workloadId", r."recipeId", r."environmentId") AS "baseKey",
        e."cpuModel", e."gpuModel", p."encoderImplementation" AS "encoderName", p.preset,
        (coalesce(review.decision = 'EXPECTED', false) OR (r.status = 'ACCEPTED' AND a.status = 'COMPLETE')) AS accepted,
        coalesce(nullif(btrim(r."repetitionGroupId"), ''), r.id) AS repetition,
        nullif(btrim(r."physicalSourceId"), '') AS source,
        r."encodeFps" AS fps, r."sourceFps", a."vmafMean" AS vmaf, a."vmafP5", a."videoBitrateBps",
        coalesce(a."fileSizeBytes", f."byteSize")::float8 AS "fileSizeBytes"
      FROM "BenchmarkRun" r
      JOIN "BenchmarkProtocol" b ON b.id = r."benchmarkProtocolId"
      JOIN "Environment" e ON e.id = r."environmentId"
      JOIN "Recipe" p ON p.id = r."recipeId"
      JOIN "Artifact" f ON f."benchmarkRunId" = r.id AND f.role = 'ENCODED'
        AND f."storageState" IN ('VERIFIED', 'RETAINED')
      JOIN LATERAL (
        SELECT a.* FROM "QualityAnalysis" a WHERE a."benchmarkRunId" = r.id
          AND (a."analysisWorkerVersion" = b."metricWorkerVersion" OR a."analysisWorkerVersion" = ${DEFAULT_ANALYZER_VERSION}
            OR starts_with(a."analysisWorkerVersion", 'authoritative-analysis/'))
        ORDER BY a."createdAt" DESC, a.id DESC LIMIT 1
      ) a ON a."artifactId" = f.id
      LEFT JOIN LATERAL (
        SELECT v.decision FROM "EvidenceReview" v WHERE v."analysisId" = a.id
          AND v."benchmarkRunId" = r.id AND v."artifactId" = f.id AND v."artifactSha256" = f.sha256
          AND v."metricModelId" = a."metricModelId" AND v."analysisWorkerVersion" = a."analysisWorkerVersion"
        ORDER BY v."createdAt" DESC, v.id DESC LIMIT 1
      ) review ON true
      WHERE b.state = 'ACTIVE' AND r.status IN ('ACCEPTED', 'SUSPECT')
        AND a.status IN ('COMPLETE', 'SUSPECT')
        AND (review.decision IS NULL OR review.decision IN ('EXPECTED', 'REVOKE')) ${filter}
    ), grouped AS (
      SELECT id, min("baseKey") AS "baseKey", max("createdAt") AS "createdAt", min("cpuModel") AS "cpuModel", min("gpuModel") AS "gpuModel",
        min("encoderName") AS "encoderName", min(preset) AS preset,
        min("benchmarkProtocolId") AS "benchmarkProtocolId", min("workloadId") AS "workloadId",
        min("recipeId") AS "recipeId", min("environmentId") AS "environmentId", min("metricModelId") AS "metricModelId",
        (array_agg("runId" ORDER BY "createdAt" DESC, "runId" DESC))[1] AS "runId",
        (array_agg("artifactId" ORDER BY "createdAt" DESC, "runId" DESC))[1] AS "artifactId",
        (array_agg("analysisId" ORDER BY "createdAt" DESC, "runId" DESC))[1] AS "analysisId",
        count(*) FILTER (WHERE accepted)::int AS accepted, count(*) FILTER (WHERE NOT accepted)::int AS suspect,
        count(DISTINCT repetition)::int AS repetitions,
        CASE WHEN bool_or(accepted) THEN count(DISTINCT source) FILTER (WHERE accepted)::int ELSE count(DISTINCT source)::int END AS "independentSources", count(DISTINCT source)::int AS machines,
        CASE WHEN count(DISTINCT "storageState") > 1 THEN 'MIXED_VERIFIED_RETAINED'
          WHEN bool_or("storageState" = 'RETAINED') THEN 'RETAINED' ELSE 'VERIFIED' END AS "artifactState",
        ${median('fps')} AS fps, ${median('"sourceFps"')} AS "sourceFps", ${median('vmaf')} AS vmaf,
        ${median('"vmafP5"')} AS "vmafP5", ${median('"videoBitrateBps"')} AS "videoBitrateBps",
        ${median('"fileSizeBytes"')} AS "fileSizeBytes",
        encode(sha256(convert_to(coalesce(jsonb_agg("analysisId" ORDER BY "analysisId") FILTER (WHERE accepted), '[]'::jsonb)::text, 'UTF8')), 'hex') AS "acceptedMembershipHash"
      FROM selected GROUP BY id
    )`;
}

function applySummary(row: PublicCorpusRow, group: GroupSummary, scored?: { centerEncodeFps: number | null; centerRealTimeRatio: number | null; centerVmafMean: number | null; centerVmafP5: number | null; centerVideoBitrateBps: number | null; centerFileSizeBytes: number | null; evidenceSummary: unknown }): PublicCorpusRow {
  const stableBasis = scored && (scored.evidenceSummary as Record<string, unknown>)?.measurementGroupSnapshot != null;
  if (stableBasis) group = { ...group, fps: scored.centerEncodeFps, vmaf: scored.centerVmafMean, vmafP5: scored.centerVmafP5, videoBitrateBps: scored.centerVideoBitrateBps, fileSizeBytes: scored.centerFileSizeBytes };
  const sourceFps = group.sourceFps != null && group.sourceFps > 0 ? group.sourceFps : null;
  const realTimeRatio = group.fps != null && sourceFps != null ? group.fps / sourceFps : null;
  const fileSizeBytes = group.fileSizeBytes == null ? null : Math.round(group.fileSizeBytes);
  return {
    ...row, fps: group.fps, vmaf: group.vmaf, vmafP5: group.vmafP5, sourceFps, realTimeRatio,
    videoBitrateBps: group.videoBitrateBps, fileSizeBytes, samples: group.accepted,
    status: { ...row.status, artifactState: group.artifactState, centerBasis: stableBasis ? 'eligible-stable-groups' : group.accepted > 0 ? 'accepted' : 'suspect' },
    sampleCounts: { ...row.sampleCounts, accepted: group.accepted, suspect: group.suspect,
      repetitions: group.repetitions, independentSources: group.independentSources, machines: group.machines },
    performance: { encodeFps: group.fps, realTimeRatio },
    quality: { ...row.quality, vmafMean: group.vmaf, vmafP5: group.vmafP5 },
    bitrate: { ...row.bitrate, videoBitrateBps: group.videoBitrateBps, fileSizeBytes },
  };
}

type DirtyIdentity = { baseKey: string; benchmarkProtocolId: string; workloadId: string; recipeId: string; environmentId: string };
export async function refreshPublicCorpusGroups(prisma: PrismaClient, batchSize = 64): Promise<number> {
  return prisma.$transaction(async tx => {
    const [pending] = await tx.$queryRaw<Array<{ pending: boolean }>>`SELECT EXISTS(SELECT 1 FROM "PublicCorpusDirtyGroup") AS pending`;
    if (!pending?.pending) return 0;
    // Serialize the short bounded refresh across processes. Row locks preserve
    // invalidations from a writer that commits while its old group is rebuilt.
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(714556), set_config('jit', 'off', true), set_config('max_parallel_workers_per_gather', '0', true), set_config('statement_timeout', '15000', true)`;
    const identities = await tx.$queryRaw<DirtyIdentity[]>`SELECT * FROM "PublicCorpusDirtyGroup" ORDER BY "updatedAt", "baseKey" LIMIT ${Math.max(1, Math.min(256, batchSize))} FOR UPDATE`;
    if (!identities.length) return 0;
    const filter = Prisma.sql`AND (${Prisma.join(identities.map(g => Prisma.sql`(r."benchmarkProtocolId" = ${g.benchmarkProtocolId} AND r."workloadId" = ${g.workloadId} AND r."recipeId" = ${g.recipeId} AND r."environmentId" = ${g.environmentId})`), ' OR ')})`;
    const keys = identities.map(g => g.baseKey);
    await tx.$executeRaw`DELETE FROM "PublicCorpusGroup" WHERE "baseKey" = ANY(${keys}::text[])`;
    await tx.$executeRaw(Prisma.sql`${buildPublicCorpusAggregationSql(filter)} INSERT INTO "PublicCorpusGroup" SELECT * FROM grouped`);
    await tx.$executeRaw`DELETE FROM "PublicCorpusDirtyGroup" WHERE "baseKey" = ANY(${keys}::text[])`;
    return identities.length;
  }, { timeout: 30000, maxWait: 5000 });
}

/** Use on every deployed HTTP/worker process; DB coordination makes it safe. */
export function startPublicCorpusRefreshLoop(prisma: PrismaClient, onError: (error: unknown) => void = console.error) {
  let busy = false;
  const timer = setInterval(() => {
    if (busy) return;
    busy = true;
    void refreshPublicCorpusGroups(prisma, 128).catch(onError).finally(() => { busy = false; });
  }, 1000);
  timer.unref();
  return () => clearInterval(timer);
}

export async function loadPublicCorpusPage(prisma: PrismaClient, query: CorpusQuery, options: {
  take: number; skip?: number | undefined; id?: string; publicReferenceContextVersions?: ReadonlySet<string>;
}) {
  const versions = options.publicReferenceContextVersions ?? getPublicReferenceContextVersions();
  // Selection and bounded hydration share a snapshot: concurrent reviews, uploads
  // and reanalysis cannot splice incompatible member sets into one response.
  for (let attempt = 0; attempt < 3; attempt++) {
    await refreshPublicCorpusGroups(prisma);
    try {
    return await prisma.$transaction(async tx => {
    const [state] = await tx.$queryRaw<Array<{ pending: boolean }>>`SELECT EXISTS(SELECT 1 FROM "PublicCorpusDirtyGroup") AS pending`;
    if (state?.pending) throw Object.assign(new Error('Corpus summary rebuild pending'), { code: 'CORPUS_REBUILD_PENDING' });
    await tx.$executeRaw`SELECT set_config('statement_timeout', '15000', true), set_config('jit', 'off', true), set_config('max_parallel_workers_per_gather', '0', true)`;
    const [summary] = await tx.$queryRaw<PageSummary[]>(buildPublicCorpusPageSql(query, options.take, options.skip ?? 0, [...versions], options.id));
    if (!summary?.groups.length) return { rows: [], totalCount: Number(summary?.totalCount ?? 0) };
    const ids = summary.groups;
    const stale = ids.filter(group => group.derivedId && group.verifiedDerivedId !== group.derivedId).map(group => group.derivedId!);
    if (stale.length) throw Object.assign(new Error('Scoring group certificate changed; rebuild required'), { code: 'CORPUS_SCORE_REBUILD_PENDING', derivedIds: stale });
    const runs = await tx.benchmarkRun.findMany({
      where: { id: { in: ids.map(g => g.runId) } },
      include: { benchmarkProtocol: true, recipe: true, environment: true,
        artifacts: { where: { id: { in: ids.map(g => g.artifactId) } } },
        qualityAnalyses: { where: { id: { in: ids.map(g => g.analysisId) } } } },
    });
    const derivedResults = await tx.derivedResult.findMany({
      where: { id: { in: ids.flatMap(g => g.derivedId == null ? [] : [g.derivedId]) } },
      include: { benchmarkProtocol: true, recipe: true, environment: true, scoreContext: true },
    });
    const rows = new Map(buildPublicCorpusRows({ runs, derivedResults, publicReferenceContextVersions: versions }).map(row => [row.id, row]));
    return { rows: ids.map(group => {
      const row = rows.get(group.id);
      if (!row) throw new Error('Corpus snapshot hydration did not resolve its selected evidence');
      return applySummary(row, group, derivedResults.find(result => result.id === group.derivedId));
    }), totalCount: Number(summary.totalCount) };
  }, { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead, timeout: 30_000, maxWait: 5_000 });
    } catch (error) {
      if ((error as { code?: string }).code === 'CORPUS_SCORE_REBUILD_PENDING') {
        const ids = (error as { derivedIds: string[] }).derivedIds;
        await prisma.derivedResult.updateMany({ where: { id: { in: ids } }, data: { invalidatedAt: new Date(), invalidationReason: 'Measurement group state or scoring membership changed' } });
        const pending = await prisma.$queryRaw<Array<{ id: string }>>(Prisma.sql`SELECT min("qualityAnalysisId") AS id FROM "DerivedResultMember" WHERE "derivedResultId" = ANY(${ids}::text[]) GROUP BY "derivedResultId"`);
        await prisma.qualityAnalysis.updateMany({ where: { id: { in: pending.map(row => row.id) } }, data: { recomputePending: true } });
        if (attempt === 2) throw error;
      } else if ((error as { code?: string }).code !== 'CORPUS_REBUILD_PENDING' || attempt === 2) throw error;
    }
  }
  throw new Error('Corpus read attempts exhausted');
}

/** Resource exhaustion is recoverable backpressure, not a missing corpus. */
export function isPublicCorpusBusyError(error: unknown): boolean {
  if (error == null || typeof error !== 'object') return false;
  const value = error as { code?: string; meta?: { code?: string } };
  return ['P2024', 'P2028', 'CORPUS_REBUILD_PENDING', 'CORPUS_SCORE_REBUILD_PENDING'].includes(value.code ?? '')
    || ['57014', '53100', '53200', '53300'].includes(value.meta?.code ?? '');
}

export async function publicCorpusReadiness(prisma: PrismaClient) {
  const [state] = await prisma.$queryRaw<Array<{ pendingGroups: bigint; oldestDirtyAt: Date | null }>>`
    SELECT count(*) AS "pendingGroups", min("updatedAt") AS "oldestDirtyAt" FROM "PublicCorpusDirtyGroup"`;
  return { ready: Number(state?.pendingGroups ?? 0) === 0, pendingGroups: Number(state?.pendingGroups ?? 0), oldestDirtyAt: state?.oldestDirtyAt ?? null };
}
