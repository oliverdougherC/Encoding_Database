import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import http from 'node:http';
import net from 'node:net';
import { Readable } from 'node:stream';
import { mkdtemp, readdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  ArtifactPipelineService,
  createArtifactPipelineRouter,
  inferBitDepth,
  inferMediaContainerFromFormatName,
  startArtifactPipelineBackgroundWork,
} from '../dist/v7/artifacts.js';
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

test('ffprobe MOV-family aliases normalize to the canonical MP4 container', () => {
  assert.equal(inferMediaContainerFromFormatName('mov,mp4,m4a,3gp,3g2,mj2'), 'mp4');
  assert.equal(inferMediaContainerFromFormatName('matroska,webm'), 'mkv');
});

test('ffprobe pixel formats infer component depth instead of chroma digits', () => {
  assert.equal(inferBitDepth('yuv420p', 0), 8);
  assert.equal(inferBitDepth('yuv422p10le', 0), 10);
  assert.equal(inferBitDepth('gbrp12le', null), 12);
  assert.equal(inferBitDepth('p010le', null), 10);
  assert.equal(inferBitDepth('yuv420p', 8), 8);
});

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
    if (input.storageState === 'REJECTED') {
      record.run.status = 'REJECTED';
      record.run.statusReason = input.stateReason ?? 'Encoded artifact rejected';
    }
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

  async ensureQualityAnalysisQueued(input) {
    const record = this.runs.get(input.benchmarkRunId);
    const now = new Date();
    const existing = record.qualityAnalyses.find((entry) => (
      entry.metricModelId === input.metricModelId && entry.analysisWorkerVersion === input.analysisWorkerVersion
    ));
    if (existing) {
      existing.status = 'PENDING';
      existing.artifactId = input.artifactId;
      existing.maxAttempts = input.maxAttempts;
      existing.nextRetryAt = now;
      existing.completedAt = null;
      existing.leaseToken = null;
      existing.leaseExpiresAt = null;
      existing.lastError = null;
      existing.lastErrorAt = null;
      existing.updatedAt = now;
    } else {
      const id = `analysis-${this.nextAnalysisId++}`;
      this.analysisIdsByKey.set(`${input.benchmarkRunId}:${input.metricModelId}:${input.analysisWorkerVersion}`, id);
      record.qualityAnalyses.push({
        id,
        benchmarkRunId: input.benchmarkRunId,
        artifactId: input.artifactId,
        createdAt: now,
        updatedAt: now,
        status: 'PENDING',
        metricModelId: input.metricModelId,
        qualityContextId: null,
        analysisWorkerVersion: input.analysisWorkerVersion,
        analysisProvenance: { queued: true },
        vmafMean: null,
        vmafMedian: null,
        vmafP1: null,
        vmafP5: null,
        vmafMin: null,
        vmafMax: null,
        vmafStdDev: null,
        vmafHarmonicMean: null,
        worstFrameIndex: null,
        worstFrameTimestampMs: null,
        belowThresholdFractions: null,
        vmafDistribution: null,
        xpsnr: null,
        ssim: null,
        psnr: null,
        videoBitrateBps: null,
        videoPayloadBytes: null,
        videoPacketCount: null,
        measuredDurationSeconds: null,
        bitrateMethod: null,
        containerBitrateBps: null,
        fileSizeBytes: null,
        attemptCount: 0,
        maxAttempts: input.maxAttempts,
        nextRetryAt: now,
        leaseToken: null,
        leaseExpiresAt: null,
        startedAt: null,
        completedAt: null,
        lastError: null,
        lastErrorAt: null,
      });
    }
    return this.cloneBundle(record);
  }

  async claimNextQueuedQualityAnalysis(input) {
    for (const record of this.runs.values()) {
      const analysis = record.qualityAnalyses.find((entry) => (
        entry.status === 'PENDING'
        && (!entry.nextRetryAt || entry.nextRetryAt <= input.now)
        && (!entry.leaseExpiresAt || entry.leaseExpiresAt <= input.now)
      ));
      if (!analysis) continue;
      analysis.attemptCount += 1;
      analysis.leaseToken = input.leaseToken;
      analysis.leaseExpiresAt = input.leaseExpiresAt;
      analysis.startedAt = input.now;
      analysis.nextRetryAt = null;
      analysis.updatedAt = new Date();
      return {
        bundle: this.cloneBundle(record),
        analysis: structuredClone(analysis),
      };
    }
    return null;
  }

  async markQualityAnalysisRetry(input) {
    const record = this.runs.get(input.benchmarkRunId);
    const analysis = record.qualityAnalyses.find((entry) => entry.id === input.analysisId);
    analysis.status = 'PENDING';
    analysis.nextRetryAt = input.nextRetryAt;
    analysis.leaseToken = null;
    analysis.leaseExpiresAt = null;
    analysis.lastError = input.errorMessage;
    analysis.lastErrorAt = new Date();
    analysis.updatedAt = new Date();
    return this.cloneBundle(record);
  }

  async markQualityAnalysisFailed(input) {
    const record = this.runs.get(input.benchmarkRunId);
    const analysis = record.qualityAnalyses.find((entry) => entry.id === input.analysisId);
    analysis.status = 'FAILED';
    analysis.nextRetryAt = null;
    analysis.leaseToken = null;
    analysis.leaseExpiresAt = null;
    analysis.completedAt = new Date();
    analysis.lastError = input.errorMessage;
    analysis.lastErrorAt = new Date();
    analysis.updatedAt = new Date();
    if (!record.qualityAnalyses.some((entry) => ['COMPLETE', 'SUSPECT', 'REJECTED'].includes(entry.status))) {
      record.run.status = 'INVALID';
      record.run.statusReason = input.errorMessage;
    }
    return this.cloneBundle(record);
  }

  async countArtifactsByStates(states) {
    let count = 0;
    for (const record of this.runs.values()) {
      count += record.artifacts.filter((entry) => states.includes(entry.storageState)).length;
    }
    return count;
  }

  async countQualityAnalysesByStatuses(states) {
    let count = 0;
    for (const record of this.runs.values()) {
      count += record.qualityAnalyses.filter((entry) => states.includes(entry.status)).length;
    }
    return count;
  }

  async sumArtifactBytesByStates(states) {
    let total = 0;
    for (const record of this.runs.values()) {
      for (const artifact of record.artifacts) {
        if (states.includes(artifact.storageState)) total += artifact.byteSize ?? 0;
      }
    }
    return total;
  }

  async saveAuthoritativeAnalysis(input) {
    const record = this.runs.get(input.benchmarkRunId);
    const now = new Date();
    const analysis = record.qualityAnalyses.find((entry) => entry.id === input.analysisId);
    Object.assign(analysis, structuredClone(input.result), {
      id: input.analysisId,
      benchmarkRunId: input.benchmarkRunId,
      artifactId: input.artifactId,
      status: input.result.analysisStatus,
      leaseToken: null,
      leaseExpiresAt: null,
      nextRetryAt: null,
      completedAt: now,
      lastError: null,
      lastErrorAt: null,
      updatedAt: now,
    });

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

class FailTwiceAnalyzer extends FakeAnalyzer {
  async analyze(input) {
    if (this.calls.length < 2) {
      this.calls.push({ runId: input.bundle.run.id, version: input.requestedAnalysisWorkerVersion });
      throw new Error('transient analyzer failure');
    }
    return await super.analyze(input);
  }
}

class AlwaysFailAnalyzer extends FakeAnalyzer {
  async analyze(input) {
    this.calls.push({ runId: input.bundle.run.id, version: input.requestedAnalysisWorkerVersion });
    throw new Error('authoritative analyzer is unavailable');
  }
}

class ConcurrencyTrackingAnalyzer extends FakeAnalyzer {
  constructor() {
    super();
    this.active = 0;
    this.maxActive = 0;
  }

  async analyze(input) {
    this.active += 1;
    this.maxActive = Math.max(this.maxActive, this.active);
    try {
      await new Promise((resolve) => setTimeout(resolve, 25));
      return await super.analyze(input);
    } finally {
      this.active -= 1;
    }
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
  startArtifactPipelineBackgroundWork();
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

async function waitForAnalysisState(baseUrl, benchmarkRunId, predicate, description) {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const response = await requestJson(baseUrl, `/v7/benchmark-runs/${benchmarkRunId}/artifacts/ENCODED/analysis-status`);
    assert.equal(response.status, 200);
    const json = response.json;
    if (predicate(json)) {
      return json;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Timed out waiting for ${description}`);
}

async function requestJson(baseUrl, routePath, options = {}) {
  const target = new URL(routePath, baseUrl);
  return await new Promise((resolve, reject) => {
    let settled = false;
    const req = http.request({
      method: options.method ?? 'GET',
      hostname: target.hostname,
      port: target.port,
      path: `${target.pathname}${target.search}`,
      headers: {
        connection: 'close',
        ...(options.headers ?? {}),
      },
    }, (res) => {
      const chunks = [];
      const expectedBytes = Number(res.headers['content-length'] || 0);
      const finish = () => {
        if (settled) return;
        settled = true;
        const raw = Buffer.concat(chunks).toString('utf8');
        resolve({
          status: res.statusCode ?? 0,
          json: raw ? JSON.parse(raw) : null,
        });
        res.destroy();
      };
      res.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
      res.on('data', () => {
        if (expectedBytes > 0 && Buffer.concat(chunks).byteLength >= expectedBytes) {
          finish();
        }
      });
      res.on('end', finish);
      res.setTimeout(3_000, () => {
        if (!settled) {
          settled = true;
          reject(new Error(`${options.method ?? 'GET'} ${routePath} response timed out`));
          res.destroy();
        }
      });
    });
    req.setTimeout(3_000, () => {
      if (!settled) {
        settled = true;
        req.destroy(new Error(`${options.method ?? 'GET'} ${routePath} timed out`));
      }
    });
    req.on('error', reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

async function putArtifactUpload(baseUrl, token, body, contentType) {
  return await requestJson(baseUrl, `/v7/artifact-uploads/${token}`, {
    method: 'PUT',
    headers: {
      'content-type': contentType,
      'content-length': String(body.byteLength),
    },
    body,
  });
}

function buildRunBody(fixtures, overrides = {}) {
  return {
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
}

async function createRun(baseUrl, fixtures, overrides = {}) {
  const body = buildRunBody(fixtures, overrides);
  const response = await fetch(`${baseUrl}/v7/benchmark-runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = await response.json();
  return { response, json, body };
}

async function createServiceHarness(configOverrides = {}, analyzerOverride = null, startBackground = true) {
  const fixtures = createFixtureCatalog();
  const persistence = new MemoryPersistence(fixtures);
  const analyzer = analyzerOverride ?? new FakeAnalyzer();
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-artifacts-service-test-'));
  const config = {
    uploadTokenSecret: 'test-secret',
    uploadTokenTtlMs: 30_000,
    maxArtifactBytes: 1024,
    allowedMimeTypes: new Set(['video/mp4']),
    authRateLimitWindowMs: 60_000,
    authRateLimitMax: 20,
    uploadRateLimitWindowMs: 60_000,
    uploadRateLimitMax: 20,
    maxConcurrentUploads: 4,
    maxPendingArtifacts: 100,
    maxPendingAnalyses: 100,
    storage: {
      rootDir: tempRoot,
      provider: 'localfs',
      bucket: null,
    },
    storageQuotaBytes: null,
    storageReserveBytes: 0,
    analyzerVersion: 'worker-v1',
    autoAnalyzeOnUpload: true,
    validateMediaBeforePublish: false,
    analysisPollIntervalMs: 10,
    analysisLeaseMs: 5_000,
    analysisRetryBackoffMs: 25,
    analysisMaxAttempts: 3,
    analysisMaxConcurrent: 2,
    ...configOverrides,
  };
  const service = new ArtifactPipelineService(
    persistence,
    analyzer,
    config,
    fixtures.suiteManifest,
    async () => {},
  );
  if (startBackground) service.startBackgroundWork();
  return {
    fixtures,
    persistence,
    analyzer,
    service,
    config,
    tempRoot,
    async close() {
      await rm(tempRoot, { recursive: true, force: true });
    },
  };
}

async function createRunDirect(service, fixtures, overrides = {}) {
  const body = buildRunBody(fixtures, overrides);
  return {
    body,
    ...(await service.createRun(body)),
  };
}

async function waitForBundleAnalysisState(service, benchmarkRunId, predicate, description) {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const bundle = await service.getBundle(benchmarkRunId, 'ENCODED');
    if (bundle && predicate(bundle)) {
      return bundle;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Timed out waiting for ${description}`);
}

async function assertNoStagedUploads(tempRoot) {
  const stagingRoot = path.join(tempRoot, '.staging');
  const entries = await readdir(stagingRoot).catch((error) => {
    if (error?.code === 'ENOENT') return [];
    throw error;
  });
  assert.deepEqual(entries, []);
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
  const harness = await createServiceHarness();
  t.after(() => harness.close());

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '1'.repeat(64),
    clientQualityDebug: { vmafMean: 0.1, vmafP5: 0.05, source: 'client-debug' },
    sha256,
    byteSize: uploadBytes.length,
  });
  assert.equal(run.created, true);

  const authJson = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256,
    byteSize: uploadBytes.length,
    contentType: 'video/mp4',
  });
  assert.equal(authJson.uploadRequired, true);

  const queuedBundle = await harness.service.acceptUploadStream(
    '127.0.0.1',
    authJson.token,
    'video/mp4',
    String(uploadBytes.length),
    Readable.from([uploadBytes]),
  );
  assert.equal(queuedBundle.run.clientQualityDebug.vmafMean, 0.1);
  assert.equal(queuedBundle.qualityAnalyses[0].status, 'PENDING');
  const uploadBundle = await waitForBundleAnalysisState(
    harness.service,
    run.bundle.run.id,
    (value) => value.qualityAnalyses.length === 1 && value.qualityAnalyses[0].status === 'COMPLETE',
    'initial authoritative analysis completion',
  );
  assert.equal(uploadBundle.qualityAnalyses[0].vmafMean, 95.25);
  assert.equal(uploadBundle.qualityAnalyses[0].vmafP5, 90.25);
  assert.equal(uploadBundle.artifact.storageState, 'RETAINED');
  assert.equal(uploadBundle.run.status, 'ACCEPTED');
  assert.equal(harness.analyzer.calls.length, 1);
  assert.equal(harness.analyzer.calls[0].clientQualityDebug.vmafMean, 0.1);
});

test('artifact upload is incrementally streamed across multiple chunks', async (t) => {
  const harness = await createServiceHarness();
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '9'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  const chunks = [ARTIFACT_BYTES.subarray(0, 2), ARTIFACT_BYTES.subarray(2, 7), ARTIFACT_BYTES.subarray(7)];
  const queued = await harness.service.acceptUploadStream(
    '127.0.0.1',
    authorization.token,
    'video/mp4',
    String(ARTIFACT_BYTES.length),
    Readable.from(chunks),
  );
  assert.equal(queued.artifact.storageState, 'UPLOADED');
  assert.equal(queued.qualityAnalyses[0].status, 'PENDING');
  await assertNoStagedUploads(harness.tempRoot);
});

test('truncated, hash-mismatched, and disconnected streams never publish retained evidence', async (t) => {
  for (const scenario of [
    {
      name: 'truncated',
      payloadHash: 'a'.repeat(63) + '1',
      stream: () => Readable.from([ARTIFACT_BYTES.subarray(0, ARTIFACT_BYTES.length - 1)]),
      pattern: /byte size does not match authorization/,
    },
    {
      name: 'hash mismatch',
      payloadHash: 'a'.repeat(63) + '2',
      stream: () => Readable.from([Buffer.from('artifact-datb')]),
      pattern: /sha256 does not match authorization/,
    },
    {
      name: 'disconnect',
      payloadHash: 'a'.repeat(63) + '3',
      stream: () => Readable.from((async function* disconnectedUpload() {
        yield ARTIFACT_BYTES.subarray(0, 4);
        throw new Error('client disconnected');
      })()),
      pattern: /client disconnected/,
    },
  ]) {
    const harness = await createServiceHarness();
    t.after(() => harness.close());
    const run = await createRunDirect(harness.service, harness.fixtures, {
      payloadHash: scenario.payloadHash,
      sha256: ARTIFACT_SHA256,
      byteSize: ARTIFACT_BYTES.length,
    });
    const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
      sha256: ARTIFACT_SHA256,
      byteSize: ARTIFACT_BYTES.length,
      contentType: 'video/mp4',
    });
    await assert.rejects(
      harness.service.acceptUploadStream(
        '127.0.0.1',
        authorization.token,
        'video/mp4',
        String(ARTIFACT_BYTES.length),
        scenario.stream(),
      ),
      scenario.pattern,
      scenario.name,
    );
    const failed = await harness.service.getBundle(run.bundle.run.id, 'ENCODED');
    assert.notEqual(failed.artifact.storageState, 'RETAINED', scenario.name);
    assert.equal(failed.qualityAnalyses.length, 0, scenario.name);
    await assertNoStagedUploads(harness.tempRoot);
  }
});

test('stream overflow stops consumption and leaves no staged or retained object', async (t) => {
  const harness = await createServiceHarness();
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: 'b'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  let producedChunks = 0;
  const source = Readable.from((async function* oversizedUpload() {
    for (const chunk of [Buffer.alloc(8), Buffer.alloc(8), Buffer.alloc(512), Buffer.alloc(512)]) {
      producedChunks += 1;
      yield chunk;
      await new Promise((resolve) => setImmediate(resolve));
    }
  })(), { highWaterMark: 1 });
  await assert.rejects(
    harness.service.acceptUploadStream('127.0.0.1', authorization.token, 'video/mp4', null, source),
    /byte size exceeds authorization/,
  );
  assert.ok(producedChunks < 4, 'overflow must abort before the complete request body is consumed');
  const failed = await harness.service.getBundle(run.bundle.run.id, 'ENCODED');
  assert.notEqual(failed.artifact.storageState, 'RETAINED');
  await assertNoStagedUploads(harness.tempRoot);
});

test('duplicate payloads and upload retries remain idempotent without duplicating analyses', async (t) => {
  const harness = await createServiceHarness();
  t.after(() => harness.close());

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const firstCreate = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '2'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  const secondCreate = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '2'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  assert.equal(secondCreate.created, false);
  assert.equal(secondCreate.bundle.run.id, firstCreate.bundle.run.id);

  const authJson = await harness.service.authorizeUpload('127.0.0.1', firstCreate.bundle.run.id, 'ENCODED', {
    sha256,
    byteSize: uploadBytes.length,
    contentType: 'video/mp4',
  });

  const firstUpload = await harness.service.acceptUploadStream(
    '127.0.0.1',
    authJson.token,
    'video/mp4',
    String(uploadBytes.length),
    Readable.from([uploadBytes]),
  );
  assert.equal(firstUpload.qualityAnalyses[0].status, 'PENDING');

  const retryUpload = await harness.service.acceptUploadStream(
    '127.0.0.1',
    authJson.token,
    'video/mp4',
    String(uploadBytes.length),
    Readable.from([uploadBytes]),
  );
  assert.ok(['PENDING', 'COMPLETE'].includes(retryUpload.qualityAnalyses[0].status));
  const completed = await waitForBundleAnalysisState(
    harness.service,
    firstCreate.bundle.run.id,
    (value) => value.qualityAnalyses.length === 1 && value.qualityAnalyses[0].status === 'COMPLETE',
    'deduplicated upload analysis completion',
  );
  assert.equal(completed.qualityAnalyses.length, 1);
  assert.equal(harness.analyzer.calls.length, 1);

  const deduplicatedRun = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: 'c'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  const deduplicatedAuthorization = await harness.service.authorizeUpload(
    '127.0.0.1',
    deduplicatedRun.bundle.run.id,
    'ENCODED',
    { sha256, byteSize: uploadBytes.length, contentType: 'video/mp4' },
  );
  assert.equal(deduplicatedAuthorization.uploadRequired, false);
  assert.equal(deduplicatedAuthorization.reason, 'deduplicated-by-sha256');
  assert.equal(deduplicatedAuthorization.artifact.storageKey, completed.artifact.storageKey);
});

test('upload authorization enforces expiry, type, size, overwrite, and rate-ish controls', async (t) => {
  const harness = await createServiceHarness({
    uploadTokenTtlMs: 1,
    authRateLimitMax: 2,
    uploadRateLimitMax: 5,
    maxArtifactBytes: 16,
  });
  t.after(() => harness.close());

  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '3'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });

  await assert.rejects(
    harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
      sha256: ARTIFACT_SHA256,
      byteSize: 999,
      contentType: 'video/mp4',
    }),
    /maximum allowed size/,
  );

  const authJson = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });

  await assert.rejects(
    harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
      sha256: ARTIFACT_SHA256,
      byteSize: ARTIFACT_BYTES.length,
      contentType: 'video/mp4',
    }),
    /rate limit/,
  );

  await new Promise((resolve) => setTimeout(resolve, 10));
  await assert.rejects(
    harness.service.acceptUploadStream('127.0.0.1', authJson.token, 'video/mp4', String(ARTIFACT_BYTES.length), Readable.from([ARTIFACT_BYTES])),
    /expired/,
  );

  const mismatchedTypeHarness = await createServiceHarness();
  t.after(() => mismatchedTypeHarness.close());
  const mismatchRun = await createRunDirect(mismatchedTypeHarness.service, mismatchedTypeHarness.fixtures, {
    payloadHash: '4'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const mismatchAuth = await mismatchedTypeHarness.service.authorizeUpload('127.0.0.1', mismatchRun.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  await assert.rejects(
    mismatchedTypeHarness.service.acceptUploadStream(
      '127.0.0.1',
      mismatchAuth.token,
      'application/octet-stream',
      String(ARTIFACT_BYTES.length),
      Readable.from([ARTIFACT_BYTES]),
    ),
    /content type does not match authorization/,
  );
  await mismatchedTypeHarness.service.acceptUploadStream(
    '127.0.0.1',
    mismatchAuth.token,
    'video/mp4',
    String(ARTIFACT_BYTES.length),
    Readable.from([ARTIFACT_BYTES]),
  );
  await waitForBundleAnalysisState(
    mismatchedTypeHarness.service,
    mismatchRun.bundle.run.id,
    (value) => value.qualityAnalyses[0]?.status === 'COMPLETE',
    'successful upload analysis completion',
  );
  await assert.rejects(
    mismatchedTypeHarness.service.authorizeUpload('127.0.0.1', mismatchRun.bundle.run.id, 'ENCODED', {
      sha256: '5f5c8f55b6cd3726e1eb3ca0c5d90f4f5efc72187eab8fdf6e8f77fca7f56d89',
      byteSize: ARTIFACT_BYTES.length,
      contentType: 'video/mp4',
    }),
    /already bound/,
  );
});

test('rejected encoded artifact makes the immutable benchmark run non-canonical', async (t) => {
  const harness = await createServiceHarness();
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '7'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  await assert.rejects(
    harness.service.acceptUploadStream(
      '127.0.0.1',
      authorization.token,
      'video/mp4',
      String(ARTIFACT_BYTES.length),
      Readable.from([ARTIFACT_BYTES.subarray(1)]),
    ),
    /byte size does not match authorization/,
  );
  const bundle = await harness.service.getBundle(run.bundle.run.id, 'ENCODED');
  assert.equal(bundle.artifact.storageState, 'REJECTED');
  assert.equal(bundle.run.status, 'REJECTED');
  assert.match(bundle.run.statusReason, /size.*match/i);
});

test('retained artifacts can be reanalyzed with a newer worker version while same-version jobs stay idempotent', async (t) => {
  const harness = await createServiceHarness();
  t.after(() => harness.close());

  const uploadBytes = ARTIFACT_BYTES;
  const sha256 = ARTIFACT_SHA256;
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '6'.repeat(64),
    sha256,
    byteSize: uploadBytes.length,
  });
  const authJson = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256,
    byteSize: uploadBytes.length,
    contentType: 'video/mp4',
  });
  await harness.service.acceptUploadStream(
    '127.0.0.1',
    authJson.token,
    'video/mp4',
    String(uploadBytes.length),
    Readable.from([uploadBytes]),
  );
  await waitForBundleAnalysisState(
    harness.service,
    run.bundle.run.id,
    (value) => value.qualityAnalyses.length === 1 && value.qualityAnalyses[0].status === 'COMPLETE',
    'baseline analysis completion before reanalyze',
  );
  assert.equal(harness.analyzer.calls.length, 1);

  const idempotentBundle = await harness.service.queueAuthoritativeAnalysis(
    run.bundle.run.id,
    DEFAULT_ANALYZER_VERSION,
    'vmaf-v1-sdr-sd',
  );
  assert.equal(idempotentBundle.qualityAnalyses.length, 1);
  assert.equal(harness.analyzer.calls.length, 1);

  await harness.service.queueAuthoritativeAnalysis(
    run.bundle.run.id,
    'worker-v2',
    'vmaf-v1-sdr-sd',
  );
  const upgradedBundle = await waitForBundleAnalysisState(
    harness.service,
    run.bundle.run.id,
    (value) => value.qualityAnalyses.some((analysis) => analysis.analysisWorkerVersion === 'worker-v2' && analysis.status === 'COMPLETE'),
    'upgraded reanalysis completion',
  );
  assert.equal(upgradedBundle.qualityAnalyses.length, 2);
  const upgradedAnalysis = upgradedBundle.qualityAnalyses.find((analysis) => analysis.analysisWorkerVersion === 'worker-v2');
  const baselineAnalysis = upgradedBundle.qualityAnalyses.find((analysis) => analysis.analysisWorkerVersion === DEFAULT_ANALYZER_VERSION);
  assert.equal(upgradedAnalysis?.vmafMean, 97.25);
  assert.ok(baselineAnalysis);
  assert.equal(upgradedBundle.artifact.storageState, 'RETAINED');
  assert.equal(harness.analyzer.calls.length, 2);
});

test('analysis maxAttempts counts executions once and permits the configured third attempt', async (t) => {
  const analyzer = new FailTwiceAnalyzer();
  const harness = await createServiceHarness({ analysisMaxAttempts: 3, analysisRetryBackoffMs: 1 }, analyzer);
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: '8'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  await harness.service.acceptUploadStream(
    '127.0.0.1',
    authorization.token,
    'video/mp4',
    String(ARTIFACT_BYTES.length),
    Readable.from([ARTIFACT_BYTES]),
  );
  const completed = await waitForBundleAnalysisState(
    harness.service,
    run.bundle.run.id,
    (value) => value.qualityAnalyses[0]?.status === 'COMPLETE',
    'third authoritative analysis attempt',
  );
  assert.equal(analyzer.calls.length, 3);
  assert.equal(completed.qualityAnalyses[0].attemptCount, 3);
  assert.equal(completed.run.status, 'ACCEPTED');
});

test('startup reconciliation resumes durable pending authoritative analysis', async (t) => {
  const harness = await createServiceHarness({ autoAnalyzeOnUpload: false }, null, false);
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: 'd'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  const uploaded = await harness.service.acceptUploadStream(
    '127.0.0.1', authorization.token, 'video/mp4', String(ARTIFACT_BYTES.length), Readable.from([ARTIFACT_BYTES]),
  );
  await harness.persistence.ensureQualityAnalysisQueued({
    benchmarkRunId: uploaded.run.id,
    artifactId: uploaded.artifact.id,
    metricModelId: 'vmaf-v1-sdr-sd',
    analysisWorkerVersion: 'worker-v1',
    maxAttempts: 3,
  });

  const restartedService = new ArtifactPipelineService(
    harness.persistence,
    harness.analyzer,
    harness.config,
    harness.fixtures.suiteManifest,
    async () => {},
  );
  restartedService.startBackgroundWork();
  const completed = await waitForBundleAnalysisState(
    restartedService,
    run.bundle.run.id,
    (value) => value.qualityAnalyses[0]?.status === 'COMPLETE',
    'reconciled authoritative analysis',
  );
  assert.equal(completed.artifact.storageState, 'RETAINED');
  assert.equal(harness.analyzer.calls.length, 1);
});

test('authoritative worker concurrency is bounded by configuration', async (t) => {
  const analyzer = new ConcurrencyTrackingAnalyzer();
  const harness = await createServiceHarness(
    { autoAnalyzeOnUpload: false, analysisMaxConcurrent: 1 },
    analyzer,
    false,
  );
  t.after(() => harness.close());
  const runIds = [];
  for (let index = 0; index < 3; index += 1) {
    const run = await createRunDirect(harness.service, harness.fixtures, {
      payloadHash: `${index + 1}`.repeat(64),
      sha256: ARTIFACT_SHA256,
      byteSize: ARTIFACT_BYTES.length,
    });
    const authorization = await harness.service.authorizeUpload(`127.0.0.${index + 1}`, run.bundle.run.id, 'ENCODED', {
      sha256: ARTIFACT_SHA256,
      byteSize: ARTIFACT_BYTES.length,
      contentType: 'video/mp4',
    });
    const uploaded = authorization.uploadRequired
      ? await harness.service.acceptUploadStream(
        `127.0.0.${index + 1}`,
        authorization.token,
        'video/mp4',
        String(ARTIFACT_BYTES.length),
        Readable.from([ARTIFACT_BYTES]),
      )
      : await harness.service.getBundle(run.bundle.run.id, 'ENCODED');
    await harness.persistence.ensureQualityAnalysisQueued({
      benchmarkRunId: uploaded.run.id,
      artifactId: uploaded.artifact.id,
      metricModelId: 'vmaf-v1-sdr-sd',
      analysisWorkerVersion: 'worker-v1',
      maxAttempts: 3,
    });
    runIds.push(run.bundle.run.id);
  }
  harness.service.startBackgroundWork();
  await Promise.all(runIds.map((runId) => waitForBundleAnalysisState(
    harness.service,
    runId,
    (value) => value.qualityAnalyses[0]?.status === 'COMPLETE',
    `bounded analysis for ${runId}`,
  )));
  assert.equal(analyzer.calls.length, 3);
  assert.equal(analyzer.maxActive, 1);
});

test('exhausted authoritative analysis failures remain observable and retry-counted', async (t) => {
  const analyzer = new AlwaysFailAnalyzer();
  const harness = await createServiceHarness(
    { analysisMaxAttempts: 2, analysisRetryBackoffMs: 1 },
    analyzer,
  );
  t.after(() => harness.close());
  const run = await createRunDirect(harness.service, harness.fixtures, {
    payloadHash: 'e'.repeat(64),
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
  });
  const authorization = await harness.service.authorizeUpload('127.0.0.1', run.bundle.run.id, 'ENCODED', {
    sha256: ARTIFACT_SHA256,
    byteSize: ARTIFACT_BYTES.length,
    contentType: 'video/mp4',
  });
  await harness.service.acceptUploadStream(
    '127.0.0.1', authorization.token, 'video/mp4', String(ARTIFACT_BYTES.length), Readable.from([ARTIFACT_BYTES]),
  );
  const failed = await waitForBundleAnalysisState(
    harness.service,
    run.bundle.run.id,
    (value) => value.qualityAnalyses[0]?.status === 'FAILED',
    'exhausted authoritative analysis',
  );
  assert.equal(failed.qualityAnalyses[0].attemptCount, 2);
  assert.match(failed.qualityAnalyses[0].lastError, /analyzer is unavailable/);
  assert.equal(failed.run.status, 'INVALID');
  assert.equal(analyzer.calls.length, 2);
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
