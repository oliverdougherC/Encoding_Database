// Relocate retained bytes without changing any original campaign receipt.
export function resolveValidationPath(document, kind, originalPath, sha256, registryHash) {
  if (!document) return originalPath;
  if (document.schemaVersion !== 'encodingdb-validation-path-bindings/v1' || document.registryHash !== registryHash
    || !Array.isArray(document.bindings)) throw new Error('Invalid validation path-binding manifest');
  const matches = document.bindings.filter(row => row.kind === kind && row.originalPath === originalPath);
  if (matches.length !== 1 || matches[0].sha256 !== sha256 || typeof matches[0].retainedPath !== 'string'
    || !matches[0].retainedPath.startsWith('/')) throw new Error('Missing, ambiguous or hash-mismatched retained path binding');
  return matches[0].retainedPath;
}
