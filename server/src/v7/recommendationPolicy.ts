import { readFileSync } from 'node:fs';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, normalizeEvidencePolicy, type RecommendationEvidencePolicy } from './aggregation.js';
import { canonicalJsonString, sha256Hex } from './persistence.js';
export function buildScoringBehaviorHash(): string {
  return sha256Hex(readFileSync(new URL('../plScore.js', import.meta.url), 'utf8') + '\n' + readFileSync(new URL('./decision.js', import.meta.url), 'utf8'));
}

interface ContextIdentity {
  contextVersion: string; formulaVersion: string; qualityModelId: string; workloadId: string;
  transformConstants?: unknown; referenceFrontier?: unknown;
  benchmarkProtocol?: { protocolVersion: string; sourceSuiteVersion: string };
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
  const policy = normalizeEvidencePolicy(context.recommendationEvidencePolicy);
  if (policy.policyStatus !== 'CALIBRATED' || sha256Hex(canonicalJsonString(policy as never)) !== context.recommendationEvidencePolicyHash
    || canonicalJsonString(persisted?.recommendationEvidencePolicy as never) !== canonicalJsonString(policy as never)
    || persisted?.recommendationEvidencePolicyHash !== context.recommendationEvidencePolicyHash) throw new Error('Recommendation evidence policy is missing or its hash does not match');
  return policy;
}
