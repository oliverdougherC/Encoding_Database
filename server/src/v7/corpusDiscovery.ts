import { createHash } from 'node:crypto';
import { Prisma, type PrismaClient } from '@prisma/client';
import { hardwareEncoderPredicate } from './corpusQuery.js';

export const MAX_DISCOVERY_ITEMS = 500;
export type DiscoveryKind = 'hardware' | 'encoders';
type DiscoveryFilters = Partial<Record<'cpu' | 'gpu' | 'search' | 'preset' | 'encoderType' | 'workloadId' | 'environmentId' | 'environmentFingerprint', string>>;
const FILTER_NAMES = new Set(['cpu', 'gpu', 'search', 'preset', 'encoderType', 'workloadId', 'environmentId', 'environmentFingerprint']);

export class DiscoveryQueryError extends Error {}

/** Coverage has no implicit scoring/workload/sample threshold. Unsupported scopes fail explicitly. */
export function parseDiscoveryFilters(query: Record<string, unknown>): DiscoveryFilters {
  const result: DiscoveryFilters = {};
  for (const [key, value] of Object.entries(query)) {
    if (key === 'mode' && value === 'coverage') continue;
    if (!FILTER_NAMES.has(key) || typeof value !== 'string' || value.length > 200) {
      throw new DiscoveryQueryError('Invalid coverage filter');
    }
    const normalized = value.trim();
    if (!normalized) continue;
    if (key === 'encoderType' && !['hardware', 'software'].includes(normalized)) {
      throw new DiscoveryQueryError('Invalid encoder type');
    }
    result[key as keyof DiscoveryFilters] = normalized;
  }
  return result;
}

/** Aggregate the complete durable corpus first; the limit caps entities, not source observations. */
export function buildCorpusDiscoverySql(kind: DiscoveryKind, filters: DiscoveryFilters) {
  const where: Prisma.Sql[] = [];
  for (const [key, column] of [['cpu', 'e."cpuModel"'], ['gpu', 'e."gpuModel"'], ['preset', 'p.preset']] as const) {
    if (filters[key]) where.push(Prisma.sql`${Prisma.raw(column)} ILIKE ${`%${filters[key]}%`}`);
  }
  for (const [key, column] of [['workloadId', 'g."workloadId"'], ['environmentId', 'g."environmentId"'], ['environmentFingerprint', 'e.fingerprint']] as const) {
    if (filters[key]) where.push(Prisma.sql`${Prisma.raw(column)} = ${filters[key]}`);
  }
  if (filters.search) {
    where.push(Prisma.sql`(${Prisma.join(['g."workloadId"', 'e."cpuModel"', 'e."gpuModel"', 'e."osName"', 'e."osVersion"', 'p."encoderImplementation"', 'p."codecFamily"', 'p.preset']
      .map(column => Prisma.sql`${Prisma.raw(column)} ILIKE ${`%${filters.search}%`}`), ' OR ')})`);
  }
  if (filters.encoderType) {
    const hardware = hardwareEncoderPredicate(Prisma.sql`p."encoderImplementation"`);
    where.push(filters.encoderType === 'hardware' ? Prisma.sql`(${hardware})` : Prisma.sql`NOT (${hardware})`);
  }
  const identity = kind === 'hardware'
    ? Prisma.sql`e."cpuModel", coalesce(e."gpuModel", '')`
    : Prisma.sql`p."encoderImplementation", p."codecFamily"`;
  const fields = kind === 'hardware'
    ? Prisma.sql`e."cpuModel", coalesce(e."gpuModel", '') AS "gpuModel", count(DISTINCT p."encoderImplementation") AS "encoderCount", array_agg(DISTINCT p."codecFamily" ORDER BY p."codecFamily") AS "codecFamilies"`
    : Prisma.sql`p."encoderImplementation" AS "encoderName", p."codecFamily"`;
  return Prisma.sql`SELECT ${fields}, sum(g.accepted)::bigint AS "acceptedCount", sum(g.suspect)::bigint AS "suspectCount", count(*) AS "configurationCount"
    FROM "PublicCorpusGroup" g
    JOIN "BenchmarkProtocol" b ON b.id = g."benchmarkProtocolId"
    JOIN "Environment" e ON e.id = g."environmentId"
    JOIN "Recipe" p ON p.id = g."recipeId"
    WHERE b.state = 'ACTIVE' AND (g.accepted > 0 OR g.suspect > 0)
      ${where.length ? Prisma.sql`AND ${Prisma.join(where, ' AND ')}` : Prisma.empty}
    GROUP BY ${identity} ORDER BY ${identity} LIMIT ${MAX_DISCOVERY_ITEMS + 1}`;
}

type CoverageRecord = {
  cpuModel?: string; gpuModel?: string; encoderName?: string; codecFamily?: string;
  encoderCount?: bigint; codecFamilies?: string[];
  acceptedCount: bigint; suspectCount: bigint; configurationCount: bigint;
};

function count(value: bigint): number {
  const result = Number(value);
  if (!Number.isSafeInteger(result) || result < 0) throw new Error('Corpus coverage count is outside the supported range');
  return result;
}

export async function loadCorpusDiscovery(prisma: PrismaClient, kind: DiscoveryKind, filters: DiscoveryFilters) {
  // No analytics cache: a newly rejected/reviewed sample must not retain stale accepted coverage.
  const rows = await prisma.$transaction(async tx => {
    await tx.$executeRaw`SELECT set_config('statement_timeout', '5000', true), set_config('jit', 'off', true), set_config('max_parallel_workers_per_gather', '0', true)`;
    const [state] = await tx.$queryRaw<Array<{ pending: boolean }>>`SELECT EXISTS(SELECT 1 FROM "PublicCorpusDirtyGroup") AS pending`;
    if (state?.pending) throw Object.assign(new Error('Corpus summary rebuild pending'), { code: 'CORPUS_REBUILD_PENDING' });
    return tx.$queryRaw<CoverageRecord[]>(buildCorpusDiscoverySql(kind, filters));
  }, { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead, timeout: 10_000, maxWait: 5_000 });
  return {
    kind,
    items: rows.slice(0, MAX_DISCOVERY_ITEMS).map(row => {
      const identity = kind === 'hardware' ? [row.cpuModel, row.gpuModel] : [row.encoderName, row.codecFamily];
      const counts = { acceptedCount: count(row.acceptedCount), suspectCount: count(row.suspectCount), configurationCount: count(row.configurationCount) };
      const id = createHash('sha256').update(JSON.stringify([kind, ...identity])).digest('hex');
      return kind === 'hardware'
        ? { id, cpuModel: row.cpuModel!, gpuModel: row.gpuModel!, codecFamilies: row.codecFamilies!, encoderCount: count(row.encoderCount!), ...counts,
          browseFilters: { cpu: row.cpuModel!, ...(row.gpuModel ? { gpu: row.gpuModel } : {}) } }
        : { id, encoderName: row.encoderName!, codecFamily: row.codecFamily!, ...counts, browseFilters: { search: row.encoderName! } };
    }),
    truncated: rows.length > MAX_DISCOVERY_ITEMS,
  };
}
