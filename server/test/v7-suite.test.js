import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

import {
  SUITE_V1_CANONICAL_CONTENT_CLASSES,
  SUITE_V1_DETERMINISTIC_FLAGS,
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

test('authoritative suite manifest exposes all seven canonical classes with exact v1 metadata', () => {
  const manifest = loadAuthoritativeSuiteManifest();

  assert.equal(manifest.suiteId, 'encodingdb-test-suite');
  assert.equal(manifest.suiteVersion, 'encodingdb-test-suite-v1');
  assert.equal(manifest.manifestVersion, 1);
  assert.equal(manifest.defaultQuickClipId, 'sports-action-960x540-24p');
  assert.deepEqual(manifest.requiredContentClasses, [...SUITE_V1_CANONICAL_CONTENT_CLASSES]);
  assert.equal(manifest.generalPlPolicy.requiresCompleteCoverage, true);
  assert.equal(manifest.generalPlPolicy.weighting, 'equal-class-geometric-mean');
  assert.equal(manifest.generalPlPolicy.legacySingleClipGeneralPlAllowed, false);
  assert.equal(manifest.redistribution.license, 'CC0-1.0');
  assert.equal(manifest.clips.length, 7);

  const sports = manifest.clips.find((clip) => clip.id === 'sports-action-960x540-24p');
  assert.ok(sports, 'sports-action-960x540-24p should exist');
  assert.equal(sports.contentClass, 'high-motion-sports');
  assert.equal(sports.payloadContentClass, 'action');
  assert.equal(sports.fileName, 'sports-action-960x540-24p.mkv');
  assert.equal(sports.source.kind, 'project-generated');
  assert.equal(sports.source.license, 'CC0-1.0');
  assert.equal(
    sports.source.provenance,
    'Generated from deterministic FFmpeg lavfi graphs owned by the project; no third-party media redistribution required.',
  );
  assert.equal(sports.acquisition.kind, 'generated');
  assert.equal(sports.acquisition.container, 'mkv');
  assert.equal(sports.acquisition.videoCodec, 'ffv1');
  assert.deepEqual(sports.acquisition.deterministicFlags, [...SUITE_V1_DETERMINISTIC_FLAGS]);
  assert.equal(sports.media.frameCount, 72);
  assert.deepEqual(sports.media.duration, { numerator: 3, denominator: 1 });
  assert.deepEqual(sports.media.frameRate, { numerator: 24, denominator: 1 });
  assert.equal(sports.media.width, 960);
  assert.equal(sports.media.height, 540);
  assert.equal(sports.media.pixelFormat, 'yuv420p');
  assert.equal(sports.media.bitDepth, 8);
  assert.equal(sports.media.chromaSubsampling, '4:2:0');
  assert.equal(sports.media.colorPrimaries, 'bt709');
  assert.equal(sports.media.colorTransfer, 'bt709');
  assert.equal(sports.media.colorMatrix, 'bt709');
  assert.equal(sports.media.colorRange, 'tv');
  assert.equal(sports.media.fieldOrder, 'progressive');
  assert.equal(sports.media.hdrMetadata, null);
  assert.equal(sports.sha256, '8dff09e5120e42c478ef02501ff75d7ae7e94a509b651a2a9506c03ff512876a');
  assert.equal(sports.byteSize, 3243818);
});

test('buildPublicTestVideoCatalog removes legacy sample.mp4 and exposes generated acquisition descriptors', () => {
  const catalog = buildPublicTestVideoCatalog();

  assert.equal(catalog.length, 7);
  assert.equal(catalog.some((clip) => clip.fileName === 'sample.mp4'), false);
  assert.deepEqual(
    catalog.map((clip) => clip.contentClass),
    [...SUITE_V1_CANONICAL_CONTENT_CLASSES],
  );

  const screen = catalog.find((clip) => clip.clipId === 'screen-text-960x540-24p');
  assert.ok(screen, 'screen-text-960x540-24p should exist');
  assert.equal(screen.workloadId, 'screen-text-960x540-24p');
  assert.equal(screen.source.license, 'CC0-1.0');
  assert.equal(screen.acquisition.kind, 'generated');
  assert.match(screen.acquisition.ffmpegLavfi, /^testsrc=size=960x540:rate=24/);
  assert.equal(screen.media.frameCount, 72);
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
    packagedRelativePath: 'canonical/sports-action-960x540-24p.mkv',
    originalFileName: 'sports-action-960x540-24p.mov',
  };

  const parsed = parseSuiteManifest(manifest, 'retained-reference-manifest');

  assert.equal(parsed.redistribution.redistributionApproved, true);
  assert.equal(parsed.redistribution.spdxExpression, 'LicenseRef-OperatorDistribution');
  assert.equal(parsed.clips[0].source.reviewed, true);
  assert.equal(parsed.clips[0].acquisition.kind, 'retained-original');
});

test('buildSuiteTestClipUpsertArgs maps suite manifest metadata into immutable TestClip evidence rows', () => {
  const manifest = loadAuthoritativeSuiteManifest();
  const clip = manifest.clips.find((entry) => entry.id === 'talking-head-960x540-24p');
  assert.ok(clip, 'talking-head-960x540-24p should exist');

  const args = buildSuiteTestClipUpsertArgs(manifest, clip);

  assert.deepEqual(args.where, {
    suiteId_suiteVersion_clipKey: {
      suiteId: 'encodingdb-test-suite',
      suiteVersion: 'encodingdb-test-suite-v1',
      clipKey: 'talking-head-960x540-24p',
    },
  });
  assert.equal(args.create.workloadId, 'talking-head-960x540-24p');
  assert.equal(args.create.contentClass, 'talking-head');
  assert.equal(args.create.manifestVersion, '1');
  assert.equal(args.create.sha256, 'dbc92d9910207f7ef30669ae5251110afb541f3fb2d343d2dcc6cbe9bd178faa');
  assert.equal(args.create.byteSize, 600620);
  assert.equal(args.create.exactFrameCount, 72);
  assert.equal(args.create.exactDurationSeconds, 3);
  assert.equal(args.create.frameRateNumerator, 24);
  assert.equal(args.create.frameRateDenominator, 1);
  assert.equal(args.create.pixelFormat, 'yuv420p');
  assert.equal(args.create.scanType, 'progressive');
  assert.equal(args.create.sourceProvenance.payloadContentClass, 'talkingHead');
  assert.equal(args.create.sourceProvenance.redistribution.license, 'CC0-1.0');
  assert.equal(
    args.create.sourceProvenance.acquisition.ffmpegLavfi,
    "color=c=0x31445a:size=960x540:rate=24,drawbox=x=280:y=100:w=400:h=360:color=0xd9b18c@1:t=fill,drawbox=x=350:y=220:w=48:h=24:color=black@0.95:t=fill,drawbox=x=562:y=220:w=48:h=24:color=black@0.95:t=fill,drawbox=x='430+6*sin(t*3)':y='330+4*sin(t*2.2)':w=100:h=16:color=0x7a342d@0.95:t=fill,drawbox=x=310:y=380:w=340:h=100:color=0x6a7d95@1:t=fill",
  );
  assert.deepEqual(args.update, args.create);
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
