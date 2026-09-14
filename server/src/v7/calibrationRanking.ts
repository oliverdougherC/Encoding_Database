import { readFileSync } from 'node:fs';
import { computePlScoreV7 } from '../plScore.js';
import { buildDecisionPayload, type CodecFamily, type DecisionCandidate, type PlFitMode } from './decision.js';
import type { CalibrationEvidenceDocument, CalibrationEvidenceRecord } from './calibration.js';
import { assertReferenceContextCalibrationBinding, parseReferenceContext, type ReferenceContext } from './referenceContext.js';

export function rankCalibrationChoices(rows: readonly CalibrationEvidenceRecord[], context: ReferenceContext, mode: PlFitMode, referenceWorkloadByEvidenceId: Record<string, string> = {}): string | null {
  const candidates: DecisionCandidate[] = rows.map((row) => {
    const workload = context.workloads.find((entry) => entry.workloadId === (referenceWorkloadByEvidenceId[row.evidenceId] ?? row.workloadId));
    if (!workload) throw new Error(`No fitted reference for evaluation workload ${row.workloadId}; an explicit transfer reference is required`);
    const score = computePlScoreV7({ vmafMean: row.vmafMean, vmafP5: row.vmafP5, videoBitrateBps: row.videoBitrateBps, encodeFps: row.realTimeRatio, sourceFps: 1 }, { workloadId: row.workloadId, workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps, ...context.transformConstants });
    return {
      rowId: row.evidenceId, encoderName: row.encoderImplementation, codecFamily: row.encoderFamily as CodecFamily,
      preset: row.preset, rateControl: { requestedMode: String(row.nativeRateControl.mode), effectiveMode: String(row.nativeRateControl.mode), qualityValue: null, targetBitrateKbps: null, maxBitrateKbps: null, bufferSizeKbits: null, label: JSON.stringify(row.nativeRateControl) },
      contentClass: row.contentClass, resolution: '1920x1080', passes: 1, workloadId: row.workloadId,
      hardwareContext: { environmentId: row.environmentFingerprint, environmentFingerprint: row.environmentFingerprint, cpuModel: '', gpuModel: row.hardwareFamily, ramGB: null, os: '' },
      sampleCount: 1, avgFps: row.realTimeRatio, avgSourceFps: 1, avgVmaf: row.vmafMean, avgVmafP5: row.vmafP5, avgVideoBitrateBps: row.videoBitrateBps,
      plScore: score?.total ?? null, canonical: { quality: score?.quality ?? null, bitrate: score?.bitrate ?? null, speed: score?.speed ?? null },
      context: { scoreContextId: context.hash, formulaVersion: context.formulaVersion, benchmarkProtocolVersion: context.benchmarkProtocolVersion, sourceSuiteVersion: context.sourceSuiteVersion, qualityModelId: context.qualityModelId, referenceContextVersion: context.contextVersion, workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps },
      confidenceLower: null, confidenceUpper: null, evidenceTier: 'PROVISIONAL', eligibleForDefaultRecommendation: false,
    };
  });
  // Compare experimental rankings, without making an individual observation public-eligible.
  return buildDecisionPayload(candidates, { selectedMode: mode }).rows.find((row) => row.fit.modes[mode].eligible)?.rowId ?? null;
}

export function verifyCalibrationRanking(document: CalibrationEvidenceDocument, context: ReferenceContext) {
  const byId = new Map(document.corpus.map((row) => [row.evidenceId, row]));
  const rows = (ids: readonly string[]) => ids.map((id) => { const row = byId.get(id); if (!row) throw new Error(`Unknown ranking evidence ${id}`); return row; });
  const results = [];
  for (const comparison of document.goldenDecisions) {
    const predicted = rankCalibrationChoices(rows(comparison.candidateEvidenceIds), context, comparison.scenario.toLowerCase() as PlFitMode);
    if (predicted !== comparison.selectedEvidenceId) throw new Error(`Production ranking disagrees with golden decision ${comparison.comparisonId}`);
    results.push({ id: comparison.comparisonId, predicted });
  }
  for (const review of document.topResultReviews) {
    const selected = byId.get(review.evidenceId);
    if (!selected) throw new Error(`Unknown top-result evidence ${review.evidenceId}`);
    const excluded = new Set(document.metricSanityReviews.filter((entry) => entry.disposition === 'EXCLUDE' || entry.disposition === 'INVESTIGATE').flatMap((entry) => entry.evidenceIds));
    const candidates = document.corpus.filter((row) => !excluded.has(row.evidenceId)
      && row.workloadId === selected.workloadId && row.environmentFingerprint === selected.environmentFingerprint
      && (review.familyKey === `encoder:${row.encoderImplementation}` || review.familyKey === `hardware:${row.hardwareFamily}`));
    if (candidates.length !== new Set(review.candidateEvidenceIds).size || candidates.some((row) => !review.candidateEvidenceIds.includes(row.evidenceId))) {
      throw new Error(`Top-result comparison omits compatible tested family choices ${review.reviewId}`);
    }
    const predicted = rankCalibrationChoices(candidates, context, review.scenario.toLowerCase() as PlFitMode);
    if (predicted !== review.evidenceId) throw new Error(`Production ranking disagrees with top-result review ${review.reviewId}`);
    results.push({ id: review.reviewId, predicted });
  }
  for (const fold of document.holdoutEvaluations) {
    if (!fold.fittedContextArtifactPath) throw new Error(`Missing independently fitted context artifact for ${fold.evaluationId}`);
    const fitted = parseReferenceContext(readFileSync(fold.fittedContextArtifactPath, 'utf8'));
    if (fitted.hash !== fold.fittedContextHash) throw new Error(`Holdout context hash mismatch ${fold.evaluationId}`);
    const fitIds = new Set(fold.fittingEvidenceIds);
    assertReferenceContextCalibrationBinding(fitted, { ...document, corpus: document.corpus.map((row) => ({ ...row, partition: fitIds.has(row.evidenceId) ? 'CALIBRATION' : 'HOLDOUT' })) });
    const actualFrontierIds = new Set(fitted.workloads.flatMap((workload) => workload.referenceFrontier.flatMap((point) => point.evidence.map((ref) => document.corpus.find((row) => row.qualityAnalysisId === ref.qualityAnalysisId)?.evidenceId))));
    if (actualFrontierIds.size !== new Set(fold.frontierEvidenceIds).size || fold.frontierEvidenceIds.some((id) => !actualFrontierIds.has(id))) throw new Error(`Holdout frontier manifest differs from applied context ${fold.evaluationId}`);
    const predicted = rankCalibrationChoices(rows(fold.evidenceIds), fitted, fold.scenario.toLowerCase() as PlFitMode, fold.referenceWorkloadByEvidenceId);
    if (predicted !== fold.predictedTopEvidenceId) throw new Error(`Production ranking differs from recorded holdout prediction ${fold.evaluationId}`);
    results.push({ id: fold.evaluationId, predicted });
  }
  return results;
}
