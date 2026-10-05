/** Operator-provided media locations must remain inert when assigned to href/src. */
export function validateReviewMediaPath(value) {
  if (typeof value !== 'string' || !value || value.length > 4096) throw new Error('Media path must be a nonempty string');
  let decoded = value;
  for (let i = 0; i < 8; i++) {
    if (/[\s\u0000-\u001f\u007f\\]/u.test(decoded)) throw new Error('Media path contains whitespace, controls or backslashes');
    const next = decodeURIComponent(decoded);
    if (next === decoded) break;
    decoded = next;
    if (i === 7) throw new Error('Media path has excessive percent encoding');
  }
  if (/^https?:\/\//i.test(value)) {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error('Media URL must be HTTP(S) without credentials');
    return value;
  }
  if (/^[a-z][a-z\d+.-]*:/i.test(decoded) || decoded.startsWith('/') || decoded.includes(':') || decoded.split(/[/?#]/).includes('..')) {
    throw new Error('Media path must be a local relative path or HTTP(S) URL');
  }
  return value;
}

export function validateReviewMediaMap(map) {
  if (!map || typeof map !== 'object' || Array.isArray(map)) throw new Error('Invalid media map');
  for (const [sha256, entry] of Object.entries(map)) {
    if (!/^[a-f0-9]{64}$/.test(sha256) || !entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('Invalid media identity');
    validateReviewMediaPath(entry.playbackPath);
    if (entry.originalPath != null) validateReviewMediaPath(entry.originalPath);
  }
  return map;
}
