import { readFileSync } from 'node:fs';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, normalizeEvidencePolicy, type RecommendationEvidencePolicy } from './aggregation.js';
import { canonicalJsonString, sha256Hex } from './persistence.js';
export const SCORING_BEHAVIOR_MODULES = [
  '../plScore.js', './decision.js', './aggregation.js', './referenceContext.js',
  './persistence.js', './reviews.js', './recommendationPolicy.js', './calibrationRanking.js',
  './calibration.js', './calibrationRetention.js', './suite.js', './validationSources.js',
] as const;

/** Exact reviewed implementation manifest, including centers, confidence and review eligibility. */
export function buildScoringBehaviorManifest(readModule: (relativePath: string) => string = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')) {
  return SCORING_BEHAVIOR_MODULES.map((module) => ({ module, sha256: sha256Hex(readModule(module)) }));
}

export function buildScoringBehaviorHash(): string {
  return sha256Hex(canonicalJsonString(buildScoringBehaviorManifest()));
}

interface ContextIdentity {
  contextVersion: string; formulaVersion: string; qualityModelId: string; workloadId: string;
  transformConstants?: unknown; referenceFrontier?: unknown; workloadReferenceBitrateBps?: number;
  benchmarkProtocol?: { protocolVersion: string; sourceSuiteVersion: string };
}
/** Select only the explicitly deployed reviewed epoch; historical records are immutable snapshots. */
export function loadActiveRecommendationContextIdentity(env: NodeJS.ProcessEnv = process.env): {
  contextVersion: string; formulaVersion: string; qualityModelId: string;
  benchmarkProtocolVersion: string; sourceSuiteVersion: string; hash: string;
} | null {
  if (!env.PL_V7_REFERENCE_CONTEXT_PATH) return null;
  const context = JSON.parse(readFileSync(env.PL_V7_REFERENCE_CONTEXT_PATH, 'utf8'));
  const { hash, ...payload } = context;
  if (sha256Hex(canonicalJsonString(payload)) !== hash) throw new Error('Recommendation context hash mismatch');
  if (context.activation?.stage !== 'PRODUCTION') return null;
  if (context.provenance?.sourceMode !== 'retained-benchmark-evidence' || context.activation?.productionActivationAllowed !== true
    || !/^[0-9a-f]{64}$/.test(context.activation?.calibrationReviewHash ?? '') || context.scoringBehaviorHash !== buildScoringBehaviorHash()
    || ['contextVersion', 'formulaVersion', 'qualityModelId', 'benchmarkProtocolVersion', 'sourceSuiteVersion'].some(key => typeof context[key] !== 'string' || !context[key])) throw new Error('Active recommendation context is not a validated reviewed epoch');
  const policy = normalizeEvidencePolicy(context.recommendationEvidencePolicy);
  if (policy.policyStatus !== 'CALIBRATED' || sha256Hex(canonicalJsonString(policy as never)) !== context.recommendationEvidencePolicyHash) throw new Error('Active recommendation policy hash mismatch');
  return { contextVersion: context.contextVersion, formulaVersion: context.formulaVersion, qualityModelId: context.qualityModelId,
    benchmarkProtocolVersion: context.benchmarkProtocolVersion, sourceSuiteVersion: context.sourceSuiteVersion, hash };
}

/** Restarts reload the exact deployed artifact; never cache only by policy version. */
export function loadRecommendationEvidencePolicyForContext(record: ContextIdentity, env: NodeJS.ProcessEnv = process.env): RecommendationEvidencePolicy {
  if (!env.PL_V7_REFERENCE_CONTEXT_PATH) return DEFAULT_RECOMMENDATION_EVIDENCE_POLICY;
  const context = JSON.parse(readFileSync(env.PL_V7_REFERENCE_CONTEXT_PATH, 'utf8'));
  const { hash, ...payload } = context;
  if (sha256Hex(canonicalJsonString(payload)) !== hash) throw new Error('Recommendation context hash mismatch');
  if (context.activation?.stage !== 'PRODUCTION') return DEFAULT_RECOMMENDATION_EVIDENCE_POLICY;
  const persisted = record.referenceFrontier as Record<string, unknown> | null;
  if (context.provenance?.sourceMode !== 'retained-benchmark-evidence' || context.activation?.productionActivationAllowed !== true
    || !/^[0-9a-f]{64}$/.test(context.activation?.calibrationReviewHash ?? '')
    || record.contextVersion !== context.contextVersion || record.formulaVersion !== context.formulaVersion || record.qualityModelId !== context.qualityModelId
    || (record.benchmarkProtocol && (record.benchmarkProtocol.protocolVersion !== context.benchmarkProtocolVersion || record.benchmarkProtocol.sourceSuiteVersion !== context.sourceSuiteVersion))
    || canonicalJsonString(record.transformConstants as never) !== canonicalJsonString(context.transformConstants)
    || persisted?.contextHash !== hash || context.scoringBehaviorHash !== buildScoringBehaviorHash()) throw new Error('Recommendation evidence policy is incompatible with the persisted score context');
  const workload = context.workloads?.find((entry: { workloadId: string }) => entry.workloadId === record.workloadId);
  const general = record.workloadId === `general-suite:${context.sourceSuiteVersion}`;
  const expectedBitrate = workload?.workloadReferenceBitrateBps ?? (general && context.workloads?.length
    ? Number(Math.exp(context.workloads.reduce((sum: number, entry: { workloadReferenceBitrateBps: number }) => sum + Math.log(entry.workloadReferenceBitrateBps), 0) / context.workloads.length).toFixed(6)) : null);
  if (expectedBitrate == null || record.workloadReferenceBitrateBps !== expectedBitrate
    || (!general && canonicalJsonString(persisted?.referenceFrontier as never) !== canonicalJsonString(workload.referenceFrontier))) {
    throw new Error('Recommendation policy workload reference differs from the reviewed context');
  }
  const policy = normalizeEvidencePolicy(context.recommendationEvidencePolicy);
  if (policy.policyStatus !== 'CALIBRATED' || sha256Hex(canonicalJsonString(policy as never)) !== context.recommendationEvidencePolicyHash
    || canonicalJsonString(persisted?.recommendationEvidencePolicy as never) !== canonicalJsonString(policy as never)
    || persisted?.recommendationEvidencePolicyHash !== context.recommendationEvidencePolicyHash) throw new Error('Recommendation evidence policy is missing or its hash does not match');
  return policy;
}
