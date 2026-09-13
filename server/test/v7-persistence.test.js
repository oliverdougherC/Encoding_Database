import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  areAggregationCompatible,
  buildAggregationCompatibilityKey,
  buildDerivedResultRecomputationSpec,
  buildDerivedResultScopeKey,
  buildEnvironmentFingerprint,
  buildRecipeFingerprint,
  canonicalJsonString,
} from '../dist/v7/persistence.js';

const schemaText = readFileSync(new URL('../prisma/schema.prisma', import.meta.url), 'utf8');
const migrationText = readFileSync(
  new URL('../prisma/migrations/20260812010000_v7_evidence_epoch/migration.sql', import.meta.url),
  'utf8',
);
const physicalMemoryMigrationText = readFileSync(
  new URL('../prisma/migrations/20260812153000_v7_environment_physical_memory/migration.sql', import.meta.url),
  'utf8',
);

test('canonicalJsonString sorts nested object keys deterministically', () => {
  const left = canonicalJsonString({
    z: 1,
    nested: { b: 2, a: 1 },
    list: [{ y: 2, x: 1 }],
  });
  const right = canonicalJsonString({
    list: [{ x: 1, y: 2 }],
    nested: { a: 1, b: 2 },
    z: 1,
  });

  assert.equal(left, right);
  assert.equal(left, '{"list":[{"x":1,"y":2}],"nested":{"a":1,"b":2},"z":1}');
});

test('buildRecipeFingerprint normalizes aliases, case, and option ordering', () => {
  const left = buildRecipeFingerprint({
    codecFamily: 'H264',
    encoderImplementation: 'H264_NVENC',
    encoderVersion: 'SDK 12.1',
    preset: ' P6 ',
    pixelFormat: 'YUV420P',
    bitDepth: 8,
    chromaSubsampling: '4:2:0',
    requestedRateControl: {
      mode: 'Quality',
      qualityValue: 23,
      extras: { qmax: 31, qmin: 12 },
    },
    effectiveRateControl: {
      mode: 'CQ',
      qualityValue: 23,
      extras: { qmin: 12, qmax: 31 },
    },
    effectiveOutputSettings: { level: '4.1', profile: 'high' },
    normalizedEffectiveOptions: { lookahead: 1, aq: 'temporal' },
  });

  const right = buildRecipeFingerprint({
    codecFamily: 'h264',
    encoderImplementation: 'h264_nvenc',
    encoderVersion: 'SDK 12.1',
    preset: 'p6',
    pixelFormat: 'yuv420p',
    bitDepth: 8,
    chromaSubsampling: '4:2:0',
    requestedRateControl: {
      mode: 'cq',
      qualityValue: 23,
      extras: { qmin: 12, qmax: 31 },
    },
    effectiveRateControl: {
      mode: 'cq',
      qualityValue: 23,
      extras: { qmax: 31, qmin: 12 },
    },
    effectiveOutputSettings: { profile: 'high', level: '4.1' },
    normalizedEffectiveOptions: { aq: 'temporal', lookahead: 1 },
  });

  assert.equal(left.canonicalJson, right.canonicalJson);
  assert.equal(left.fingerprint, right.fingerprint);
});

test('buildRecipeFingerprint changes for materially different effective recipes', () => {
  const base = {
    codecFamily: 'av1',
    encoderImplementation: 'libsvtav1',
    pixelFormat: 'yuv420p10le',
    bitDepth: 10,
    chromaSubsampling: '4:2:0',
    requestedRateControl: { mode: 'crf', qualityValue: 28 },
    effectiveRateControl: { mode: 'crf', qualityValue: 28 },
  };

  const left = buildRecipeFingerprint(base);
  const right = buildRecipeFingerprint({
    ...base,
    effectiveRateControl: { mode: 'crf', qualityValue: 30 },
  });

  assert.notEqual(left.fingerprint, right.fingerprint);
});

test('buildEnvironmentFingerprint normalizes architecture aliases but keeps material driver changes distinct', () => {
  const left = buildEnvironmentFingerprint({
    cpuModel: 'AMD Ryzen 9 9950X',
    cpuArchitecture: 'AMD64',
    physicalCoreCount: 16,
    logicalThreadCount: 32,
    physicalMemoryBytes: 68719476736,
    gpuModel: 'NVIDIA RTX 5090',
    selectedAcceleratorId: 'GPU-0',
    selectedAccelerator: 'RTX 5090',
    driverVersion: '555.12',
    osName: 'Windows',
    osVersion: '11 24H2',
    ffmpegBuildFingerprint: 'ffmpeg-git-123',
    ffmpegVersion: 'n7.1',
    encoderVersion: 'nvenc-12.1',
    clientVersion: 'v7.0.0',
  });

  const alias = buildEnvironmentFingerprint({
    cpuModel: 'AMD Ryzen 9 9950X',
    cpuArchitecture: 'x86_64',
    physicalCoreCount: 16,
    logicalThreadCount: 32,
    physicalMemoryBytes: 68719476736,
    gpuModel: 'NVIDIA RTX 5090',
    selectedAcceleratorId: 'gpu-0',
    selectedAccelerator: 'RTX 5090',
    driverVersion: '555.12',
    osName: 'windows',
    osVersion: '11 24h2',
    ffmpegBuildFingerprint: 'ffmpeg-git-123',
    ffmpegVersion: 'n7.1',
    encoderVersion: 'nvenc-12.1',
    clientVersion: 'v7.0.0',
  });

  const changedDriver = buildEnvironmentFingerprint({
    cpuModel: 'AMD Ryzen 9 9950X',
    cpuArchitecture: 'x86_64',
    physicalCoreCount: 16,
    logicalThreadCount: 32,
    physicalMemoryBytes: 68719476736,
    gpuModel: 'NVIDIA RTX 5090',
    selectedAcceleratorId: 'gpu-0',
    selectedAccelerator: 'RTX 5090',
    driverVersion: '556.01',
    osName: 'windows',
    osVersion: '11 24h2',
    ffmpegBuildFingerprint: 'ffmpeg-git-123',
    ffmpegVersion: 'n7.1',
    encoderVersion: 'nvenc-12.1',
    clientVersion: 'v7.0.0',
  });
  const changedMemory = buildEnvironmentFingerprint({
    cpuModel: 'AMD Ryzen 9 9950X',
    cpuArchitecture: 'x86_64',
    physicalCoreCount: 16,
    logicalThreadCount: 32,
    physicalMemoryBytes: 34359738368,
    gpuModel: 'NVIDIA RTX 5090',
    selectedAcceleratorId: 'gpu-0',
    selectedAccelerator: 'RTX 5090',
    driverVersion: '555.12',
    osName: 'windows',
    osVersion: '11 24h2',
    ffmpegBuildFingerprint: 'ffmpeg-git-123',
    ffmpegVersion: 'n7.1',
    encoderVersion: 'nvenc-12.1',
    clientVersion: 'v7.0.0',
  });

  assert.equal(left.fingerprint, alias.fingerprint);
  assert.notEqual(left.fingerprint, changedDriver.fingerprint);
  assert.notEqual(left.fingerprint, changedMemory.fingerprint);
});

test('aggregation compatibility key blocks protocol, workload, recipe, environment, or score-context drift', () => {
  const base = {
    protocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: 'sdr-suite-v1',
    workloadId: 'sports-1080p',
    recipeFingerprint: 'recipe-a',
    environmentFingerprint: 'env-a',
    formulaVersion: '7.0',
    scoreContextVersion: 'pl7-sdr-suite-v1-2026a',
    qualityModelId: 'vmaf-v1.0.0-sdr',
  };

  assert.equal(areAggregationCompatible(base, { ...base }), true);
  assert.equal(
    areAggregationCompatible(base, { ...base, environmentFingerprint: 'env-b' }),
    false,
  );
  assert.equal(
    buildAggregationCompatibilityKey(base),
    buildAggregationCompatibilityKey({ ...base }),
  );
});

test('derived-result recomputation specs and scope keys are canonical and non-null', () => {
  assert.equal(
    buildDerivedResultScopeKey('clip', { workloadId: 'sports-1080p', testClipId: 'clip-01' }),
    'clip:sports-1080p:clip-01',
  );
  assert.equal(
    buildDerivedResultScopeKey('workload', { workloadId: 'sports-1080p' }),
    'workload:sports-1080p',
  );

  const spec = buildDerivedResultRecomputationSpec({
    protocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: 'sdr-suite-v1',
    workloadId: 'sports-1080p',
    recipeFingerprint: 'recipe-a',
    environmentFingerprint: 'env-a',
    formulaVersion: '7.0',
    scoreContextVersion: 'pl7-sdr-suite-v1-2026a',
    qualityModelId: 'vmaf-v1.0.0-sdr',
    scopeKey: 'workload:sports-1080p',
    includedStatuses: ['accepted', 'suspect'],
    aggregatorVersion: 'derived-v1',
    selectedAnalysisIds: ['analysis-b', 'analysis-a'],
    analysisWorkerVersions: ['worker-v1', 'worker-v1'],
  });

  assert.deepEqual(spec.includedStatuses, ['accepted', 'suspect']);
  assert.equal(spec.scopeKey, 'workload:sports-1080p');
  assert.deepEqual(spec.selectedAnalysisIds, ['analysis-a', 'analysis-b']);
  assert.deepEqual(spec.analysisWorkerVersions, ['worker-v1']);
});

test('schema and migration isolate legacy aggregates and require explicit canonical workload identity', () => {
  assert.doesNotMatch(
    schemaText,
    /@@unique\(\[cpuModel, gpuModel, ramGB, os, codec, preset, crf, contentClass, resolution, passes, workloadId\]\)/,
  );
  assert.match(schemaText, /model BenchmarkRun \{/);
  assert.match(schemaText, /physicalMemoryBytes\s+BigInt\?/);
  assert.match(schemaText, /workloadId\s+String/);
  assert.match(schemaText, /energyDomains\s+Json\?/);
  assert.match(schemaText, /decodeBenchmark\s+Json\?/);
  assert.match(schemaText, /scopeKey\s+String/);
  assert.match(schemaText, /invalidRunCount\s+Int/);
  assert.match(schemaText, /evidenceSummary\s+Json/);
  assert.match(schemaText, /confidenceIntervals\s+Json/);
  assert.match(schemaText, /dispersion\s+Json/);
  assert.match(schemaText, /@@unique\(\[kind, benchmarkProtocolId, recipeId, environmentId, scoreContextId, scopeKey\]\)/);

  assert.match(migrationText, /DROP CONSTRAINT IF EXISTS "Benchmark_v7_aggregate_key"/);
  assert.match(migrationText, /"BenchmarkRun"\s+\([\s\S]*"workloadId" TEXT NOT NULL/);
  assert.match(physicalMemoryMigrationText, /ALTER TABLE "Environment"[\s\S]*ADD COLUMN "physicalMemoryBytes" BIGINT/);
  assert.match(physicalMemoryMigrationText, /"canonicalJson"->>'physicalMemoryBytes'/);
  assert.match(migrationText, /"BenchmarkRun"\s+\([\s\S]*"energyDomains" JSONB/);
  assert.match(migrationText, /"BenchmarkRun"\s+\([\s\S]*"decodeBenchmark" JSONB/);
  assert.match(migrationText, /"ScoreContext"\s+\([\s\S]*"workloadId" TEXT NOT NULL/);
  assert.match(migrationText, /"DerivedResult"\s+\([\s\S]*"invalidRunCount" INTEGER NOT NULL DEFAULT 0/);
  assert.match(migrationText, /"DerivedResult"\s+\([\s\S]*"evidenceSummary" JSONB NOT NULL/);
  assert.match(migrationText, /"DerivedResult"\s+\([\s\S]*"confidenceIntervals" JSONB NOT NULL/);
  assert.match(migrationText, /"DerivedResult"\s+\([\s\S]*"dispersion" JSONB NOT NULL/);
  assert.match(
    migrationText,
    /CREATE UNIQUE INDEX "DerivedResult_kind_benchmarkProtocolId_recipeId_environmentId_scoreContextId_scopeKey_key"/,
  );
});

test('legacy compatibility aggregate keeps null workload identities unique', () => {
  const migration = readFileSync(new URL('../prisma/migrations/20260812030000_legacy_aggregate_null_identity/migration.sql', import.meta.url), 'utf8');
  assert.match(migration, /CREATE UNIQUE INDEX "Benchmark_legacy_identity_nulls_not_distinct_key"/);
  assert.match(migration, /NULLS NOT DISTINCT/);
  assert.match(migration, /"workloadId"/);
});

test('derived membership and bitrate provenance retain exact immutable analysis evidence', () => {
  const migration = readFileSync(new URL('../prisma/migrations/20260812040000_exact_analysis_membership/migration.sql', import.meta.url), 'utf8');
  assert.match(schemaText, /videoPayloadBytes\s+Int\?/);
  assert.match(schemaText, /videoPacketCount\s+Int\?/);
  assert.match(schemaText, /measuredDurationSeconds\s+Float\?/);
  assert.match(schemaText, /bitrateMethod\s+String\?/);
  assert.match(schemaText, /qualityAnalysisId\s+String/);
  assert.match(migration, /ALTER COLUMN "qualityAnalysisId" SET NOT NULL/);
  assert.match(migration, /FOREIGN KEY \("qualityAnalysisId"\) REFERENCES "QualityAnalysis"\("id"\)/);
  assert.match(migration, /DerivedResultMember_derivedResultId_qualityAnalysisId_key/);
});
