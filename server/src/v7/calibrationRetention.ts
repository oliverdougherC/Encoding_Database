import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import type { PrismaClient } from '@prisma/client';
import type { CalibrationEvidenceDocument } from './calibration.js';
import { applyEffectiveReview } from './reviews.js';
import { canonicalJsonString } from './persistence.js';

/** Verifies live identities and object bytes, not a self-consistent exported JSON. */
export async function verifyCalibrationRetainedEvidence(
  client: Pick<PrismaClient, 'qualityAnalysis'>,
  document: CalibrationEvidenceDocument,
  storageRoot = process.env.ARTIFACT_STORAGE_ROOT ?? path.resolve(process.cwd(), '.artifacts'),
): Promise<{ verifiedAnalyses: number; verifiedObjects: number }> {
  const root = await realpath(storageRoot);
  const verifiedObjects = new Set<string>();
  for (const evidence of document.corpus) {
    const analysis = await client.qualityAnalysis.findUnique({
      where: { id: evidence.qualityAnalysisId },
      include: { evidenceReviews: true, artifact: true, benchmarkRun: { include: { benchmarkProtocol: true, recipe: true, environment: true, testClip: true } } },
    });
    if (!analysis?.artifact) throw new Error(`Missing retained analysis/artifact ${evidence.qualityAnalysisId}`);
    const newest = await client.qualityAnalysis.findFirst({ where: { benchmarkRunId: analysis.benchmarkRunId, metricModelId: analysis.metricModelId }, orderBy: [{ createdAt: 'desc' }, { id: 'desc' }], select: { id: true } });
    if (newest?.id !== analysis.id) throw new Error(`Calibration analysis has been superseded ${analysis.id}`);
    const run = analysis.benchmarkRun;
    const artifact = analysis.artifact;
    const actual = {
      benchmarkRunId: run.id, artifactId: artifact.id, artifactSha256: artifact.sha256,
      artifactStorageState: artifact.storageState, analysisWorkerVersion: analysis.analysisWorkerVersion,
      recipeFingerprint: run.recipe.fingerprint, environmentFingerprint: run.environment.fingerprint,
      machineSourceId: run.physicalSourceId, workloadId: run.workloadId, contentClass: run.testClip.contentClass,
      encoderFamily: run.recipe.codecFamily, encoderImplementation: run.recipe.encoderImplementation,
      hardwareFamily: ['videotoolbox', 'nvenc', 'qsv', 'amf', 'vaapi'].find((family) => run.recipe.encoderImplementation.toLowerCase().includes(family)) ?? 'software',
      nativeRateControl: run.recipe.requestedRateControl, preset: run.recipe.preset ?? 'unspecified',
      runStatus: run.status, analysisStatus: analysis.status,
      vmafMean: analysis.vmafMean, vmafP5: analysis.vmafP5, xpsnr: analysis.xpsnr,
      videoBitrateBps: analysis.videoBitrateBps,
      realTimeRatio: run.realTimeRatio ?? (run.encodeFps && run.sourceFps ? run.encodeFps / run.sourceFps : null),
    };
    for (const [key, value] of Object.entries(actual)) {
      if (canonicalJsonString(value as never) !== canonicalJsonString(evidence[key as keyof typeof evidence] as never)) {
        throw new Error(`Retained evidence mismatch ${evidence.evidenceId}.${key}`);
      }
    }
    if (analysis.metricModelId !== document.qualityModelId
      || run.benchmarkProtocol.protocolVersion !== document.benchmarkProtocolVersion
      || run.benchmarkProtocol.sourceSuiteVersion !== document.sourceSuiteVersion
      || run.benchmarkProtocol.protocolVersion !== '7.1' || run.encodeTimerBoundary !== 'ffmpeg-process-v1'
      || !run.physicalSourceId || artifact.benchmarkRunId !== run.id || artifact.role !== 'ENCODED'
      || !['RETAINED', 'VERIFIED'].includes(artifact.storageState)) throw new Error(`Incompatible retained evidence ${evidence.evidenceId}`);
    const effective = applyEffectiveReview({ runStatus: run.status, analysisStatus: analysis.status, artifactState: artifact.storageState, analysisId: analysis.id, reviews: analysis.evidenceReviews });
    if ((evidence.evidenceReviewId ?? null) !== effective.reviewId) throw new Error(`Evidence review head changed ${evidence.evidenceId}`);
    const excluded = document.metricSanityReviews.some((review) => review.disposition === 'EXCLUDE' && review.evidenceIds.includes(evidence.evidenceId));
    if (!excluded && !effective.eligible) throw new Error(`Evidence lacks effective retained eligibility ${evidence.evidenceId}`);
    if (!artifact.storageKey || artifact.storageProvider !== 'localfs') throw new Error(`Unsupported or missing retained storage identity ${artifact.id}`);
    const objectPath = await realpath(path.resolve(root, artifact.storageKey));
    if (!objectPath.startsWith(`${root}${path.sep}`)) throw new Error('Retained object escapes storage root');
    if (verifiedObjects.has(objectPath)) continue;
    const objectStat = await stat(objectPath);
    if (!objectStat.isFile() || objectStat.size !== artifact.byteSize) throw new Error(`Retained object size mismatch ${artifact.id}`);
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(objectPath)) hash.update(chunk);
    if (hash.digest('hex') !== artifact.sha256) throw new Error(`Retained object SHA-256 mismatch ${artifact.id}`);
    verifiedObjects.add(objectPath);
  }
  return { verifiedAnalyses: document.corpus.length, verifiedObjects: verifiedObjects.size };
}
