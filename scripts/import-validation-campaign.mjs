#!/usr/bin/env node
// Local operator only. No HTTP route and no production DATABASE_URL fallback.
import { readFile, mkdir, copyFile, rename, stat, writeFile } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validationMeasurementGroup } from './validation-measurement-group.mjs';

const args = new Map();
for (let i = 2; i < process.argv.length; i += 2) args.set(process.argv[i], process.argv[i + 1]);
for (const name of ['--campaign', '--registry', '--storage-root']) if (!args.get(name)) throw new Error(`${name} is required`);
const url = process.env.VALIDATION_DATABASE_URL;
if (!url || !/^\/encodingdb_validation_[a-z0-9_]+$/.test(new URL(url).pathname)) throw new Error('VALIDATION_DATABASE_URL must name an isolated encodingdb_validation_* database');
process.env.DATABASE_URL = url;
process.env.VALIDATION_SOURCE_REGISTRY_PATH = path.resolve(args.get('--registry'));
const root = path.resolve(args.get('--storage-root'));
if (!root.split(path.sep).some(part => part.includes('validation'))) throw new Error('Storage must be in an explicit task-owned validation namespace');
await mkdir(root, { recursive: true });
const server = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../server');
const [{ PrismaClient }, artifacts, sources, persistence, suite] = await Promise.all([
  import(path.join(server, 'node_modules/@prisma/client/default.js')),
  import(path.join(server, 'dist/v7/artifacts.js')), import(path.join(server, 'dist/v7/validationSources.js')),
  import(path.join(server, 'dist/v7/persistence.js')), import(path.join(server, 'dist/v7/suite.js')),
]);
if (artifacts.SERVER_CANONICAL_PROTOCOL_VERSION !== '7.1') throw new Error('The corrected server implementation is required');
const hash = (value) => persistence.sha256Hex(persistence.canonicalJsonString(value));
async function hashFile(file) { const digest = createHash('sha256'); for await (const chunk of createReadStream(file)) digest.update(chunk); return digest.digest('hex'); }
const receipt = JSON.parse(await readFile(path.resolve(args.get('--campaign')), 'utf8'));
if (receipt.schemaVersion !== 'encodingdb-controlled-validation-campaign/v1' || receipt.validationOnly !== true || receipt.protocolVersion !== '7.1') throw new Error('Not a corrected validation campaign receipt');
const source = sources.loadRegisteredValidationSource(receipt.source.workloadId);
if (hash(source) !== receipt.sourceRegistrationHash || hash(receipt.source) !== hash(source)) throw new Error('Campaign source registration differs');
if (await hashFile(receipt.referencePath) !== source.sourceSha256 || (await stat(receipt.referencePath)).size !== source.byteSize) throw new Error('Registered reference bytes differ');
const measured = receipt.campaign.recipeResults.flatMap(result => {
  if (!result.stability.stable || result.measuredRunsCounted < 2) throw new Error('Campaign timing is not stable enough for authoritative analysis');
  const measurementGroup = validationMeasurementGroup(result);
  return result.runs.filter(run => run.countedForStability === true).map(record => ({ record, measurementGroup }));
});
if (measured.length < 2) throw new Error('Two valid measured attempts are required');
const db = new PrismaClient({ datasources: { db: { url } } });
const config = artifacts.mergeArtifactPipelineConfig({ storage: { rootDir: root, provider: 'localfs', bucket: null }, analysisMaxConcurrent: 1, maxPendingAnalyses: 10, analysisPollIntervalMs: 250 });
const store = artifacts.createPrismaArtifactPipelinePersistence(db, config);
// No derived recomputation: validation-only observations must never fit a public frontier.
const service = new artifacts.ArtifactPipelineService(store, new artifacts.FfmpegArtifactAnalyzer(artifacts.DEFAULT_ANALYZER_VERSION), config, suite.loadAuthoritativeSuiteManifest(), async () => {});
const result = { schemaVersion: 'encodingdb-controlled-validation-import/v1', validationOnly: true, sourceRegistrationHash: hash(source), runs: [] };
try {
  const protocol = await db.benchmarkProtocol.upsert({ where: { protocolVersion_sourceSuiteVersion_metricWorkerVersion: { protocolVersion: '7.1', sourceSuiteVersion: sources.VALIDATION_SOURCE_SUITE, metricWorkerVersion: artifacts.DEFAULT_ANALYZER_VERSION } },
    create: { protocolVersion: '7.1', sourceSuiteVersion: sources.VALIDATION_SOURCE_SUITE, minimumClientVersion: 'client/0.3.0', canonicalRecipeRules: { validationOnly: true, warmupRuns: 1, minimumMeasuredRuns: 2 }, canonicalOutputRules: { singleVideoStream: true, noAudio: true }, metricWorkerVersion: artifacts.DEFAULT_ANALYZER_VERSION }, update: {} });
  const clipData = { suiteId: sources.VALIDATION_SOURCE_SUITE, suiteVersion: sources.VALIDATION_SOURCE_SUITE, manifestVersion: 'validation-source/v1', clipKey: source.workloadId, displayName: source.workloadId, workloadId: source.workloadId, contentClass: source.contentClass,
    sourceProvenance: { fileName: `${source.workloadId}.mkv`, referencePath: receipt.referencePath, validationSource: source, validationSourceHash: hash(source) }, sha256: source.sourceSha256, byteSize: source.byteSize, exactFrameCount: source.frameCount, exactDurationSeconds: source.durationSeconds,
    frameRateNumerator: 24, frameRateDenominator: 1, width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', colorPrimaries: 'bt709', transferCharacteristics: 'bt709', matrixCoefficients: 'bt709', colorRange: 'tv' };
  const clip = await db.testClip.upsert({ where: { sha256: source.sourceSha256 }, create: clipData, update: {} });
  if (clip.suiteVersion !== sources.VALIDATION_SOURCE_SUITE || hash(clip.sourceProvenance.validationSource) !== hash(source)) throw new Error('Existing TestClip is not the same immutable validation registration');
  const environmentJson = { hardware: receipt.hardware, runtime: receipt.runtime, execution: receipt.execution, osName: receipt.osName, osVersion: receipt.osVersion };
  const environment = await db.environment.upsert({ where: { fingerprint: hash(environmentJson) }, create: {
    fingerprint: hash(environmentJson), canonicalJson: environmentJson, cpuModel: receipt.hardware.cpuModel, cpuArchitecture: receipt.runtime.clientExecutionArchitecture,
    gpuModel: receipt.hardware.gpuModel ?? null, osName: receipt.osName, osVersion: receipt.osVersion, ffmpegBuildFingerprint: receipt.runtime.ffmpeg.sha256,
    ffmpegVersion: receipt.ffmpegVersion, clientVersion: receipt.clientVersion, runtimeIdentity: receipt.runtime,
  }, update: {} });
  for (const { record, measurementGroup } of measured) {
    const info = record.metadata.info;
    if (info.encodeTimerBoundary !== 'ffmpeg-process-v1' || await hashFile(info.artifactPath) !== info.artifactSha256) throw new Error('Measured artifact or corrected timer differs from journal');
    const recipeJson = JSON.parse(info.effectiveRecipeJson);
    const requested = recipeJson.rateControlRequested; const effective = recipeJson.rateControlEffective;
    if (requested.mode !== 'crf' || effective.mode !== 'crf') throw new Error('This first controlled runner supports explicit software CRF only');
    const recipe = await db.recipe.upsert({ where: { fingerprint: hash(recipeJson) }, create: {
      fingerprint: hash(recipeJson), canonicalJson: recipeJson, codecFamily: recipeJson.codecFamily, encoderImplementation: info.encoderUsed,
      preset: info.presetUsed, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', containerFormat: 'mp4',
      requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedQualityValue: requested.qualityValue, effectiveQualityValue: effective.qualityValue,
      requestedRateControl: requested, effectiveRateControl: effective,
    }, update: {} });
    const timing = record.timing;
    const measuredElapsed = (timing.end_monotonic_ns - timing.start_monotonic_ns) / 1e9;
    if (Math.abs(measuredElapsed - timing.elapsed_s) > 0.000001) throw new Error('Timing tuple differs from measured monotonic interval');
    artifacts.validateCanonicalTiming({ encodeTimerBoundary: info.encodeTimerBoundary, physicalSourceId: receipt.physicalSourceId, inputHash: source.sourceSha256, sourceFrameCount: timing.source_frame_count, encodedFrameCount: timing.encoded_frame_count, sourceFps: timing.source_fps, encodeWallTimeMs: timing.elapsed_s * 1000, encodeFps: timing.encode_fps, realTimeRatio: timing.realtime_multiple }, clip);
    const immutable = { schedule: record.schedule, timing, measurementGroup, recipe: recipe.fingerprint, environment: environment.fingerprint, source: hash(source), physicalSourceId: receipt.physicalSourceId, artifact: info.artifactSha256 };
    const id = `validation_${hash(record.schedule)}`;
    const existing = await db.benchmarkRun.findUnique({ where: { id } });
    if (existing && existing.payloadHash !== hash(immutable)) throw new Error('Validation attempt ID was reused with different contents');
    const run = await db.benchmarkRun.upsert({ where: { id }, create: { id, benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: source.workloadId, recipeId: recipe.id, environmentId: environment.id,
      payloadHash: hash(immutable), immutablePayloadHash: hash(immutable), physicalSourceId: receipt.physicalSourceId, encodeTimerBoundary: 'ffmpeg-process-v1', inputHash: source.sourceSha256,
      campaignId: record.schedule.campaign_id, repetitionGroupId: `${record.schedule.campaign_id}:${record.schedule.recipe_id}`, repetitionIndex: record.schedule.repetition_index,
      encodeWallTimeMs: timing.elapsed_s * 1000, encodeFps: timing.encode_fps, sourceFps: timing.source_fps, realTimeRatio: timing.realtime_multiple, sourceFrameCount: timing.source_frame_count, encodedFrameCount: timing.encoded_frame_count,
      preRunEnvironmentCheck: { snapshot: record.environmentSnapshot, overallValidity: record.overallValidity, environmentValidity: record.environmentValidity, structuralValidity: record.structuralValidity, measurementGroup }, clientQualityDebug: { validationOnly: true, rawJournalRecord: record }, status: 'PENDING' }, update: {} });
    const key = path.join('objects', info.artifactSha256.slice(0, 2), info.artifactSha256); const destination = path.join(root, key);
    await mkdir(path.dirname(destination), { recursive: true });
    const temporary = `${destination}.${process.pid}.partial`; await copyFile(info.artifactPath, temporary);
    if (await hashFile(temporary) !== info.artifactSha256) throw new Error('Copied artifact hash mismatch');
    await rename(temporary, destination);
    await db.artifact.upsert({ where: { benchmarkRunId_role: { benchmarkRunId: run.id, role: 'ENCODED' } }, create: { benchmarkRunId: run.id, role: 'ENCODED', sha256: info.artifactSha256, byteSize: (await stat(destination)).size, storageState: 'UPLOADED', storageProvider: 'localfs', storageKey: key, storageUrl: destination, uploadedAt: new Date() }, update: {} });
    await service.queueAuthoritativeAnalysis(run.id, artifacts.DEFAULT_ANALYZER_VERSION, 'vmaf-v1-sdr-1080p');
    const deadline = Date.now() + 30 * 60 * 1000;
    let analysis;
    do {
      analysis = await db.qualityAnalysis.findFirst({ where: { benchmarkRunId: run.id, analysisWorkerVersion: artifacts.DEFAULT_ANALYZER_VERSION }, orderBy: [{ createdAt: 'desc' }, { id: 'desc' }] });
      if (analysis && !['PENDING', 'FAILED'].includes(analysis.status)) break;
      if (analysis?.status === 'FAILED' && !analysis.nextRetryAt) throw new Error(`Authoritative validation analysis failed: ${analysis.lastError}`);
      if (Date.now() > deadline) throw new Error('Authoritative validation analysis deadline expired; durable queue retained');
      await new Promise(resolve => setTimeout(resolve, 500));
    } while (true);
    result.runs.push({ benchmarkRunId: run.id, qualityAnalysisId: analysis.id, artifactSha256: info.artifactSha256, analysisStatus: analysis.status, metricFrameCount: analysis.vmafDistribution?.frameCount });
    await writeFile(path.join(root, 'validation-import-receipt.json'), `${JSON.stringify(result, null, 2)}\n`);
  }
} finally { await service.stopBackgroundWork(); await db.$disconnect(); }
console.log(JSON.stringify(result, null, 2));
