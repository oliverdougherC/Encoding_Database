import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

import {
  SUITE_V1_CANONICAL_CONTENT_CLASSES,
  SUITE_V1_MANIFEST_PATH,
  buildPublicTestVideoCatalog,
  buildSuiteTestClipUpsertArgs,
  loadAuthoritativeSuiteManifest,
  parseSuiteManifest,
  upsertSuiteTestClips,
} from '../dist/v7/suite.js';

test('all packaged canonical source artifacts match manifest bytes and hashes', () => {
  const manifest = loadAuthoritativeSuiteManifest();
  for (const clip of manifest.clips) {
    const bytes = readFileSync(new URL(`canonical/${clip.fileName}`, SUITE_V1_MANIFEST_PATH));
    assert.equal(bytes.length, clip.byteSize, clip.id);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), clip.sha256, clip.id);
  }
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

test('authoritative frozen suite exposes seven actual references and retained acquisition', () => {
  const manifest = loadAuthoritativeSuiteManifest();
  assert.equal(manifest.suiteId, 'encodingdb-test-suite');
  assert.equal(manifest.suiteVersion, 'encodingdb-test-suite-v1');
  assert.equal(manifest.manifestVersion, 2);
  assert.equal(manifest.defaultQuickClipId, 'athletic-action-1080p24-final');
  assert.deepEqual(manifest.requiredContentClasses, [...SUITE_V1_CANONICAL_CONTENT_CLASSES]);
  assert.equal(manifest.generalPlPolicy.requiresCompleteCoverage, true);
  assert.equal(manifest.generalPlPolicy.weighting, 'equal-class-geometric-mean');
  assert.equal(manifest.generalPlPolicy.legacySingleClipGeneralPlAllowed, false);
  assert.equal(manifest.redistribution.reviewed, true);
  assert.equal(manifest.redistribution.redistributionApproved, true);
  assert.equal(manifest.clips.length, 7);
  assert.equal(new Set(manifest.clips.map(clip => clip.id)).size, 7);
  for (const clip of manifest.clips) {
    assert.match(clip.id, /-1080p24-final$/);
    assert.equal(clip.source.reviewed, true);
    assert.equal(clip.source.redistributionApproved, true);
    assert.ok(['CC-BY-4.0', 'CC-BY-3.0', 'CC0-1.0'].includes(clip.source.license));
    assert.ok(clip.source.provenance.length > 0);
    assert.equal(clip.acquisition.kind, 'retained-original');
    assert.equal(clip.acquisition.ffmpegLavfi, undefined);
    assert.equal(clip.media.width, 1920);
    assert.equal(clip.media.height, 1080);
    assert.deepEqual(clip.media.frameRate, { numerator: 24, denominator: 1 });
    const duration = clip.media.duration.numerator / clip.media.duration.denominator;
    assert.ok(duration >= 8 && duration <= 10);
    assert.equal(clip.media.frameCount, duration * 24);
    assert.equal(clip.media.pixelFormat, 'yuv420p');
    assert.equal(clip.media.bitDepth, 8);
    assert.equal(clip.media.chromaSubsampling, '4:2:0');
    assert.equal(clip.media.colorPrimaries, 'bt709');
    assert.equal(clip.media.colorTransfer, 'bt709');
    assert.equal(clip.media.colorMatrix, 'bt709');
    assert.equal(clip.media.colorRange, 'tv');
    assert.equal(clip.media.fieldOrder, 'progressive');
    assert.equal(clip.media.hdrMetadata, null);
    assert.match(clip.sha256, /^[0-9a-f]{64}$/);
    assert.ok(clip.byteSize > 0);
  }
});

test('public catalog exposes retained canonical reference identities', () => {
  const catalog = buildPublicTestVideoCatalog();
  const manifest = loadAuthoritativeSuiteManifest();
  assert.equal(catalog.length, 7);
  assert.equal(catalog.some((clip) => clip.fileName === 'sample.mp4'), false);
  assert.deepEqual(catalog.map((clip) => clip.contentClass), [...SUITE_V1_CANONICAL_CONTENT_CLASSES]);
  for (const clip of manifest.clips) {
    const entry = catalog.find(item => item.clipId === clip.id);
    assert.ok(entry);
    assert.equal(entry.workloadId, clip.id);
    assert.deepEqual(entry.source, clip.source);
    assert.deepEqual(entry.media, clip.media);
    assert.equal(entry.acquisition.kind, 'retained-original');
    assert.equal(entry.acquisition.ffmpegLavfi, undefined);
  }
});

test('parseSuiteManifest rejects invalid canonical coverage and corrupted clip evidence', () => {
  const manifest = clone(loadAuthoritativeSuiteManifest());
  manifest.requiredContentClasses = manifest.requiredContentClasses.slice(0, 6);
  assert.throws(
    () => parseSuiteManifest(manifest, 'broken-manifest'),
    /broken-manifest is invalid: requiredContentClasses/,
  );

  const corrupted = clone(loadAuthoritativeSuiteManifest());
  corrupted.clips[0].source.provenance = '';
  corrupted.clips[0].sha256 = 'xyz';
  corrupted.clips[0].byteSize = 0;
  assert.throws(
    () => parseSuiteManifest(corrupted, 'corrupted-manifest'),
    /corrupted-manifest is invalid: .*clips\.0\.source\.provenance.*clips\.0\.sha256.*clips\.0\.byteSize/s,
  );
});

test('parseSuiteManifest accepts reviewed retained-reference provenance for future frozen suites', () => {
  const manifest = clone(loadAuthoritativeSuiteManifest());
  manifest.redistribution = {
    license: 'LicenseRef-OperatorDistribution',
    notes: 'Operator reviewed redistribution for the frozen suite.',
    reviewed: true,
    redistributionApproved: true,
    reviewHash: 'a'.repeat(64),
    spdxExpression: 'LicenseRef-OperatorDistribution',
  };
  manifest.clips[0].source = {
    kind: 'operator-supplied',
    provenance: 'Owned and reviewed by the project operator.',
    license: 'CC0-1.0',
    reviewed: true,
    redistributionApproved: true,
    reviewHash: 'a'.repeat(64),
  };
  manifest.clips[0].acquisition = {
    kind: 'retained-original',
    container: 'mov',
    videoCodec: 'retained-reference',
    packagedRelativePath: `canonical/${manifest.clips[0].fileName}`,
    originalFileName: 'fixture-retained-reference.mov',
  };

  const parsed = parseSuiteManifest(manifest, 'retained-reference-manifest');

  assert.equal(parsed.redistribution.redistributionApproved, true);
  assert.equal(parsed.redistribution.spdxExpression, 'LicenseRef-OperatorDistribution');
  assert.equal(parsed.clips[0].source.reviewed, true);
  assert.equal(parsed.clips[0].acquisition.kind, 'retained-original');
});

test('buildSuiteTestClipUpsertArgs preserves immutable reference evidence exactly', () => {
  const manifest = loadAuthoritativeSuiteManifest();
  for (const clip of manifest.clips) {
    const args = buildSuiteTestClipUpsertArgs(manifest, clip);
    assert.deepEqual(args.where, { suiteId_suiteVersion_clipKey: {
      suiteId: manifest.suiteId, suiteVersion: manifest.suiteVersion, clipKey: clip.id,
    }});
    assert.equal(args.create.workloadId, clip.id);
    assert.equal(args.create.contentClass, clip.contentClass);
    assert.equal(args.create.manifestVersion, String(manifest.manifestVersion));
    assert.equal(args.create.sha256, clip.sha256);
    assert.equal(args.create.byteSize, clip.byteSize);
    assert.equal(args.create.exactFrameCount, clip.media.frameCount);
    assert.equal(args.create.exactDurationSeconds, clip.media.duration.numerator / clip.media.duration.denominator);
    assert.equal(args.create.frameRateNumerator, clip.media.frameRate.numerator);
    assert.equal(args.create.frameRateDenominator, clip.media.frameRate.denominator);
    assert.equal(args.create.pixelFormat, clip.media.pixelFormat);
    assert.equal(args.create.scanType, clip.media.fieldOrder);
    assert.equal(args.create.sourceProvenance.payloadContentClass, clip.payloadContentClass);
    assert.deepEqual(args.create.sourceProvenance.redistribution, manifest.redistribution);
    assert.deepEqual(args.create.sourceProvenance.acquisition, clip.acquisition);
    assert.deepEqual(args.update, args.create);
  }
});

test('upsertSuiteTestClips persists every canonical suite clip once', async () => {
  const manifest = loadAuthoritativeSuiteManifest();
  const calls = [];
  const delegate = {
    async upsert(args) {
      calls.push(args);
      return { id: args.create.clipKey, workloadId: args.create.workloadId };
    },
  };

  const persisted = await upsertSuiteTestClips(delegate, manifest);

  assert.equal(calls.length, 7);
  assert.deepEqual(
    calls.map((call) => call.create.contentClass),
    [...SUITE_V1_CANONICAL_CONTENT_CLASSES],
  );
  assert.deepEqual(
    persisted,
    manifest.clips.map((clip) => ({ id: clip.id, workloadId: clip.id })),
  );
});
