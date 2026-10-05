import { CANONICAL_MEASUREMENT_RULES } from '../server/dist/v7/measurementGroup.js';
import { canonicalJsonString } from '../server/dist/v7/persistence.js';

/** Bind imported metadata to the rules actually recorded before measurement. */
export function validationRecipeRules(receipt) {
  const config = receipt?.protocolConfig;
  if (receipt?.protocolVersion !== '7.1' || config?.version !== '7.1'
    || config.warmup_runs !== 1
    || config.minimum_measured_runs !== CANONICAL_MEASUREMENT_RULES.minimumMeasuredRuns
    || config.max_adaptive_repeats !== CANONICAL_MEASUREMENT_RULES.maxAdaptiveRepeats
    || config.stability_threshold_ratio !== CANONICAL_MEASUREMENT_RULES.stabilityThresholdRatio) {
    throw new Error('Validation receipt does not declare the exact canonical measurement rules');
  }
  return { validationOnly: true, warmupRuns: 1, ...CANONICAL_MEASUREMENT_RULES };
}

export function assertValidationProtocolRules(protocol, expected) {
  if (canonicalJsonString(protocol.canonicalRecipeRules) !== canonicalJsonString(expected)) {
    throw new Error('Existing validation protocol metadata differs; preserve it and use an audited isolated correction');
  }
}
