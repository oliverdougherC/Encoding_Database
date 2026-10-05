import test from 'node:test';
import assert from 'node:assert/strict';
import { CANONICAL_MEASUREMENT_RULES } from '../dist/v7/measurementGroup.js';
import { validationRecipeRules, assertValidationProtocolRules } from '../../scripts/calibration-validation-protocol.mjs';
const receipt = () => ({ protocolVersion: '7.1', protocolConfig: { version: '7.1', warmup_runs: 1, minimum_measured_runs: 2, max_adaptive_repeats: 2, stability_threshold_ratio: 0.03 } });

test('imported validation protocol carries every measurement-group gate actually declared by the original receipt', () => {
  const rules = validationRecipeRules(receipt());
  for (const [key, value] of Object.entries(CANONICAL_MEASUREMENT_RULES)) assert.equal(rules[key], value);
  assert.equal(rules.validationOnly, true); assert.equal(rules.warmupRuns, 1);
  assert.doesNotThrow(() => assertValidationProtocolRules({ canonicalRecipeRules: rules }, rules));
});
for (const [field, value] of [['version', '7.0'], ['warmup_runs', 0], ['minimum_measured_runs', 1], ['max_adaptive_repeats', 9], ['stability_threshold_ratio', 0.04]]) {
  test(`validation import refuses changed measured rule ${field}`, () => {
    const invalid = receipt(); invalid.protocolConfig[field] = value;
    assert.throws(() => validationRecipeRules(invalid), /exact canonical measurement rules/);
  });
}
test('missing measurement declarations cannot be inferred from a claimed protocol version', () => {
  assert.throws(() => validationRecipeRules({ protocolVersion: '7.1' }), /exact canonical measurement rules/);
});
test('legacy incomplete imported metadata is rejected without rewriting original protocol', () => {
  const protocol = { canonicalRecipeRules: { validationOnly: true, warmupRuns: 1, minimumMeasuredRuns: 2 } };
  const before = structuredClone(protocol);
  assert.throws(() => assertValidationProtocolRules(protocol, validationRecipeRules(receipt())), /audited isolated correction/);
  assert.deepEqual(protocol, before);
});
