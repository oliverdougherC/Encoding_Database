import { createHash } from 'node:crypto';
export function assertIsolatedCorpusDatabase(url) {
  const parsed = new URL(url);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname) || !/^\/encodingdb_corpus(?:_[a-z0-9_]+)?$/.test(parsed.pathname)) {
    throw new Error('Corpus fixtures require a loopback encodingdb_corpus test database');
  }
}
const digest = value => createHash('sha256').update(value).digest('hex');
export async function seedCorpusFixture(db, prefix = 'corpus-test') {
  const protocol = await db.benchmarkProtocol.create({ data: {
    id: `${prefix}-protocol`, protocolVersion: `${prefix}-7.1`, sourceSuiteVersion: 'isolated-synthetic-fixture',
    minimumClientVersion: '0.3.0', canonicalRecipeRules: {}, canonicalOutputRules: {}, metricWorkerVersion: 'authoritative-analysis/corpus-test',
  } });
  const clip = await db.testClip.create({ data: {
    id: `${prefix}-clip`, suiteId: prefix, suiteVersion: 'fixture', manifestVersion: 'fixture', clipKey: prefix,
    displayName: 'Isolated corpus fixture, not media evidence', workloadId: prefix, contentClass: 'screen-text', sourceProvenance: {},
    sha256: digest(prefix), byteSize: 1, exactFrameCount: 240, exactDurationSeconds: 10, frameRateNumerator: 24, frameRateDenominator: 1,
    width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '420',
  } });
  const recipes = await Promise.all(['libx264', 'h264_nvenc', 'libx265', 'libsvtav1'].map((encoder, i) => db.recipe.create({ data: {
    id: `${prefix}-recipe-${i}`, fingerprint: digest(`${prefix}-recipe-${i}`), canonicalJson: {}, codecFamily: i === 3 ? 'av1' : 'h264',
    encoderImplementation: encoder, preset: i === 3 ? null : i === 2 ? 'slow' : 'fast', pixelFormat: 'yuv420p', bitDepth: 8,
    chromaSubsampling: '420', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {},
  } })));
  const environment = await db.environment.create({ data: {
    id: `${prefix}-env`, fingerprint: digest(`${prefix}-env`), canonicalJson: {}, cpuModel: 'Fixture CPU 100%_literal', cpuArchitecture: 'x86_64',
    gpuModel: 'Fixture GPU', osName: 'Linux', osVersion: 'fixture', ffmpegBuildFingerprint: digest('fixture-ffmpeg'),
    ffmpegVersion: 'fixture', clientVersion: '0.3.0',
  } });
  for (let i = 0; i < 20; i++) {
    const status = i % 4 === 3 || i % 5 === 0 ? 'SUSPECT' : 'ACCEPTED';
    const run = await db.benchmarkRun.create({ data: {
      id: `${prefix}-run-${i}`, createdAt: new Date(Date.UTC(2026, 0, 1, 0, 0, i)),
      benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: prefix, recipeId: recipes[i % 4].id,
      environmentId: environment.id, payloadHash: digest(`${prefix}-run-${i}`), campaignId: `campaign-${i}`,
      physicalSourceId: i % 5 === 0 ? null : `source-${i % 3}`, repetitionGroupId: `${prefix}-repeat-${Math.floor(i / 4)}`,
      encodeWallTimeMs: 1000, encodeFps: i === 4 ? null : i * 10 + 1, sourceFps: 24, realTimeRatio: (i * 10 + 1) / 24,
      sourceFrameCount: 240, encodedFrameCount: 240, status,
    } });
    const artifact = await db.artifact.create({ data: {
      id: `${prefix}-artifact-${i}`, benchmarkRunId: run.id, role: 'ENCODED', sha256: digest(`${prefix}-artifact-${i}`),
      byteSize: i * 100 + 1000, storageState: i % 2 ? 'VERIFIED' : 'RETAINED',
    } });
    await db.qualityAnalysis.create({ data: {
      id: `${prefix}-analysis-${i}`, createdAt: run.createdAt, benchmarkRunId: run.id, artifactId: artifact.id,
      status: status === 'ACCEPTED' ? 'COMPLETE' : 'SUSPECT', metricModelId: 'fixture-model',
      analysisWorkerVersion: protocol.metricWorkerVersion, analysisProvenance: {}, vmafMean: i === 2 ? null : 70 + i,
      vmafP5: 60 + i, videoBitrateBps: 1000 + i * 101, fileSizeBytes: i % 3 ? 1000 + i * 100 : null,
      completedAt: new Date(run.createdAt.getTime() + 1200000),
    } });
  }
  return { prefix, protocol, clip, recipes, environment };
}
// Keep append-only reviews intact even in test databases. Retiring the isolated
// protocol removes a fixture from public queries without deleting its audit trail.
export async function removeCorpusFixture(db, prefix = 'corpus-test') {
  await db.benchmarkProtocol.updateMany({ where: { id: { startsWith: prefix } }, data: { state: 'RETIRED' } });
}
