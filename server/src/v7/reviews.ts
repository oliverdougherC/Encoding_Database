import crypto from 'node:crypto';
import { Router, type Request, type RequestHandler } from 'express';
import type { PrismaClient } from '@prisma/client';
import { z } from 'zod';

export type ReviewDecision = 'EXPECTED' | 'REJECT' | 'INVESTIGATE' | 'REVOKE';
export interface ReviewRecord {
  id: string;
  analysisId: string;
  decision: ReviewDecision;
  createdAt: Date | string;
}

/** A decision only applies to the exact immutable analysis it names. */
export function applyEffectiveReview(input: {
  runStatus: string;
  analysisStatus: string;
  artifactState: string;
  analysisId: string;
  reviews?: readonly ReviewRecord[];
}) {
  const latest = [...(input.reviews ?? [])]
    .filter((review) => review.analysisId === input.analysisId)
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime() || b.id.localeCompare(a.id))[0];
  let { runStatus, analysisStatus, artifactState } = input;
  if (latest?.decision === 'REJECT') runStatus = 'REJECTED';
  if (latest?.decision === 'INVESTIGATE') runStatus = 'SUSPECT';
  const structurallyValid = ['ACCEPTED', 'SUSPECT'].includes(input.runStatus)
    && ['COMPLETE', 'SUSPECT'].includes(input.analysisStatus)
    && ['VERIFIED', 'RETAINED'].includes(input.artifactState);
  if (latest?.decision === 'EXPECTED' && structurallyValid) {
    runStatus = 'ACCEPTED';
    analysisStatus = 'COMPLETE';
    artifactState = 'RETAINED';
  }
  const eligible = runStatus === 'ACCEPTED' && analysisStatus === 'COMPLETE'
    && artifactState === 'RETAINED' && latest?.decision !== 'INVESTIGATE';
  return { eligible, runStatus, analysisStatus, artifactState, reviewId: latest?.id ?? null };
}

const decisionInput = z.object({
  benchmarkRunId: z.string().min(1),
  artifactId: z.string().min(1),
  artifactSha256: z.string().regex(/^[a-f0-9]{64}$/),
  metricModelId: z.string().min(1),
  analysisWorkerVersion: z.string().min(1),
  decision: z.enum(['EXPECTED', 'REJECT', 'INVESTIGATE', 'REVOKE']),
  rationale: z.string().trim().min(20).max(10000),
  evidenceLinks: z.array(z.string().url()).min(1).max(30),
  supersedesId: z.string().min(1).nullable().default(null),
}).strict();

export class ReviewConflict extends Error {}

export async function appendEvidenceReview(client: PrismaClient, analysisId: string, reviewerId: string, raw: unknown) {
  const input = decisionInput.parse(raw);
  if (!reviewerId.trim()) throw new ReviewConflict('An authenticated reviewer identity is required');
  const id = `review_${crypto.createHash('sha256').update(JSON.stringify({ analysisId, reviewerId, ...input })).digest('hex')}`;
  return client.$transaction(async (tx) => {
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(714555)`;
    // Serializes review heads with other review writers without holding locks over media work.
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${`encodingdb-review:${input.benchmarkRunId}`}, 0))`;
    const duplicate = await tx.evidenceReview.findUnique({ where: { id } });
    if (duplicate) return duplicate;
    const analysis = await tx.qualityAnalysis.findUnique({
      where: { id: analysisId }, include: { artifact: true, benchmarkRun: true },
    });
    if (!analysis || !analysis.artifact || analysis.benchmarkRunId !== input.benchmarkRunId
      || analysis.artifactId !== input.artifactId || analysis.artifact.sha256 !== input.artifactSha256
      || analysis.metricModelId !== input.metricModelId || analysis.analysisWorkerVersion !== input.analysisWorkerVersion) {
      throw new ReviewConflict('Review identity does not match the retained analysis and artifact');
    }
    if (!analysis.completedAt || !['COMPLETE', 'SUSPECT', 'REJECTED'].includes(analysis.status)) {
      throw new ReviewConflict('Only terminal immutable analyses can be reviewed');
    }
    const latest = await tx.evidenceReview.findFirst({
      where: { analysisId }, orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
    });
    if ((latest?.id ?? null) !== input.supersedesId) throw new ReviewConflict('Supersedes must name the current review head');
    if (input.decision === 'REVOKE' && !latest) throw new ReviewConflict('No review exists to revoke');
    if (input.decision === 'EXPECTED' && !applyEffectiveReview({
      runStatus: analysis.benchmarkRun.status, analysisStatus: analysis.status,
      artifactState: analysis.artifact.storageState, analysisId,
      reviews: [{ id, analysisId, decision: 'EXPECTED', createdAt: new Date() }],
    }).eligible) throw new ReviewConflict('Review cannot override structural rejection, invalid timing or missing bytes');
    const createdAt = new Date(Math.max(Date.now(), (latest?.createdAt.getTime() ?? 0) + 1));
    const review = await tx.evidenceReview.create({ data: { id, analysisId, reviewerId, createdAt, ...input } });
    if (input.decision === 'EXPECTED') {
      await tx.artifact.updateMany({
        where: { id: input.artifactId, storageState: 'VERIFIED' },
        data: { storageState: 'RETAINED', retainedAt: new Date() },
      });
    }
    const run = analysis.benchmarkRun;
    await tx.derivedResult.updateMany({
      where: { benchmarkProtocolId: run.benchmarkProtocolId, recipeId: run.recipeId, environmentId: run.environmentId },
      data: { invalidatedAt: new Date(), invalidationReason: `Evidence review ${review.id}; rebuild pending` },
    });
    await tx.qualityAnalysis.update({ where: { id: analysisId }, data: { recomputePending: true, recomputeLastError: null } });
    return review;
  });
}

/** Mounted with the same server-owned operator authentication as reanalysis. */
export function createEvidenceReviewRouter(options: {
  client: PrismaClient;
  authorize: RequestHandler;
  reviewerIdentity: (request: Request) => string;
  afterReview?: () => void;
}) {
  const router = Router();
  router.use('/v7/operator', options.authorize);
  router.post('/v7/operator/analyses/:analysisId/reviews', async (req, res) => {
    try {
      const review = await appendEvidenceReview(options.client, String(req.params.analysisId), options.reviewerIdentity(req), req.body);
      options.afterReview?.();
      res.status(201).json({ review, recomputation: 'QUEUED' });
    } catch (error) {
      if (error instanceof z.ZodError) return res.status(400).json({ error: 'Invalid review', details: error.issues });
      if (error instanceof ReviewConflict) return res.status(409).json({ error: error.message });
      res.status(500).json({ error: 'Unable to persist review' });
    }
  });
  router.get('/v7/operator/analyses/:analysisId/reviews', async (req, res) => {
    const reviews = await options.client.evidenceReview.findMany({
      where: { analysisId: String(req.params.analysisId) }, orderBy: [{ createdAt: 'desc' }, { id: 'desc' }], take: 100,
    });
    res.json({ reviews, limit: 100 });
  });
  return router;
}
