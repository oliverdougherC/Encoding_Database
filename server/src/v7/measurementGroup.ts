import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { Prisma } from '@prisma/client';
import { z } from 'zod';
import { canonicalJsonString } from './persistence.js';
import { applyEffectiveReview } from './reviews.js';

export const MEASUREMENT_GROUP_STATE_VERSION = 'measurement-group-state/v3' as const;
export const MEASUREMENT_GROUP_SCHEMA_VERSION = 'encodingdb-measurement-group/v1' as const;
export const CANONICAL_MEASUREMENT_RULES = { minimumMeasuredRuns: 2, stabilityThresholdRatio: 0.03, maxAdaptiveRepeats: 2 } as const;
const receiptSchema = z.object({
  schemaVersion: z.literal(MEASUREMENT_GROUP_SCHEMA_VERSION),
  campaignId: z.string().min(1).max(200), repetitionGroupId: z.string().min(1).max(200), completed: z.literal(true),
  countedAttempts: z.array(z.object({ repetitionIndex: z.number().int().min(0), encodeWallTimeMs: z.number().positive().max(86_400_000) }).strict()).min(2).max(4),
}).strict().superRefine((value, context) => {
  if (value.countedAttempts.some((attempt, index) => index > 0 && attempt.repetitionIndex <= value.countedAttempts[index - 1]!.repetitionIndex)) context.addIssue({ code: 'custom', path: ['countedAttempts'], message: 'Counted repetition indices must be sorted and unique' });
});
export type MeasurementGroupReceipt = z.infer<typeof receiptSchema>;
export interface MeasurementGroupRun {
  id?: string; benchmarkProtocolId?: string; testClipId?: string; workloadId?: string | null; recipeId?: string; environmentId?: string;
  physicalSourceId?: string | null; campaignId?: string | null; repetitionGroupId?: string | null; repetitionIndex?: number | null;
  encodeWallTimeMs?: number | null; encodeTimerBoundary?: string | null; inputHash?: string | null;
  encodeFps?: number | null; sourceFps?: number | null; realTimeRatio?: number | null; sourceFrameCount?: number | null; encodedFrameCount?: number | null;
  status?: string; preRunEnvironmentCheck?: unknown; benchmarkProtocol?: any; testClip?: any; qualityAnalyses?: any[];
}
export interface MeasurementGroupEligibility {
  eligible: boolean; reason: string; expectedCount: number; observedCount: number;
  relativeSpread: number | null; threshold: number; memberRunIds: string[]; analysisIds: string[];
}
const object = (value: unknown): Record<string, unknown> | null => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
export function receiptFromRun(run: MeasurementGroupRun): unknown { return object(run.preRunEnvironmentCheck)?.measurementGroup; }
// Prisma serializes JSON (jsonb) floats as 15-significant-digit decimal text, so a
// receipt entry written as 1473.9108999999999 reads back as 1473.9109. Exact double or
// canonical-text equality then contradicts the byte-identical sealed receipt it was
// stored from. Receipt elapsed times are therefore compared with a tolerance far above
// that decimal round-trip error yet orders of magnitude below the difference between
// two genuine encoding attempts (milliseconds).
export function receiptWallTimesEqual(a: number, b: number): boolean {
  if (a === b) return true;
  return Math.abs(a - b) <= Math.max(1e-9, Math.min(Math.abs(a), Math.abs(b)) * 1e-12);
}
export function receiptsEquivalent(a: MeasurementGroupReceipt, b: MeasurementGroupReceipt): boolean {
  return a.schemaVersion === b.schemaVersion && a.campaignId === b.campaignId && a.repetitionGroupId === b.repetitionGroupId
    && a.completed === b.completed && a.countedAttempts.length === b.countedAttempts.length
    && a.countedAttempts.every((attempt, index) => attempt.repetitionIndex === b.countedAttempts[index]!.repetitionIndex
      && receiptWallTimesEqual(attempt.encodeWallTimeMs, b.countedAttempts[index]!.encodeWallTimeMs));
}
export function parseMeasurementGroupReceipt(value: unknown, run?: MeasurementGroupRun): MeasurementGroupReceipt | null {
  if (value == null) return null;
  const receipt = receiptSchema.parse(value);
  if (run && (receipt.campaignId !== run.campaignId || receipt.repetitionGroupId !== run.repetitionGroupId
    || !receipt.countedAttempts.some(attempt => attempt.repetitionIndex === run.repetitionIndex && receiptWallTimesEqual(attempt.encodeWallTimeMs, run.encodeWallTimeMs!)))) throw new Error('Measurement group receipt does not bind this exact run identity and elapsed time');
  return receipt;
}
export function measurementGroupKey(run: MeasurementGroupRun): string | null {
  if (!run.physicalSourceId || !run.campaignId || !run.repetitionGroupId) return null;
  return JSON.stringify([run.physicalSourceId, run.campaignId, run.repetitionGroupId]);
}
function timingMatches(run: MeasurementGroupRun): boolean {
  const clip = run.testClip;
  if (!clip || run.encodeTimerBoundary !== 'ffmpeg-process-v1' || run.inputHash !== clip.sha256 || run.sourceFrameCount !== clip.exactFrameCount || run.encodedFrameCount !== clip.exactFrameCount) return false;
  const fps = clip.frameRateNumerator / clip.frameRateDenominator;
  if (!Number.isInteger(clip.exactFrameCount) || clip.exactFrameCount <= 0 || !Number.isFinite(fps) || fps <= 0 || !Number.isFinite(clip.exactDurationSeconds) || clip.exactDurationSeconds <= 0 || Math.abs(clip.exactFrameCount / fps - clip.exactDurationSeconds) > 1e-6) return false;
  const ms = run.encodeWallTimeMs;
  if (!Number.isFinite(ms) || ms! <= 0 || ms! > 86_400_000 || !Number.isFinite(run.sourceFps) || Math.abs(run.sourceFps! - fps) > 1e-7) return false;
  return [[run.encodeFps, clip.exactFrameCount * 1000 / ms!], [run.realTimeRatio, clip.exactDurationSeconds * 1000 / ms!]].every(([value, expected]) => Number.isFinite(value) && value! > 0 && Math.abs(value! - expected!) <= Math.max(0.001, expected! * 0.002));
}
/** The members must be the complete persisted group, not a filtered frontier/page. */
export function evaluateMeasurementGroup(target: MeasurementGroupRun, members: readonly MeasurementGroupRun[], identity: MeasurementGroupAnalysisIdentity): MeasurementGroupEligibility {
  const result: MeasurementGroupEligibility = { eligible: false, reason: 'missing-receipt', expectedCount: 0, observedCount: members.length, relativeSpread: null,
    threshold: CANONICAL_MEASUREMENT_RULES.stabilityThresholdRatio, memberRunIds: [], analysisIds: [] };
  let receipt: MeasurementGroupReceipt | null;
  try { receipt = parseMeasurementGroupReceipt(receiptFromRun(target), target); } catch { return { ...result, reason: 'invalid-receipt' }; }
  if (!receipt || !measurementGroupKey(target)) return result;
  result.expectedCount = receipt.countedAttempts.length;
  const protocol = members.find(member => member.id === target.id)?.benchmarkProtocol ?? target.benchmarkProtocol;
  const rules = object(protocol?.canonicalRecipeRules);
  if (protocol?.protocolVersion !== '7.1' || Object.entries(CANONICAL_MEASUREMENT_RULES).some(([key, value]) => rules?.[key] !== value)) return { ...result, reason: 'incompatible-protocol' };
  if (members.length !== receipt.countedAttempts.length || !members.some(member => member.id === target.id)) return { ...result, reason: 'incomplete-or-extra-members' };
  const canonicalReceipt = canonicalJsonString(receipt as never);
  let worker: string | undefined = identity.analysisWorkerVersion;
  let workerBuild: string | undefined;
  const seen = new Set<number>();
  for (const member of members) {
    if (['benchmarkProtocolId', 'testClipId', 'workloadId', 'recipeId', 'environmentId', 'physicalSourceId', 'campaignId', 'repetitionGroupId'].some(key => (member as any)[key] !== (target as any)[key])) return { ...result, reason: 'mixed-group-identity' };
    let observed: MeasurementGroupReceipt | null;
    try { observed = parseMeasurementGroupReceipt(receiptFromRun(member), member); } catch { return { ...result, reason: 'inconsistent-receipt-or-timing' }; }
    if (!observed || canonicalJsonString(observed as never) !== canonicalReceipt || member.repetitionIndex == null || seen.has(member.repetitionIndex)) return { ...result, reason: 'inconsistent-receipt-or-members' };
    seen.add(member.repetitionIndex);
    const snapshot = object(object(member.preRunEnvironmentCheck)?.snapshot);
    const sources = typeof snapshot?.telemetry_sources === 'string' ? snapshot.telemetry_sources.split(',').map(source => source.trim()) : [];
    if (!sources.some(source => source === 'cpu_psutil_thread_window_v1' || source === 'cpu_psutil_blocking_window_v1')
      || typeof snapshot?.background_cpu_pct !== 'number' || !Number.isFinite(snapshot.background_cpu_pct)) return { ...result, reason: 'missing-corrected-background-observation' };
    if (!timingMatches(member)) return { ...result, reason: 'invalid-timing-tuple' };
    const latest = [...(member.qualityAnalyses ?? [])].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime() || b.id.localeCompare(a.id))[0];
    if (!latest || latest.metricModelId !== identity.metricModelId || (worker && latest.analysisWorkerVersion !== worker)) return { ...result, reason: 'missing-or-mixed-analysis' };
    worker ??= latest.analysisWorkerVersion;
    const build = object(latest.analysisProvenance)?.workerBuildFingerprint;
    if (typeof build !== 'string' || !/^[a-f0-9]{64}$/.test(build) || (workerBuild && build !== workerBuild)) return { ...result, reason: 'missing-or-mixed-worker-build' };
    workerBuild ??= build;
    const artifact = latest.artifact;
    if (!artifact || artifact.role !== 'ENCODED' || artifact.benchmarkRunId !== member.id || !/^[a-f0-9]{64}$/.test(artifact.sha256 ?? '') || !Number.isInteger(artifact.byteSize) || artifact.byteSize <= 0
      || !artifact.storageKey || !artifact.storageUrl || artifact.storageProvider !== 'localfs') return { ...result, reason: 'missing-retained-artifact' };
    if (!applyEffectiveReview({ runStatus: member.status!, analysisStatus: latest.status, artifactState: artifact.storageState, analysisId: latest.id, reviews: latest.evidenceReviews }).eligible) return { ...result, reason: 'ineligible-member' };
    result.memberRunIds.push(member.id!); result.analysisIds.push(latest.id);
  }
  const elapsed = members.map(member => member.encodeWallTimeMs!);
  const mean = elapsed.reduce((sum, value) => sum + value, 0) / elapsed.length;
  result.relativeSpread = (Math.max(...elapsed) - Math.min(...elapsed)) / mean;
  if (result.relativeSpread > result.threshold) return { ...result, reason: 'unstable-timing' };
  return { ...result, eligible: true, reason: 'complete-stable-retained-group' };
}
export interface MeasurementGroupAnalysisIdentity { metricModelId: string; analysisWorkerVersion?: string; verifyRetainedBytes?: boolean; storageRoot?: string; }
async function verifyGroupObjects(members: readonly MeasurementGroupRun[], rootDir: string, verified: Set<string>): Promise<void> {
  const root = await realpath(rootDir);
  for (const run of members) {
    const artifact = run.qualityAnalyses![0].artifact;
    const objectPath = await realpath(path.resolve(root, artifact.storageKey));
    if (!objectPath.startsWith(root + path.sep)) throw new Error('Group artifact escaped retained storage');
    const key = JSON.stringify([objectPath, artifact.sha256, artifact.byteSize]);
    if (verified.has(key)) continue;
    if ((await stat(objectPath)).size !== artifact.byteSize) throw new Error('Group artifact size mismatch');
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(objectPath)) hash.update(chunk);
    if (hash.digest('hex') !== artifact.sha256) throw new Error('Group artifact SHA mismatch');
    verified.add(key);
  }
}
export type MeasurementGroupClient = { benchmarkRun: { findMany: (args: any) => Promise<any[]> } };
export async function loadMeasurementGroupEligibility(client: MeasurementGroupClient, run: MeasurementGroupRun, identity: MeasurementGroupAnalysisIdentity, verifiedObjects = new Set<string>()): Promise<MeasurementGroupEligibility> {
  if (!measurementGroupKey(run) || receiptFromRun(run) == null) return evaluateMeasurementGroup(run, [], identity);
  const members = await client.benchmarkRun.findMany({ where: { physicalSourceId: run.physicalSourceId, campaignId: run.campaignId, repetitionGroupId: run.repetitionGroupId },
    include: { benchmarkProtocol: true, testClip: true, qualityAnalyses: { orderBy: [{ createdAt: 'desc' }, { id: 'desc' }], take: 1, include: { artifact: true, evidenceReviews: true } } },
    orderBy: [{ createdAt: 'asc' }, { id: 'asc' }], take: CANONICAL_MEASUREMENT_RULES.minimumMeasuredRuns + CANONICAL_MEASUREMENT_RULES.maxAdaptiveRepeats + 1 });
  const result = evaluateMeasurementGroup(run, members, identity);
  if (result.eligible && identity.verifyRetainedBytes) {
    try { await verifyGroupObjects(members, identity.storageRoot ?? process.env.ARTIFACT_STORAGE_ROOT ?? path.resolve(process.cwd(), '.artifacts'), verifiedObjects); }
    catch { return { ...result, eligible: false, reason: 'missing-or-corrupt-retained-group-object' }; }
  }
  return result;
}
/** Cache only for one bounded read/rebuild operation, never across reviews or uploads. */
export function createMeasurementGroupVerifier(client: MeasurementGroupClient, identity: MeasurementGroupAnalysisIdentity) {
  const groups = new Map<string, Promise<MeasurementGroupEligibility>>();
  const verifiedObjects = new Set<string>();
  return (run: MeasurementGroupRun): Promise<MeasurementGroupEligibility> => {
    const key = measurementGroupKey(run);
    if (!key) return Promise.resolve(evaluateMeasurementGroup(run, [], identity));
    let result = groups.get(key);
    if (!result) { result = loadMeasurementGroupEligibility(client, run, identity, verifiedObjects); groups.set(key, result); }
    return result;
  };
}

/** Hash every complete row before ordered aggregation, bounding the aggregate state to IDs/digests. */
export function measurementGroupStateHashSql(scope: Prisma.Sql): Prisma.Sql {
  return Prisma.sql`(WITH row_state AS MATERIALIZED (SELECT r.id, encode(sha256(convert_to(jsonb_build_array(
    r.id, r."benchmarkProtocolId", r."testClipId", r."workloadId", r."recipeId", r."environmentId", r."physicalSourceId", r."campaignId", r."repetitionGroupId", r."repetitionIndex",
    r.status, r."encodeTimerBoundary", r."inputHash", r."encodeWallTimeMs", r."encodeFps", r."sourceFps", r."realTimeRatio", r."sourceFrameCount", r."encodedFrameCount", r."preRunEnvironmentCheck",
    b."protocolVersion", b."canonicalRecipeRules", c.sha256, c."exactFrameCount", c."exactDurationSeconds", c."frameRateNumerator", c."frameRateDenominator",
    a.id, a.status, a."metricModelId", a."analysisWorkerVersion", a."analysisProvenance"->'workerBuildFingerprint', a."vmafMean", a."vmafP5", a."videoBitrateBps", a."fileSizeBytes",
    f.id, f.role, f."benchmarkRunId", f.sha256, f."byteSize", f."storageState", f."storageProvider", f."storageKey", f."storageUrl",
    review.id, review.decision
  )::text, 'UTF8')), 'hex') AS hash
    FROM "BenchmarkRun" r JOIN "BenchmarkProtocol" b ON b.id = r."benchmarkProtocolId" JOIN "TestClip" c ON c.id = r."testClipId"
    LEFT JOIN LATERAL (SELECT a.* FROM "QualityAnalysis" a WHERE a."benchmarkRunId" = r.id ORDER BY a."createdAt" DESC, a.id DESC LIMIT 1) a ON true
    LEFT JOIN "Artifact" f ON f.id = a."artifactId"
    LEFT JOIN LATERAL (SELECT v.id, v.decision FROM "EvidenceReview" v WHERE v."analysisId" = a.id ORDER BY v."createdAt" DESC, v.id DESC LIMIT 1) review ON true
    WHERE ${scope})
    SELECT encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array(id, hash) ORDER BY id COLLATE "C"), '[]'::jsonb)::text, 'UTF8')), 'hex') FROM row_state)`;
}
export function measurementGroupScopeForMembers(runIds: readonly string[]): Prisma.Sql {
  return Prisma.sql`EXISTS (SELECT 1 FROM "BenchmarkRun" counted WHERE counted.id = ANY(${[...runIds]}::text[])
    AND counted."physicalSourceId" = r."physicalSourceId" AND counted."campaignId" = r."campaignId" AND counted."repetitionGroupId" = r."repetitionGroupId")`;
}
export function measurementGroupScopeForDerived(derivedId: Prisma.Sql): Prisma.Sql {
  // Publication stores these distinct group keys atomically with the members.
  // Hash every sibling as before; missing/extra coverage fails the stored v3 hash.
  return Prisma.sql`EXISTS (SELECT 1 FROM "DerivedResultGroupDependency" dependency WHERE dependency."derivedResultId" = ${derivedId}
    AND dependency."physicalSourceId" = r."physicalSourceId" AND dependency."campaignId" = r."campaignId" AND dependency."repetitionGroupId" = r."repetitionGroupId")`;
}
