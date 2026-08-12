import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import net from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { createArtifactPipelineRouter } from '../dist/v7/artifacts.js';
import { createDefaultDerivedRecomputeCallback } from '../dist/v7/artifacts.js';
import {
  DEFAULT_ANALYZER_VERSION,
  SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
  SERVER_CANONICAL_OUTPUT_RULES,
  SERVER_CANONICAL_PROTOCOL_VERSION,
  SERVER_CANONICAL_RECIPE_RULES,
} from '../dist/v7/artifacts.js';
import {
  buildEnvironmentFingerprint,
  buildRecipeFingerprint,
} from '../dist/v7/persistence.js';
import { loadAuthoritativeSuiteManifest } from '../dist/v7/suite.js';

const ARTIFACT_BYTES = Buffer.from('artifact-data');
const ARTIFACT_SHA256 = '682709f36991fd3910d7343e6264dd5510bf02005fa6503a4878ff17530751d8';
const SUITE_MANIFEST = loadAuthoritativeSuiteManifest();
const PRIMARY_CLIP = SUITE_MANIFEST.clips[0];

const CAN_BIND_LOOPBACK = await new Promise((resolve) => {
  const probe = net.createServer();
  probe.once('error', () => resolve(false));
  probe.listen(0, '127.0.0.1', () => {
    probe.close(() => resolve(true));
  });
});

function createFixtureCatalog() {
  const recipeIdentity = {
    codecFamily: 'h264',
    encoderImplementation: 'libx264',
    preset: 'medium',
    pixelFormat: 'yuv420p',
    bitDepth: 8,
    chromaSubsampling: '4:2:0',
    containerFormat: 'mp4',
    requestedRateControl: {
      mode: 'crf',
      qualityValue: 23,
    },
    effectiveRateControl: {
      mode: 'crf',
      qualityValue: 23,
    },
  };
  const environmentIdentity = {
    cpuModel: 'Test CPU',
    cpuArchitecture: 'x86_64',
    osName: 'TestOS',
    osVersion: '1.0',
    ffmpegBuildFingerprint: 'ffmpeg-build-test',
    ffmpegVersion: 'n7.1',
    clientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
  };
  return {
    protocol: {
      protocolVersion: SERVER_CANONICAL_PROTOCOL_VERSION,
      sourceSuiteVersion: SUITE_MANIFEST.suiteVersion,
      minimumClientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
      metricWorkerVersion: DEFAULT_ANALYZER_VERSION,
      canonicalRecipeRules: SERVER_CANONICAL_RECIPE_RULES,
      canonicalOutputRules: SERVER_CANONICAL_OUTPUT_RULES,
      state: 'ACTIVE',
    },
    suiteManifest: SUITE_MANIFEST,
    clip: PRIMARY_CLIP,
    recipe: {
      identity: recipeIdentity,
      ...buildRecipeFingerprint(recipeIdentity),
    },
    environment: {
      identity: environmentIdentity,
      ...buildEnvironmentFingerprint(environmentIdentity),
    },
  };
}

class MemoryPersistence {
  constructor(fixtures) {
    this.fixtures = fixtures;
    this.protocols = new Map();
    this.testClips = new Map();
    this.recipes = new Map();
    this.environments = new Map();
    this.runs = new Map();
    this.runIdsByPayloadHash = new Map();
    this.analysisIdsByKey = new Map();
    this.nextProtocolId = 1;
    this.nextTestClipId = 1;
    this.nextRecipeId = 1;
    this.nextEnvironmentId = 1;
    this.nextRunId = 1;
    this.nextArtifactId = 1;
    this.nextAnalysisId = 1;
  }

  cloneBundle(record, role = 'ENCODED') {
    const artifact = record.artifacts.find((entry) => entry.role === role);
    assert.ok(artifact, `Missing artifact ${role}`);
    return {
      run: structuredClone(record.run),
      artifact: structuredClone(artifact),
      qualityAnalyses: structuredClone(record.qualityAnalyses),
    };
  }

  protocolKey(input) {
    return `${input.protocolVersion}:${input.sourceSuiteVersion}:${input.metricWorkerVersion}`;
  }

  async resolveOrBootstrapBenchmarkProtocol(input) {
    const key = this.protocolKey(input);
    const existing = this.protocols.get(key);
    if (existing) {
      assert.equal(JSON.stringify(existing.canonicalRecipeRules), JSON.stringify(input.canonicalRecipeRules));
      assert.equal(JSON.stringify(existing.canonicalOutputRules), JSON.stringify(input.canonicalOutputRules));
      assert.equal(existing.minimumClientVersion, input.minimumClientVersion);
      return structuredClone(existing);
    }
    const created = {
      id: `protocol-${this.nextProtocolId++}`,
      ...structuredClone(input),
      state: 'ACTIVE',
    };
    this.protocols.set(key, created);
    return structuredClone(created);
  }

  async upsertCanonicalTestClip(input) {
    const key = `${input.suiteId}:${input.suiteVersion}:${input.clipKey}`;
    const existing = this.testClips.get(key);
    const record = existing ?? {
      id: `clip-${this.nextTestClipId++}`,
      ...structuredClone(input),
    };
    this.testClips.set(key, record);
    return {
      id: record.id,
      workloadId: record.workloadId,
      displayName: record.displayName,
      sourceProvenance: record.sourceProvenance,
      exactFrameCount: record.exactFrameCount,
      exactDurationSeconds: record.exactDurationSeconds,
      frameRateNumerator: record.frameRateNumerator,
      frameRateDenominator: record.frameRateDenominator,
      width: record.width,
      height: record.height,
      pixelFormat: record.pixelFormat,
      bitDepth: record.bitDepth,
      chromaSubsampling: record.chromaSubsampling,
    };
  }

  async resolveOrBootstrapRecipe(input) {
    const fingerprint = buildRecipeFingerprint(input.identity);
    assert.equal(fingerprint.fingerprint, input.fingerprint);
    if (input.canonicalJson !== undefined) {
      assert.equal(JSON.stringify(JSON.parse(fingerprint.canonicalJson)), JSON.stringify(input.canonicalJson));
    }
    const existing = this.recipes.get(input.fingerprint);
    if (existing) return structuredClone(existing);
    const created = {
      id: `recipe-${this.nextRecipeId++}`,
      fingerprint: fingerprint.fingerprint,
      canonicalJson: JSON.parse(fingerprint.canonicalJson),
      codecFamily: fingerprint.normalized.codecFamily,
      encoderImplementation: fingerprint.normalized.encoderImplementation,
      pixelFormat: fingerprint.normalized.pixelFormat,
      bitDepth: fingerprint.normalized.bitDepth,
      chromaSubsampling: fingerprint.normalized.chromaSubsampling,
      containerFormat: fingerprint.normalized.containerFormat,
    };
    this.recipes.set(input.fingerprint, created);
    return structuredClone(created);
  }

  async resolveOrBootstrapEnvironment(input) {
    const fingerprint = buildEnvironmentFingerprint(input.identity);
    assert.equal(fingerprint.fingerprint, input.fingerprint);
    if (input.canonicalJson !== undefined) {
      assert.equal(JSON.stringify(JSON.parse(fingerprint.canonicalJson)), JSON.stringify(input.canonicalJson));
    }
    const existing = this.environments.get(input.fingerprint);
    if (existing) return structuredClone(existing);
    const created = {
      id: `environment-${this.nextEnvironmentId++}`,
      fingerprint: fingerprint.fingerprint,
      canonicalJson: JSON.parse(fingerprint.canonicalJson),
      clientVersion: fingerprint.normalized.clientVersion,
      ffmpegVersion: fingerprint.normalized.ffmpegVersion,
    };
    this.environments.set(input.fingerprint, created);
    return structuredClone(created);
  }

  async createOrFetchRun(input) {
    const existingRunId = this.runIdsByPayloadHash.get(input.payloadHash);
    if (existingRunId) {
      return { bundle: this.cloneBundle(this.runs.get(existingRunId)), created: false };
    }

    const runId = `run-${this.nextRunId++}`;
    const artifactId = `artifact-${this.nextArtifactId++}`;
    const run = {
      id: runId,
      benchmarkProtocolId: input.benchmarkProtocolId,
      testClipId: input.testClipId,
      workloadId: input.workloadId,
      recipeId: input.recipeId,
      environmentId: input.environmentId,
      payloadHash: input.payloadHash,
      inputHash: input.inputHash ?? null,
      campaignId: input.campaignId ?? null,
      repetitionGroupId: input.repetitionGroupId ?? null,
      repetitionIndex: input.repetitionIndex ?? null,
      encodeWallTimeMs: input.encodeWallTimeMs ?? null,
      encodeFps: input.encodeFps ?? null,
      sourceFps: input.sourceFps ?? null,
      realTimeRatio: input.realTimeRatio ?? null,
      sourceFrameCount: input.sourceFrameCount ?? null,
      encodedFrameCount: input.encodedFrameCount ?? null,
      telemetry: input.telemetry ?? null,
      telemetrySources: input.telemetrySources ?? null,
      telemetryMissing: input.telemetryMissing ?? null,
      energyDomains: input.energyDomains ?? null,
      decodeBenchmark: input.decodeBenchmark ?? null,
      preRunEnvironmentCheck: input.preRunEnvironmentCheck ?? null,
      ffmpegProgressTelemetry: input.ffmpegProgressTelemetry ?? null,
      clientQualityDebug: input.clientQualityDebug ?? null,
      status: 'PENDING',
      statusReason: null,
      benchmarkProtocol: [...this.protocols.values()].find((entry) => entry.id === input.benchmarkProtocolId),
      testClip: [...this.testClips.values()].find((entry) => entry.id === input.testClipId),
      recipe: [...this.recipes.values()].find((entry) => entry.id === input.recipeId),
      environment: [...this.environments.values()].find((entry) => entry.id === input.environmentId),
    };
    const artifact = {
      id: artifactId,
      benchmarkRunId: runId,
      role: input.artifact.role,
      sha256: input.artifact.sha256,
      byteSize: input.artifact.byteSize,
      storageState: 'PENDING',
      storageProvider: null,
      storageBucket: null,
      storageKey: null,
      storageUrl: null,
      mediaContainer: input.artifact.mediaContainer ?? null,
      stateReason: null,
      stateDetails: null,
      uploadedAt: null,
      verifiedAt: null,
      retainedAt: null,
      deletedAt: null,
    };
    const record = { run, artifacts: [artifact], qualityAnalyses: [] };
    this.runs.set(runId, record);
    this.runIdsByPayloadHash.set(input.payloadHash, runId);
    return { bundle: this.cloneBundle(record), created: true };
  }

  async getRunArtifact(benchmarkRunId, role) {
    const record = this.runs.get(benchmarkRunId);
    return record ? this.cloneBundle(record, role) : null;
  }

  async getArtifactBySha256(sha256) {
    for (const record of this.runs.values()) {
      for (const artifact of record.artifacts) {
        if (artifact.sha256 === sha256) return structuredClone(artifact);
      }
    }
    return null;
  }

  async markArtifactUploaded(input) {
    const record = this.runs.get(this.findRunIdByArtifactId(input.artifactId));
    const artifact = record.artifacts.find((entry) => entry.id === input.artifactId);
    Object.assign(artifact, {
      sha256: input.sha256,
      byteSize: input.byteSize,
      mediaContainer: input.mediaContainer,
      storageState: 'UPLOADED',
      storageProvider: input.storageProvider,
      storageBucket: input.storageBucket,
      storageKey: input.storageKey,
      storageUrl: input.storageUrl,
      stateReason: null,
      stateDetails: input.stateDetails ?? null,
      uploadedAt: new Date(),
    });
    return this.cloneBundle(record);
  }

  async markArtifactState(input) {
    const record = this.runs.get(this.findRunIdByArtifactId(input.artifactId));
    const artifact = record.artifacts.find((entry) => entry.id === input.artifactId);
    artifact.storageState = input.storageState;
    artifact.stateReason = input.stateReason ?? null;
    artifact.stateDetails = input.stateDetails ?? null;
    if (input.storageState === 'VERIFIED') artifact.verifiedAt = new Date();
    if (input.storageState === 'RETAINED') artifact.retainedAt = new Date();
    if (input.storageState === 'DELETED') artifact.deletedAt = new Date();
    return this.cloneBundle(record);
  }

  async getQualityAnalysis(benchmarkRunId, metricModelId, analysisWorkerVersion) {
    const record = this.runs.get(benchmarkRunId);
    return structuredClone(
      record?.qualityAnalyses.find((entry) => (
        entry.metricModelId === metricModelId && entry.analysisWorkerVersion === analysisWorkerVersion
      )) ?? null,
    );
  }

  async saveAuthoritativeAnalysis(input) {
    const record = this.runs.get(input.benchmarkRunId);
    const key = `${input.benchmarkRunId}:${input.result.metricModelId}:${input.result.analysisWorkerVersion}`;
    const existingId = this.analysisIdsByKey.get(key);
    const now = new Date();
    if (existingId) {
      const analysis = record.qualityAnalyses.find((entry) => entry.id === existingId);
      Object.assign(analysis, structuredClone(input.result), {
        id: existingId,
        benchmarkRunId: input.benchmarkRunId,
        artifactId: input.artifactId,
        createdAt: analysis.createdAt,
        updatedAt: now,
      });
    } else {
      const id = `analysis-${this.nextAnalysisId++}`;
      this.analysisIdsByKey.set(key, id);
      record.qualityAnalyses.push({
        id,
        benchmarkRunId: input.benchmarkRunId,
        artifactId: input.artifactId,
        createdAt: now,
        updatedAt: now,
        ...structuredClone(input.result),
      });
    }

    const artifact = record.artifacts.find((entry) => entry.id === input.artifactId);
    record.run.status = input.result.runStatus;
    record.run.statusReason = input.result.runStatusReason ?? null;
    artifact.storageState = input.result.artifactState;
    artifact.stateReason = input.result.artifactStateReason ?? null;
    artifact.stateDetails = input.result.artifactStateDetails ?? null;
    artifact.verifiedAt = artifact.verifiedAt ?? new Date();
    if (input.result.artifactState === 'RETAINED') {
      artifact.retainedAt = new Date();
    }
    return this.cloneBundle(record);
  }

  findRunIdByArtifactId(artifactId) {
    for (const [runId, record] of this.runs.entries()) {
      if (record.artifacts.some((artifact) => artifact.id === artifactId)) return runId;
    }
    throw new Error(`Unknown artifact ${artifactId}`);
  }
}

class FakeAnalyzer {
  constructor() {
    this.calls = [];
  }

  async analyze(input) {
    const version = input.requestedAnalysisWorkerVersion || 'worker-v1';
    this.calls.push({
      runId: input.bundle.run.id,
      version,
      clientQualityDebug: structuredClone(input.bundle.run.clientQualityDebug),
    });
    const vmafMean = version === 'worker-v2' ? 97.25 : 95.25;
    const vmafP5 = version === 'worker-v2' ? 92.25 : 90.25;
    return {
      metricModelId: 'vmaf-v1-sdr-sd',
      qualityContextId: 'vmaf-v1-sdr-sd-yuv420p10le',
      analysisWorkerVersion: version,
      analysisStatus: 'COMPLETE',
      analysisProvenance: {
        pipelineVersion: 'test',
        workerVersion: version,
      },
      vmafMean,
      vmafMedian: vmafMean,
      vmafP1: vmafP5 - 2,
      vmafP5,
      vmafMin: vmafP5 - 4,
      vmafMax: vmafMean + 1,
      vmafStdDev: 1.5,
      vmafHarmonicMean: vmafMean - 0.25,
      worstFrameIndex: 12,
      worstFrameTimestampMs: 500,
      belowThresholdFractions: { '90.000000': { threshold: 90, count: 0, fraction: 0 } },
      vmafDistribution: { frameCount: 3, frames: [{ frameIndex: 0, timestampMs: 0, score: vmafMean }] },
      xpsnr: 41.5,
      ssim: 0.992,
      psnr: 45.1,
      videoBitrateBps: 2_222_222,
      videoPayloadBytes: 833_333,
      videoPacketCount: 72,
      measuredDurationSeconds: 3,
      bitrateMethod: 'ffprobe-video-packet-size-sum',
      containerBitrateBps: 2_333_333,
      fileSizeBytes: ARTIFACT_BYTES.length,
      runStatus: 'ACCEPTED',
      runStatusReason: null,
      artifactState: 'RETAINED',
      artifactStateReason: null,
      artifactStateDetails: {
        retainedBecause: 'accepted-corpus-small',
      },
    };
  }
}

async function startServer(router) {
  const app = express();
  app.use(express.json({ limit: '1mb' }));
  app.use(router);
  const server = await new Promise((resolve) => {
    const instance = app.listen(0, '127.0.0.1', () => resolve(instance));
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Unexpected server address');
  return {
    server,
    baseUrl: `http://127.0.0.1:${address.port}`,
  };
}

async function createHarness(configOverrides = {}) {
  const fixtures = createFixtureCatalog();
  const persistence = new MemoryPersistence(fixtures);
  const analyzer = new FakeAnalyzer();
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-artifacts-test-'));
  const router = createArtifactPipelineRouter({
    persistence,
    analyzer,
    suiteManifest: fixtures.suiteManifest,
    onDerivedRecompute: async () => {},
    config: {
      uploadTokenSecret: 'test-secret',
      uploadTokenTtlMs: 30_000,
      maxArtifactBytes: 1024,
      allowedMimeTypes: new Set(['video/mp4']),
      authRateLimitWindowMs: 60_000,
      authRateLimitMax: 20,
      uploadRateLimitWindowMs: 60_000,
      uploadRateLimitMax: 20,
      storage: {
        rootDir: tempRoot,
        provider: 'localfs',
        bucket: null,
      },
      analyzerVersion: 'worker-v1',
      autoAnalyzeOnUpload: true,
      ...configOverrides,
    },
  });
  const http = await startServer(router);
  return {
    ...http,
    fixtures,
    persistence,
    analyzer,
    tempRoot,
    async close() {
      await new Promise((resolve) => http.server.close(resolve));
      await rm(tempRoot, { recursive: true, force: true });
    },
  };
}

async function createRun(baseUrl, fixtures, overrides = {}) {
  const body = {
    benchmarkProtocol: {
      protocolVersion: fixtures.protocol.protocolVersion,
      sourceSuiteVersion: fixtures.protocol.sourceSuiteVersion,
      minimumClientVersion: fixtures.protocol.minimumClientVersion,
      canonicalRecipeRules: fixtures.protocol.canonicalRecipeRules,
      canonicalOutputRules: fixtures.protocol.canonicalOutputRules,
      metricWorkerVersion: fixtures.protocol.metricWorkerVersion,
    },
	    testClip: {
	      suiteId: fixtures.suiteManifest.suiteId,
	      suiteVersion: fixtures.suiteManifest.suiteVersion,
	      clipKey: fixtures.clip.id,
	      sha256: fixtures.clip.sha256,
	      workloadId: fixtures.clip.workloadId,
	    },
    recipe: {
      fingerprint: fixtures.recipe.fingerprint,
      canonicalJson: JSON.parse(fixtures.recipe.canonicalJson),
      identity: fixtures.recipe.identity,
    },
    environment: {
      fingerprint: fixtures.environment.fingerprint,
      canonicalJson: JSON.parse(fixtures.environment.canonicalJson),
      identity: fixtures.environment.identity,
    },
    payloadHash: overrides.payloadHash || 'a'.repeat(64),
	    workloadId: fixtures.clip.workloadId,
    expectedMetricModelId: 'vmaf-v1-sdr-sd',
    inputHash: 'b'.repeat(64),
    encodeWallTimeMs: 10_000,
    encodeFps: 120,
    sourceFps: 24,
    realTimeRatio: 5,
    sourceFrameCount: 240,
    encodedFrameCount: 240,
    energyDomains: overrides.energyDomains,
    decodeBenchmark: overrides.decodeBenchmark,
    clientQualityDebug: overrides.clientQualityDebug ?? { vmafMean: 1.0, vmafP5: 0.5 },
    artifact: {
      role: 'ENCODED',
      sha256: overrides.sha256 || ARTIFACT_SHA256,
      byteSize: overrides.byteSize || ARTIFACT_BYTES.length,
      mediaContainer: 'mp4',
    },
  };
  const response = await fetch(`${baseUrl}/v7/benchmark-runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = await response.json();
  return { response, json, body };
}

test('run creation validates and persists canonical energy domains and decode evidence', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('loopback bind unavailable');
  const harness = await createHarness();
  t.after(() => harness.close());

  const created = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: 'e'.repeat(64),
    energyDomains: [{
      domain: 'gpu-board',
      domainLabel: 'gpu-board:0',
      collector: 'nvml-total-energy',
      collectorVersion: 'pynvml',
      source: 'nvml-total-energy',
      counterUnit: 'millijoules',
      counterState: 'valid',
      startCounter: 10,
      endCounter: 1010,
    }],
    decodeBenchmark: {
      status: 'complete',
      decoderImplementation: 'ffmpeg-software-default',
      decoderVersion: 'n7.1',
      toolchainFingerprint: 'environment-fingerprint',
      executionMode: 'software',
      cacheDiscipline: 'documented',
      wallTimeMs: 2000,
      decodeFps: 120,
      sourceFps: 24,
      cpuTimeMs: 1500,
      notes: 'ffmpeg-software-decode-v1',
    },
  });

  assert.equal(created.response.status, 201);
  assert.equal(created.json.benchmarkRun.energyDomains[0].deltaJoules, 1);
  assert.equal(created.json.benchmarkRun.energyDomains[0].joulesPerFrame, 0.004166667);
  assert.equal(created.json.benchmarkRun.decodeBenchmark.status, 'complete');
  assert.equal(created.json.benchmarkRun.decodeBenchmark.realTimeMultiple, 5);
  const stored = [...harness.persistence.runs.values()][0].run;
  assert.deepEqual(stored.energyDomains, created.json.benchmarkRun.energyDomains);
  assert.deepEqual(stored.decodeBenchmark, created.json.benchmarkRun.decodeBenchmark);
});

test('run creation rejects mislabeled energy/decode evidence instead of storing arbitrary JSON', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('loopback bind unavailable');
  const harness = await createHarness();
  t.after(() => harness.close());

  const rejected = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: 'd'.repeat(64),
    energyDomains: [{
      domain: 'gpu-board',
      domainLabel: 'gpu-board:0',
      collector: 'nvml',
      counterUnit: 'watts',
      counterState: 'valid',
      startCounter: 1,
      endCounter: 2,
    }],
    decodeBenchmark: {
      status: 'complete',
      decodeFps: 120,
      sourceFps: 24,
    },
  });

  assert.equal(rejected.response.status, 400);
  assert.match(rejected.json.error, /Invalid telemetry evidence/);
  assert.equal(harness.persistence.runs.size, 0);
});

test('artifact upload stores client quality as debug only and returns authoritative server analysis', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const harness = await createHarness();
  t.after(async () => {
    await harness.close();
  });

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const run = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '1'.repeat(64),
    clientQualityDebug: { vmafMean: 0.1, vmafP5: 0.05, source: 'client-debug' },
    sha256,
    byteSize: uploadBytes.length,
  });
  assert.equal(run.response.status, 201);
  assert.equal(run.json.created, true);

  const authResponse = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      sha256,
      byteSize: uploadBytes.length,
      contentType: 'video/mp4',
    }),
  });
  assert.equal(authResponse.status, 200);
  const authJson = await authResponse.json();
  assert.equal(authJson.uploadRequired, true);

  const uploadResponse = await fetch(`${harness.baseUrl}/v7/artifact-uploads/${authJson.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: uploadBytes,
  });
  assert.equal(uploadResponse.status, 200);
  const uploadJson = await uploadResponse.json();
  assert.equal(uploadJson.benchmarkRun.clientQualityDebug.vmafMean, 0.1);
  assert.equal(uploadJson.analyses.length, 1);
  assert.equal(uploadJson.analyses[0].vmafMean, 95.25);
  assert.equal(uploadJson.analyses[0].vmafP5, 90.25);
  assert.equal(uploadJson.artifact.storageState, 'RETAINED');
  assert.equal(uploadJson.benchmarkRun.status, 'ACCEPTED');
  assert.equal(harness.analyzer.calls.length, 1);
  assert.equal(harness.analyzer.calls[0].clientQualityDebug.vmafMean, 0.1);
});

test('duplicate payloads and upload retries remain idempotent without duplicating analyses', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const harness = await createHarness();
  t.after(async () => {
    await harness.close();
  });

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const firstCreate = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '2'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  const secondCreate = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '2'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  assert.equal(secondCreate.response.status, 200);
  assert.equal(secondCreate.json.created, false);
  assert.equal(secondCreate.json.benchmarkRun.id, firstCreate.json.benchmarkRun.id);

  const authResponse = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${firstCreate.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256, byteSize: uploadBytes.length, contentType: 'video/mp4' }),
  });
  const authJson = await authResponse.json();

  const firstUpload = await fetch(`${harness.baseUrl}/v7/artifact-uploads/${authJson.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: uploadBytes,
  });
  assert.equal(firstUpload.status, 200);

  const retryUpload = await fetch(`${harness.baseUrl}/v7/artifact-uploads/${authJson.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: uploadBytes,
  });
  assert.equal(retryUpload.status, 200);
  const retryJson = await retryUpload.json();
  assert.equal(retryJson.analyses.length, 1);
  assert.equal(harness.analyzer.calls.length, 1);
});

test('upload authorization enforces expiry, type, size, overwrite, and rate-ish controls', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const harness = await createHarness({
    uploadTokenTtlMs: 1,
    authRateLimitMax: 2,
    uploadRateLimitMax: 5,
    maxArtifactBytes: 16,
  });
  t.after(async () => {
    await harness.close();
  });

  const run = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '3'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });

  const tooLargeAuth = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256: ARTIFACT_SHA256, byteSize: 999, contentType: 'video/mp4' }),
  });
  assert.equal(tooLargeAuth.status, 413);

  const auth = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256: ARTIFACT_SHA256, byteSize: ARTIFACT_BYTES.length, contentType: 'video/mp4' }),
  });
  assert.equal(auth.status, 200);
  const authJson = await auth.json();

  const rateLimitedAuth = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256: ARTIFACT_SHA256, byteSize: ARTIFACT_BYTES.length, contentType: 'video/mp4' }),
  });
  assert.equal(rateLimitedAuth.status, 429);

  await new Promise((resolve) => setTimeout(resolve, 10));
  const expiredUpload = await fetch(`${harness.baseUrl}/v7/artifact-uploads/${authJson.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: ARTIFACT_BYTES,
  });
  assert.equal(expiredUpload.status, 401);

  const mismatchedTypeHarness = await createHarness();
  t.after(async () => {
    await mismatchedTypeHarness.close();
  });
  const mismatchRun = await createRun(mismatchedTypeHarness.baseUrl, mismatchedTypeHarness.fixtures, {
    payloadHash: '4'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const mismatchAuthResponse = await fetch(`${mismatchedTypeHarness.baseUrl}/v7/benchmark-runs/${mismatchRun.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256: ARTIFACT_SHA256, byteSize: ARTIFACT_BYTES.length, contentType: 'video/mp4' }),
  });
  const mismatchAuth = await mismatchAuthResponse.json();
  const mismatchedTypeUpload = await fetch(`${mismatchedTypeHarness.baseUrl}/v7/artifact-uploads/${mismatchAuth.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/octet-stream' },
    body: ARTIFACT_BYTES,
  });
  assert.equal(mismatchedTypeUpload.status, 415);

  const successfulUpload = await fetch(`${mismatchedTypeHarness.baseUrl}/v7/artifact-uploads/${mismatchAuth.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: ARTIFACT_BYTES,
  });
  assert.equal(successfulUpload.status, 200);

  const overwriteAttempt = await fetch(`${mismatchedTypeHarness.baseUrl}/v7/benchmark-runs/${mismatchRun.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256: '5f5c8f55b6cd3726e1eb3ca0c5d90f4f5efc72187eab8fdf6e8f77fca7f56d89', byteSize: ARTIFACT_BYTES.length, contentType: 'video/mp4' }),
  });
  assert.equal(overwriteAttempt.status, 409);
});

test('retained artifacts can be reanalyzed with a newer worker version while same-version jobs stay idempotent', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const harness = await createHarness();
  t.after(async () => {
    await harness.close();
  });

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const run = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '6'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  const authResponse = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/upload-authorizations`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sha256, byteSize: uploadBytes.length, contentType: 'video/mp4' }),
  });
  const authJson = await authResponse.json();
  const upload = await fetch(`${harness.baseUrl}/v7/artifact-uploads/${authJson.token}`, {
    method: 'PUT',
    headers: { 'content-type': 'video/mp4' },
    body: uploadBytes,
  });
  assert.equal(upload.status, 200);
  assert.equal(harness.analyzer.calls.length, 1);

  const idempotentReanalyze = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/reanalyze`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, metricModelId: 'vmaf-v1-sdr-sd' }),
  });
  assert.equal(idempotentReanalyze.status, 200);
  const idempotentJson = await idempotentReanalyze.json();
  assert.equal(idempotentJson.analyses.length, 1);
  assert.equal(harness.analyzer.calls.length, 1);

  const upgradedReanalyze = await fetch(`${harness.baseUrl}/v7/benchmark-runs/${run.json.benchmarkRun.id}/artifacts/ENCODED/reanalyze`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ analysisWorkerVersion: 'worker-v2', metricModelId: 'vmaf-v1-sdr-sd' }),
  });
  assert.equal(upgradedReanalyze.status, 200);
  const upgradedJson = await upgradedReanalyze.json();
  assert.equal(upgradedJson.analyses.length, 2);
  assert.equal(upgradedJson.analyses[0].analysisWorkerVersion, 'worker-v2');
  assert.equal(upgradedJson.analyses[0].vmafMean, 97.25);
  assert.equal(upgradedJson.analyses[1].analysisWorkerVersion, DEFAULT_ANALYZER_VERSION);
  assert.equal(upgradedJson.artifact.storageState, 'RETAINED');
  assert.equal(harness.analyzer.calls.length, 2);
});

test('semantic bootstrap rejects non-canonical protocol drift and minimum-client incompatibility', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const harness = await createHarness();
  t.after(async () => {
    await harness.close();
  });

  const protocolDrift = await createRun(harness.baseUrl, harness.fixtures, {
    payloadHash: '7'.repeat(64),
  });
  assert.equal(protocolDrift.response.status, 201);

  const driftResponse = await fetch(`${harness.baseUrl}/v7/benchmark-runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      ...protocolDrift.body,
      payloadHash: '8'.repeat(64),
      benchmarkProtocol: {
        ...protocolDrift.body.benchmarkProtocol,
        protocolVersion: 'EDB-2099.9',
      },
    }),
  });
  assert.equal(driftResponse.status, 409);

  const versionResponse = await fetch(`${harness.baseUrl}/v7/benchmark-runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify((() => {
      const downgradedEnvironment = buildEnvironmentFingerprint({
        ...protocolDrift.body.environment.identity,
        clientVersion: 'client/0.1.0',
      });
      return {
        ...protocolDrift.body,
        payloadHash: '9'.repeat(64),
        environment: {
          fingerprint: downgradedEnvironment.fingerprint,
          canonicalJson: JSON.parse(downgradedEnvironment.canonicalJson),
          identity: {
            ...protocolDrift.body.environment.identity,
            clientVersion: 'client/0.1.0',
          },
        },
      };
    })()),
  });
  assert.equal(versionResponse.status, 409);
});

test('default derived recompute callback persists workload derived results from authoritative analyses', async () => {
  const calls = [];
  const client = {
    benchmarkRun: {
      async findUnique() {
        return {
          id: 'run-1',
          benchmarkProtocolId: 'proto-1',
          testClipId: 'clip-1',
          workloadId: 'sports-action-960x540-24p',
          recipeId: 'recipe-1',
          environmentId: 'env-1',
          benchmarkProtocol: {
            protocolVersion: 'EDB-2026.1',
            sourceSuiteVersion: SUITE_MANIFEST.suiteVersion,
          },
          testClip: {},
          recipe: { fingerprint: 'recipe-fingerprint' },
          environment: { fingerprint: 'environment-fingerprint' },
        };
      },
    },
    scoreContext: {
      async findFirst() {
        return null;
      },
      async findMany() {
        return [{
          id: 'score-1',
          benchmarkProtocolId: 'proto-1',
          workloadId: 'sports-action-960x540-24p',
          qualityModelId: 'vmaf-v1-sdr-sd',
          formulaVersion: '7.0',
          contextVersion: 'ctx-v1',
          workloadReferenceBitrateBps: 4_000_000,
          transformConstants: {
            qualityExponent: 2.4,
            speedCurveRate: 1.2,
            speedSaturationRealtime: 4,
          },
        }];
      },
      async findFirst() {
        return null;
      },
    },
    qualityAnalysis: {
      async findMany() {
        return [{
          id: 'analysis-1',
          benchmarkRunId: 'run-1',
          status: 'COMPLETE',
          analysisWorkerVersion: 'authoritative-analysis/v1',
          updatedAt: new Date(),
          videoBitrateBps: 4_000_000,
          fileSizeBytes: 1_000_000,
          vmafMean: 95,
          vmafP5: 90,
          benchmarkRun: {
            status: 'ACCEPTED',
            encodeFps: 120,
            sourceFps: 24,
            repetitionGroupId: 'rep-1',
            environmentId: 'env-1',
          },
        }];
      },
    },
    derivedResult: {
      async upsert(args) {
        calls.push(['upsert', args]);
        return { id: 'derived-1' };
      },
    },
    derivedResultMember: {
      async deleteMany(args) {
        calls.push(['deleteMany', args]);
      },
      async createMany(args) {
        calls.push(['createMany', args]);
      },
    },
    async $transaction(fn) {
      return fn(this);
    },
  };

  const callback = createDefaultDerivedRecomputeCallback(client);
  await callback({
    benchmarkRunId: 'run-1',
    artifactId: 'artifact-1',
    metricModelId: 'vmaf-v1-sdr-sd',
    analysisWorkerVersion: 'worker-v1',
  });

  assert.deepEqual(calls.map(([name]) => name), ['upsert', 'deleteMany', 'createMany']);
  assert.equal(calls[0][1].create.workloadId, 'sports-action-960x540-24p');
  assert.equal(calls[0][1].create.scoreContext.connect.id, 'score-1');
  assert.deepEqual(calls[2][1].data, [{
    derivedResultId: 'derived-1',
    benchmarkRunId: 'run-1',
    qualityAnalysisId: 'analysis-1',
  }]);
});
