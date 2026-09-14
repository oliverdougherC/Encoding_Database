import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveValidationPath } from './validation-path-bindings.mjs';
const original = '/mac/staged/reference.mkv';
const document = { schemaVersion: 'encodingdb-validation-path-bindings/v1', registryHash: 'registry', bindings: [{ kind: 'REFERENCE', originalPath: original, retainedPath: '/p910/trusted/reference.mkv', sha256: 'source' }] };
test('relocates exact registered bytes while preserving original receipt paths', () => {
  const before = JSON.stringify(document);
  assert.equal(resolveValidationPath(document, 'REFERENCE', original, 'source', 'registry'), '/p910/trusted/reference.mkv');
  assert.equal(JSON.stringify(document), before);
  assert.equal(resolveValidationPath(null, 'REFERENCE', original, 'source', 'registry'), original);
});
test('rejects missing, duplicate, registry-mismatched or hash-substituted paths', () => {
  for (const args of [['ENCODED', original, 'source', 'registry'], ['REFERENCE', original, 'different', 'registry'], ['REFERENCE', original, 'source', 'different']]) assert.throws(() => resolveValidationPath(document, ...args));
  assert.throws(() => resolveValidationPath({ ...document, bindings: [...document.bindings, ...document.bindings] }, 'REFERENCE', original, 'source', 'registry'));
});
