import test from 'node:test';
import assert from 'node:assert/strict';
import { computePlScoreV7, parseWorkloadReferenceContexts } from '../dist/plScore.js';

const context = { workloadId: 'sports-1080p', workloadReferenceBitrateBps: 4_000_000 };
const input = { vmafMean: 94, vmafP5: 88, videoBitrateBps: 4_000_000, encodeFps: 60, sourceFps: 30 };

test('PL v7 is fixed, bounded, monotonic, and dominance-safe', () => {
  const score = computePlScoreV7(input, context);
  assert.equal(score.bitrate, 0.5);
  assert.ok(score.total >= 0 && score.total <= 100);
  const dominator = computePlScoreV7({ ...input, vmafMean: 96, videoBitrateBps: 3_000_000, encodeFps: 90 }, context);
  assert.ok(dominator.total > score.total);
  assert.deepEqual(computePlScoreV7(input, context), score);
});

test('PL v7 refuses incomplete evidence and invalid contexts', () => {
  assert.equal(computePlScoreV7({ ...input, vmafP5: null }, context), null);
  assert.equal(computePlScoreV7(input, { ...context, workloadReferenceBitrateBps: 0 }), null);
});

test('reference contexts are explicit and versioned outside the candidate set', () => {
  const contexts = parseWorkloadReferenceContexts('{"sports-1080p":4000000}');
  assert.equal(contexts.get('sports-1080p'), 4_000_000);
  assert.equal(parseWorkloadReferenceContexts('bad').size, 0);
});
