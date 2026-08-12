import express, { Router } from 'express';
import crypto from 'node:crypto';
import { promisify } from 'node:util';
import { execFile, spawn } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { access, copyFile, mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import type { PrismaClient } from '@prisma/client';
import { prisma } from '../db.js';
import {
  buildAuthoritativeQualityAnalysisRecord,
  resolveQualityAnalysisExecutionPlan,
  VMAF_MODEL_FILENAME,
} from '../qualityAnalysis.js';
import {
  DEFAULT_RECOMMENDATION_EVIDENCE_POLICY,
  persistDerivedResultAggregate,
} from './aggregation.js';
import {
  buildEnvironmentFingerprint,
  buildRecipeFingerprint,
  canonicalJsonString,
  type EnvironmentIdentityInput,
  type JsonValue,
  type RecipeIdentityInput,
} from './persistence.js';
import {
  buildSuiteTestClipRecordInput,
  loadAuthoritativeSuiteManifest,
  parseSuiteManifest,
  type SuiteTestClipRecordInput,
  type SuiteV1Manifest,
  SUITE_V1_VERSION,
} from './suite.js';
import {
  normalizeDecodeBenchmark,
  normalizeEnergyDomains,
  type DecodeBenchmarkInput,
  type EnergyDomainInput,
} from './telemetry.js';
import {
  buildScoreContextSeedRecords,
  loadReferenceContext,
  persistGeneralDerivedResultFromWorkloadEvidence,
  type ReferenceContext,
} from './referenceContext.js';

const execFileAsync = promisify(execFile);

export const ARTIFACT_PIPELINE_VERSION = 'encodingdb-artifact-pipeline/v1' as const;
export const DEFAULT_ANALYZER_VERSION = 'authoritative-analysis/v1' as const;
export const SERVER_CANONICAL_PROTOCOL_VERSION = '7.0' as const;
export const SERVER_CANONICAL_MINIMUM_CLIENT_VERSION = 'client/0.2.0' as const;
export const SERVER_CANONICAL_RECIPE_RULES = {
  artifactUploadRequired: true,
  warmupRuns: 1,
  minimumMeasuredRuns: 2,
  stabilityThresholdRatio: 0.03,
  maxAdaptiveRepeats: 2,
} as const;
export const SERVER_CANONICAL_OUTPUT_RULES = {
  singleVideoStream: true,
  noAudio: true,
} as const;

export type ArtifactRoleValue = 'ENCODED' | 'METADATA' | 'TELEMETRY' | 'LOG' | 'ANALYSIS_REPORT';
export type ArtifactStorageStateValue = 'PENDING' | 'UPLOADED' | 'VERIFIED' | 'RETAINED' | 'REJECTED' | 'DELETED';
export type BenchmarkRunStatusValue = 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'SUSPECT' | 'INVALID';
export type QualityAnalysisStatusValue = 'PENDING' | 'COMPLETE' | 'SUSPECT' | 'REJECTED' | 'FAILED';

type JsonObject = Record<string, unknown>;
type JsonRecord = Record<string, unknown>;

export interface StoredBenchmarkProtocol {
  id: string;
  protocolVersion: string;
  sourceSuiteVersion: string;
  minimumClientVersion: string;
  metricWorkerVersion: string;
  canonicalRecipeRules: unknown;
  canonicalOutputRules: unknown;
  state?: string;
}

export interface StoredTestClip {
  id: string;
  workloadId: string;
  displayName: string;
  sourceProvenance: unknown;
  sha256: string;
  byteSize: number;
  exactFrameCount: number;
  exactDurationSeconds: number;
  frameRateNumerator: number;
  frameRateDenominator: number;
  width: number;
  height: number;
  pixelFormat: string;
  bitDepth: number;
  chromaSubsampling: string;
  colorPrimaries?: string | null;
  transferCharacteristics?: string | null;
  matrixCoefficients?: string | null;
  colorRange?: string | null;
}

export interface StoredRecipe {
  id: string;
  fingerprint: string;
  canonicalJson: unknown;
  codecFamily: string;
  encoderImplementation: string;
  pixelFormat: string;
  bitDepth: number;
  chromaSubsampling: string;
  containerFormat: string | null;
  videoCodecTag: string | null;
  profile: string | null;
  level: string | null;
  gopSize: number | null;
  keyframeInterval: number | null;
  bFrames: number | null;
  frameReordering: boolean | null;
}

export interface StoredEnvironment {
  id: string;
  fingerprint: string;
  canonicalJson: unknown;
  clientVersion?: string;
  ffmpegVersion: string;
}

export interface StoredBenchmarkRun {
  id: string;
  benchmarkProtocolId: string;
  testClipId: string;
  workloadId: string;
  recipeId: string;
  environmentId: string;
  payloadHash: string;
  inputHash: string | null;
  campaignId: string | null;
  repetitionGroupId: string | null;
  repetitionIndex: number | null;
  encodeWallTimeMs: number | null;
  encodeFps: number | null;
  sourceFps: number | null;
  realTimeRatio: number | null;
  sourceFrameCount: number | null;
  encodedFrameCount: number | null;
  telemetry: unknown;
  telemetrySources: unknown;
  telemetryMissing: unknown;
  energyDomains: unknown;
  decodeBenchmark: unknown;
  preRunEnvironmentCheck: unknown;
  ffmpegProgressTelemetry: unknown;
  clientQualityDebug: unknown;
  status: BenchmarkRunStatusValue;
  statusReason: string | null;
  benchmarkProtocol: StoredBenchmarkProtocol;
  testClip: StoredTestClip;
  recipe: StoredRecipe;
  environment: StoredEnvironment;
}

export interface StoredArtifact {
  id: string;
  benchmarkRunId: string;
  role: ArtifactRoleValue;
  sha256: string | null;
  byteSize: number | null;
  storageState: ArtifactStorageStateValue;
  storageProvider: string | null;
  storageBucket: string | null;
  storageKey: string | null;
  storageUrl: string | null;
  mediaContainer: string | null;
  stateReason: string | null;
  stateDetails: unknown;
  uploadedAt: Date | null;
  verifiedAt: Date | null;
  retainedAt: Date | null;
  deletedAt: Date | null;
}

export interface StoredQualityAnalysis {
  id: string;
  benchmarkRunId: string;
  artifactId: string | null;
  status: QualityAnalysisStatusValue;
  metricModelId: string;
  qualityContextId: string | null;
  analysisWorkerVersion: string;
  analysisProvenance: unknown;
  vmafMean: number | null;
  vmafMedian: number | null;
  vmafP1: number | null;
  vmafP5: number | null;
  vmafMin: number | null;
  vmafMax: number | null;
  vmafStdDev: number | null;
  vmafHarmonicMean: number | null;
  worstFrameIndex: number | null;
  worstFrameTimestampMs: number | null;
  belowThresholdFractions: unknown;
  vmafDistribution: unknown;
  xpsnr: number | null;
  ssim: number | null;
  psnr: number | null;
  videoBitrateBps: number | null;
  videoPayloadBytes: number | null;
  videoPacketCount: number | null;
  measuredDurationSeconds: number | null;
  bitrateMethod: string | null;
  containerBitrateBps: number | null;
  fileSizeBytes: number | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface RunArtifactBundle {
  run: StoredBenchmarkRun;
  artifact: StoredArtifact;
  qualityAnalyses: StoredQualityAnalysis[];
}

export interface CreateRunInput {
  benchmarkProtocolId: string;
  testClipId: string;
  workloadId: string;
  recipeId: string;
  environmentId: string;
  payloadHash: string;
  inputHash?: string | null;
  campaignId?: string | null;
  repetitionGroupId?: string | null;
  repetitionIndex?: number | null;
  encodeWallTimeMs?: number | null;
  encodeFps?: number | null;
  sourceFps?: number | null;
  realTimeRatio?: number | null;
  sourceFrameCount?: number | null;
  encodedFrameCount?: number | null;
  telemetry?: unknown;
  telemetrySources?: unknown;
  telemetryMissing?: unknown;
  energyDomains?: unknown;
  decodeBenchmark?: unknown;
  preRunEnvironmentCheck?: unknown;
  ffmpegProgressTelemetry?: unknown;
  clientQualityDebug?: unknown;
  artifact: {
    role: ArtifactRoleValue;
    sha256: string;
    byteSize: number;
    mediaContainer?: string | null;
  };
}

export interface BenchmarkProtocolBootstrapInput {
  protocolVersion: string;
  sourceSuiteVersion: string;
  minimumClientVersion: string;
  canonicalRecipeRules: unknown;
  canonicalOutputRules: unknown;
  metricWorkerVersion: string;
}

export interface TestClipBootstrapInput {
  suiteId: string;
  suiteVersion: string;
  clipKey?: string | null;
  sha256?: string | null;
  workloadId?: string | null;
}

export interface RecipeBootstrapInput {
  fingerprint: string;
  canonicalJson?: unknown;
  identity: unknown;
}

export interface EnvironmentBootstrapInput {
  fingerprint: string;
  canonicalJson?: unknown;
  identity: unknown;
}

export interface CreateRunRequestInput {
  benchmarkProtocol: BenchmarkProtocolBootstrapInput;
  testClip: TestClipBootstrapInput;
  recipe: RecipeBootstrapInput;
  environment: EnvironmentBootstrapInput;
  payloadHash: string;
  workloadId?: string | null;
  expectedMetricModelId?: string | null;
  inputHash?: string | null;
  campaignId?: string | null;
  repetitionGroupId?: string | null;
  repetitionIndex?: number | null;
  encodeWallTimeMs?: number | null;
  encodeFps?: number | null;
  sourceFps?: number | null;
  realTimeRatio?: number | null;
  sourceFrameCount?: number | null;
  encodedFrameCount?: number | null;
  telemetry?: unknown;
  telemetrySources?: unknown;
  telemetryMissing?: unknown;
  energyDomains?: unknown;
  decodeBenchmark?: unknown;
  preRunEnvironmentCheck?: unknown;
  ffmpegProgressTelemetry?: unknown;
  clientQualityDebug?: unknown;
  artifact: {
    role: ArtifactRoleValue;
    sha256: string;
    byteSize: number;
    mediaContainer?: string | null;
  };
}

export interface AuthoritativeAnalysisResult {
  metricModelId: string;
  qualityContextId: string | null;
  analysisWorkerVersion: string;
  analysisStatus: QualityAnalysisStatusValue;
  analysisProvenance: JsonObject;
  vmafMean: number | null;
  vmafMedian: number | null;
  vmafP1: number | null;
  vmafP5: number | null;
  vmafMin: number | null;
  vmafMax: number | null;
  vmafStdDev: number | null;
  vmafHarmonicMean: number | null;
  worstFrameIndex: number | null;
  worstFrameTimestampMs: number | null;
  belowThresholdFractions: unknown;
  vmafDistribution: unknown;
  xpsnr: number | null;
  ssim: number | null;
  psnr: number | null;
  videoBitrateBps: number | null;
  videoPayloadBytes: number | null;
  videoPacketCount: number | null;
  measuredDurationSeconds: number | null;
  bitrateMethod: string | null;
  containerBitrateBps: number | null;
  fileSizeBytes: number | null;
  runStatus: BenchmarkRunStatusValue;
  runStatusReason: string | null;
  artifactState: ArtifactStorageStateValue;
  artifactStateReason?: string | null;
  artifactStateDetails?: JsonObject | null;
}

export interface AnalyzeArtifactInput {
  bundle: RunArtifactBundle;
  artifactPath: string;
  requestedAnalysisWorkerVersion?: string | null;
  requestedMetricModelId?: string | null | undefined;
}

export interface ArtifactAnalyzer {
  analyze(input: AnalyzeArtifactInput): Promise<AuthoritativeAnalysisResult>;
}

export interface ArtifactPipelinePersistence {
  resolveOrBootstrapBenchmarkProtocol(input: BenchmarkProtocolBootstrapInput): Promise<StoredBenchmarkProtocol>;
  upsertCanonicalTestClip(input: SuiteTestClipRecordInput): Promise<StoredTestClip>;
  resolveOrBootstrapRecipe(input: RecipeBootstrapInput): Promise<StoredRecipe>;
  resolveOrBootstrapEnvironment(input: EnvironmentBootstrapInput): Promise<StoredEnvironment>;
  createOrFetchRun(input: CreateRunInput): Promise<{ bundle: RunArtifactBundle; created: boolean }>;
  getRunArtifact(benchmarkRunId: string, role: ArtifactRoleValue): Promise<RunArtifactBundle | null>;
  getArtifactBySha256(sha256: string): Promise<StoredArtifact | null>;
  markArtifactUploaded(input: {
    artifactId: string;
    sha256: string;
    byteSize: number;
    mediaContainer: string | null;
    storageProvider: string;
    storageBucket: string | null;
    storageKey: string;
    storageUrl: string;
    stateDetails?: JsonObject;
  }): Promise<RunArtifactBundle>;
  markArtifactState(input: {
    artifactId: string;
    storageState: ArtifactStorageStateValue;
    stateReason?: string | null;
    stateDetails?: JsonObject | null;
  }): Promise<RunArtifactBundle>;
  getQualityAnalysis(
    benchmarkRunId: string,
    metricModelId: string,
    analysisWorkerVersion: string,
  ): Promise<StoredQualityAnalysis | null>;
  saveAuthoritativeAnalysis(input: {
    benchmarkRunId: string;
    artifactId: string;
    result: AuthoritativeAnalysisResult;
  }): Promise<RunArtifactBundle>;
}

export interface DerivedRecomputeHookPayload {
  benchmarkRunId: string;
  artifactId: string;
  metricModelId: string;
  analysisWorkerVersion: string;
}

export interface ArtifactStorageConfig {
  rootDir: string;
  provider: string;
  bucket: string | null;
}

export interface ArtifactPipelineConfig {
  uploadTokenSecret: string;
  uploadTokenTtlMs: number;
  maxArtifactBytes: number;
  allowedMimeTypes: ReadonlySet<string>;
  authRateLimitWindowMs: number;
  authRateLimitMax: number;
  uploadRateLimitWindowMs: number;
  uploadRateLimitMax: number;
  storage: ArtifactStorageConfig;
  analyzerVersion: string;
  autoAnalyzeOnUpload: boolean;
}

export interface ArtifactPipelineOptions {
  persistence?: ArtifactPipelinePersistence;
  analyzer?: ArtifactAnalyzer;
  config?: Partial<ArtifactPipelineConfig>;
  suiteManifest?: SuiteV1Manifest | unknown;
  onDerivedRecompute?: (payload: DerivedRecomputeHookPayload) => Promise<void> | void;
}

const VALID_ARTIFACT_ROLE_VALUES = ['ENCODED', 'METADATA', 'TELEMETRY', 'LOG', 'ANALYSIS_REPORT'] as const;
const BENCHMARK_PROTOCOL_BOOTSTRAP_SCHEMA = z.object({
  protocolVersion: z.string().min(1).max(100),
  sourceSuiteVersion: z.string().min(1).max(100),
  minimumClientVersion: z.string().min(1).max(100),
  canonicalRecipeRules: z.unknown(),
  canonicalOutputRules: z.unknown(),
  metricWorkerVersion: z.string().min(1).max(200),
}).strict();

const TEST_CLIP_BOOTSTRAP_SCHEMA = z.object({
  suiteId: z.string().min(1).max(100),
  suiteVersion: z.string().min(1).max(100),
  clipKey: z.string().min(1).max(200).optional().nullable(),
  sha256: z.string().length(64).regex(/^[0-9a-f]+$/).optional().nullable(),
  workloadId: z.string().min(1).max(200).optional().nullable(),
}).strict().superRefine((value, ctx) => {
  if (!value.clipKey && !value.sha256) {
    ctx.addIssue({
      code: 'custom',
      path: ['clipKey'],
      message: 'clipKey or sha256 is required',
    });
  }
});

const RECIPE_BOOTSTRAP_SCHEMA = z.object({
  fingerprint: z.string().length(64).regex(/^[0-9a-f]+$/),
  canonicalJson: z.unknown().optional(),
  identity: z.unknown(),
}).strict();

const ENVIRONMENT_BOOTSTRAP_SCHEMA = z.object({
  fingerprint: z.string().length(64).regex(/^[0-9a-f]+$/),
  canonicalJson: z.unknown().optional(),
  identity: z.unknown(),
}).strict();

const RUN_CREATE_SCHEMA = z.object({
  benchmarkProtocol: BENCHMARK_PROTOCOL_BOOTSTRAP_SCHEMA,
  testClip: TEST_CLIP_BOOTSTRAP_SCHEMA,
  recipe: RECIPE_BOOTSTRAP_SCHEMA,
  environment: ENVIRONMENT_BOOTSTRAP_SCHEMA,
  payloadHash: z.string().length(64).regex(/^[0-9a-f]+$/),
  workloadId: z.string().min(1).max(200).optional().nullable(),
  expectedMetricModelId: z.string().min(1).max(200).optional().nullable(),
  inputHash: z.string().length(64).regex(/^[0-9a-f]+$/).optional().nullable(),
  campaignId: z.string().max(200).optional().nullable(),
  repetitionGroupId: z.string().max(200).optional().nullable(),
  repetitionIndex: z.number().int().min(0).optional().nullable(),
  encodeWallTimeMs: z.number().int().min(0).optional().nullable(),
  encodeFps: z.number().positive().optional().nullable(),
  sourceFps: z.number().positive().optional().nullable(),
  realTimeRatio: z.number().positive().optional().nullable(),
  sourceFrameCount: z.number().int().min(0).optional().nullable(),
  encodedFrameCount: z.number().int().min(0).optional().nullable(),
  telemetry: z.unknown().optional(),
  telemetrySources: z.unknown().optional(),
  telemetryMissing: z.unknown().optional(),
  energyDomains: z.array(z.unknown()).optional().nullable(),
  decodeBenchmark: z.unknown().optional().nullable(),
  preRunEnvironmentCheck: z.unknown().optional(),
  ffmpegProgressTelemetry: z.unknown().optional(),
  clientQualityDebug: z.unknown().optional(),
  artifact: z.object({
    role: z.enum(VALID_ARTIFACT_ROLE_VALUES).default('ENCODED'),
    sha256: z.string().length(64).regex(/^[0-9a-f]+$/),
    byteSize: z.number().int().positive(),
    mediaContainer: z.string().max(64).optional().nullable(),
  }).strict(),
}).strict();

const UPLOAD_AUTH_SCHEMA = z.object({
  sha256: z.string().length(64).regex(/^[0-9a-f]+$/),
  byteSize: z.number().int().positive(),
  contentType: z.string().max(200).optional().nullable(),
}).strict();

const REANALYZE_SCHEMA = z.object({
  analysisWorkerVersion: z.string().min(1).max(200).optional().nullable(),
  metricModelId: z.string().min(1).max(200).optional().nullable(),
}).strict();

const DEFAULT_ALLOWED_MIME_TYPES = new Set(['video/mp4', 'video/x-matroska', 'application/octet-stream']);

const defaultStorageRoot = path.resolve(process.cwd(), '.artifacts');

function buildDefaultConfig(): ArtifactPipelineConfig {
  return {
    uploadTokenSecret: process.env.ARTIFACT_UPLOAD_SECRET || 'encodingdb-artifact-secret-dev-only',
    uploadTokenTtlMs: Number(process.env.ARTIFACT_UPLOAD_TTL_MS || 15 * 60 * 1000),
    maxArtifactBytes: Number(process.env.ARTIFACT_MAX_BYTES || 2 * 1024 * 1024 * 1024),
    allowedMimeTypes: DEFAULT_ALLOWED_MIME_TYPES,
    authRateLimitWindowMs: Number(process.env.ARTIFACT_AUTH_RATE_WINDOW_MS || 60_000),
    authRateLimitMax: Number(process.env.ARTIFACT_AUTH_RATE_MAX || 30),
    uploadRateLimitWindowMs: Number(process.env.ARTIFACT_UPLOAD_RATE_WINDOW_MS || 60_000),
    uploadRateLimitMax: Number(process.env.ARTIFACT_UPLOAD_RATE_MAX || 20),
    storage: {
      rootDir: path.resolve(process.env.ARTIFACT_STORAGE_ROOT || defaultStorageRoot),
      provider: 'localfs',
      bucket: null,
    },
    analyzerVersion: process.env.ARTIFACT_ANALYZER_VERSION || DEFAULT_ANALYZER_VERSION,
    autoAnalyzeOnUpload: String(process.env.ARTIFACT_AUTO_ANALYZE || '1') !== '0',
  };
}

export function mergeArtifactPipelineConfig(overrides: Partial<ArtifactPipelineConfig> | undefined): ArtifactPipelineConfig {
  const base = buildDefaultConfig();
  if (!overrides) return base;
  return {
    ...base,
    ...overrides,
    allowedMimeTypes: overrides.allowedMimeTypes ?? base.allowedMimeTypes,
    storage: {
      ...base.storage,
      ...(overrides.storage ?? {}),
    },
  };
}

function normalizeVersionSegment(value: string): string | number {
  return /^\d+$/.test(value) ? Number(value) : value.toLowerCase();
}

function splitVersionLike(value: string): Array<string | number> {
  return value
    .split(/[^0-9a-zA-Z]+/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map(normalizeVersionSegment);
}

function compareVersionLike(leftRaw: string, rightRaw: string): number {
  const left = splitVersionLike(leftRaw);
  const right = splitVersionLike(rightRaw);
  const max = Math.max(left.length, right.length);
  for (let index = 0; index < max; index += 1) {
    const leftValue = left[index] ?? 0;
    const rightValue = right[index] ?? 0;
    if (leftValue === rightValue) continue;
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return leftValue < rightValue ? -1 : 1;
    }
    return String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: 'base' });
  }
  return 0;
}

function toCanonicalJsonString(value: unknown, fieldName: string): string {
  try {
    return canonicalJsonString(value as JsonValue);
  } catch (error) {
    throw new HttpError(400, `${fieldName} must be canonicalizable JSON: ${normalizeError(error)}`);
  }
}

function assertCanonicalJsonMatch(expected: string, provided: unknown, fieldName: string): void {
  if (provided === undefined) return;
  const candidate = toCanonicalJsonString(provided, fieldName);
  if (candidate !== expected) {
    throw new HttpError(409, `${fieldName} does not match the canonical normalized identity JSON`);
  }
}

function asRecipeIdentityInput(value: unknown): RecipeIdentityInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new HttpError(400, 'recipe.identity must be an object');
  }
  return value as RecipeIdentityInput;
}

function asEnvironmentIdentityInput(value: unknown): EnvironmentIdentityInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new HttpError(400, 'environment.identity must be an object');
  }
  return value as EnvironmentIdentityInput;
}

function assertClientVersionMeetsMinimum(actual: string, minimum: string): void {
  if (compareVersionLike(actual, minimum) < 0) {
    throw new HttpError(409, `Client version ${actual} is below canonical minimum ${minimum}`);
  }
}

function assertMetricModelCompatibility(expectedMetricModelId: string | null | undefined, testClip: StoredTestClip): void {
  if (!expectedMetricModelId) return;
  const source = {
    width: testClip.width,
    height: testClip.height,
    frameRate: testClip.frameRateNumerator / testClip.frameRateDenominator,
    dynamicRange: 'sdr' as const,
  };
  const modelPath = fileURLToPath(new URL(`../../resources/vmaf/${VMAF_MODEL_FILENAME}`, import.meta.url));
  const resolvedMetricModelId = resolveQualityAnalysisExecutionPlan(source, modelPath).metricModelId;
  if (expectedMetricModelId !== resolvedMetricModelId) {
    throw new HttpError(409, `Expected metric model ${expectedMetricModelId} is incompatible with canonical workload model ${resolvedMetricModelId}`);
  }
}

function toPrismaRateControlMode(mode: string): string {
  return mode.toUpperCase();
}

function assertCanonicalProtocolRules(
  input: BenchmarkProtocolBootstrapInput,
  suiteVersion: string,
): BenchmarkProtocolBootstrapInput {
  if (input.protocolVersion !== SERVER_CANONICAL_PROTOCOL_VERSION) {
    throw new HttpError(409, `Server canonical protocolVersion is ${SERVER_CANONICAL_PROTOCOL_VERSION}; client declared ${input.protocolVersion}`);
  }
  if (input.sourceSuiteVersion !== suiteVersion || input.sourceSuiteVersion !== SUITE_V1_VERSION) {
    throw new HttpError(409, `Server canonical sourceSuiteVersion is ${suiteVersion}; client declared ${input.sourceSuiteVersion}`);
  }
  if (input.metricWorkerVersion !== DEFAULT_ANALYZER_VERSION) {
    throw new HttpError(409, `Server canonical metricWorkerVersion is ${DEFAULT_ANALYZER_VERSION}; client declared ${input.metricWorkerVersion}`);
  }
  if (input.minimumClientVersion !== SERVER_CANONICAL_MINIMUM_CLIENT_VERSION) {
    throw new HttpError(409, `Server canonical minimumClientVersion is ${SERVER_CANONICAL_MINIMUM_CLIENT_VERSION}; client declared ${input.minimumClientVersion}`);
  }

  const recipeRules = asJsonObject(input.canonicalRecipeRules);
  const outputRules = asJsonObject(input.canonicalOutputRules);
  for (const [key, expected] of Object.entries(SERVER_CANONICAL_RECIPE_RULES)) {
    if (recipeRules?.[key] !== expected) {
      throw new HttpError(409, `Server canonical recipe rule ${key}=${expected} but client declared ${String(recipeRules?.[key])}`);
    }
  }
  for (const [key, expected] of Object.entries(SERVER_CANONICAL_OUTPUT_RULES)) {
    if (outputRules?.[key] !== expected) {
      throw new HttpError(409, `Server canonical output rule ${key}=${expected} but client declared ${String(outputRules?.[key])}`);
    }
  }

  return {
    protocolVersion: SERVER_CANONICAL_PROTOCOL_VERSION,
    sourceSuiteVersion: suiteVersion,
    minimumClientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
    canonicalRecipeRules: SERVER_CANONICAL_RECIPE_RULES,
    canonicalOutputRules: SERVER_CANONICAL_OUTPUT_RULES,
    metricWorkerVersion: DEFAULT_ANALYZER_VERSION,
  };
}

function sha256Hex(buffer: Buffer): string {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function toBase64Url(buffer: Buffer): string {
  return buffer.toString('base64url');
}

function fromBase64Url(value: string): Buffer {
  return Buffer.from(value, 'base64url');
}

function compareBytes(left: Buffer, right: Buffer): boolean {
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function signUploadToken(payload: JsonObject, secret: string): string {
  const body = toBase64Url(Buffer.from(JSON.stringify(payload), 'utf8'));
  const signature = crypto.createHmac('sha256', secret).update(body).digest();
  return `${body}.${toBase64Url(signature)}`;
}

function verifyUploadToken(token: string, secret: string): JsonObject {
  const [body, sig] = token.split('.');
  if (!body || !sig) throw new Error('Malformed upload token');
  const expected = crypto.createHmac('sha256', secret).update(body).digest();
  const provided = fromBase64Url(sig);
  if (!compareBytes(expected, provided)) throw new Error('Invalid upload token signature');
  const parsed = JSON.parse(fromBase64Url(body).toString('utf8')) as JsonObject;
  return parsed;
}

function buildObjectKey(sha256: string): string {
  return path.join('objects', sha256.slice(0, 2), sha256);
}

async function ensureParentDir(filePath: string): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

class LocalArtifactStorage {
  constructor(private readonly config: ArtifactStorageConfig) {}

  resolveAbsolutePath(key: string): string {
    return path.join(this.config.rootDir, key);
  }

  async hasObject(key: string, expectedSize: number): Promise<boolean> {
    const absolutePath = this.resolveAbsolutePath(key);
    try {
      const stats = await stat(absolutePath);
      return stats.isFile() && stats.size === expectedSize;
    } catch {
      return false;
    }
  }

  async writeObject(sha256: string, body: Buffer): Promise<{ key: string; absolutePath: string }> {
    const key = buildObjectKey(sha256);
    const absolutePath = this.resolveAbsolutePath(key);
    if (await this.hasObject(key, body.length)) {
      return { key, absolutePath };
    }
    await ensureParentDir(absolutePath);
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-artifact-'));
    const tempFile = path.join(tempDir, sha256);
    try {
      await writeFile(tempFile, body);
      try {
        await rename(tempFile, absolutePath);
      } catch {
        if (!(await this.hasObject(key, body.length))) {
          throw new Error(`Failed to persist artifact object ${sha256}`);
        }
      }
      return { key, absolutePath };
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  }

  async linkExistingObject(sha256: string, expectedSize: number): Promise<{ key: string; absolutePath: string } | null> {
    const key = buildObjectKey(sha256);
    const absolutePath = this.resolveAbsolutePath(key);
    if (!(await this.hasObject(key, expectedSize))) return null;
    return { key, absolutePath };
  }
}

function asJsonObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : null;
}

function nowIso(): string {
  return new Date().toISOString();
}

function normalizeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function inferMediaContainerFromFormatName(formatName: string | null | undefined): string | null {
  if (!formatName) return null;
  const formats = formatName.split(',').map((value) => value.trim().toLowerCase()).filter(Boolean);
  if (formats.some((value) => ['mp4', 'mov', 'm4v', '3gp', '3g2', 'mj2'].includes(value))) return 'mp4';
  if (formats.some((value) => ['matroska', 'mkv'].includes(value))) return 'mkv';
  if (formats.includes('webm')) return 'webm';
  return formats[0] ?? null;
}

function inferBitDepth(pixelFormat: string | null | undefined, rawBits: number | null): number | null {
  if (rawBits != null && Number.isFinite(rawBits) && rawBits > 0) {
    return Math.trunc(rawBits);
  }
  const text = String(pixelFormat || '').toLowerCase();
  const match = text.match(/(?:p|yuv|gbr|gray)(\d{2})/);
  if (match?.[1]) return Number(match[1]);
  if (text.includes('p010') || text.includes('10le')) return 10;
  if (text.includes('12le')) return 12;
  if (text) return 8;
  return null;
}

function inferChromaSubsampling(pixelFormat: string | null | undefined): string | null {
  const text = String(pixelFormat || '').toLowerCase();
  if (!text) return null;
  if (text.includes('444')) return '4:4:4';
  if (text.includes('422')) return '4:2:2';
  if (text.includes('420') || text.includes('nv12') || text.includes('p010')) return '4:2:0';
  if (text.includes('411')) return '4:1:1';
  return null;
}

function parseRatio(value: string | null | undefined): number | null {
  if (!value) return null;
  const [rawLeft, rawRight] = value.split('/');
  if (!rawLeft || !rawRight) return null;
  const left = Number(rawLeft);
  const right = Number(rawRight);
  if (!Number.isFinite(left) || !Number.isFinite(right) || right === 0) return null;
  return left / right;
}

function approxEqual(left: number, right: number, tolerance: number): boolean {
  return Math.abs(left - right) <= tolerance;
}

function assertArtifactRole(input: string): asserts input is ArtifactRoleValue {
  if (!VALID_ARTIFACT_ROLE_VALUES.includes(input as ArtifactRoleValue)) {
    throw new Error(`Unsupported artifact role ${input}`);
  }
}

function validateProbeAgainstRun(bundle: RunArtifactBundle, probePayload: JsonObject): {
  mediaContainer: string | null;
  durationSeconds: number;
  videoPacketBytesExpectedDurationSeconds: number;
  stateDetails: JsonObject;
} {
  const streams = Array.isArray(probePayload.streams) ? probePayload.streams : [];
  const format = asJsonObject(probePayload.format);
  const videoStreams = streams
    .map((stream) => asJsonObject(stream))
    .filter((stream): stream is JsonObject => stream != null && stream.codec_type === 'video');
  const nonVideoStreams = streams
    .map((stream) => asJsonObject(stream))
    .filter((stream): stream is JsonObject => stream != null && stream.codec_type !== 'video');
  if (videoStreams.length !== 1) {
    throw new Error(`Expected exactly one video stream, found ${videoStreams.length}`);
  }
  if (nonVideoStreams.length > 0) {
    throw new Error('Canonical encoded artifacts must not contain auxiliary audio/subtitle/data streams');
  }

  const video = videoStreams[0]!;
  const frames = (Array.isArray(probePayload.frames) ? probePayload.frames : [])
    .map((frame) => asJsonObject(frame))
    .filter((frame): frame is JsonObject => frame != null && frame.media_type === 'video');
  const width = Number(video.width ?? 0);
  const height = Number(video.height ?? 0);
  if (width !== bundle.run.testClip.width || height !== bundle.run.testClip.height) {
    throw new Error(`Encoded dimensions ${width}x${height} do not match canonical clip ${bundle.run.testClip.width}x${bundle.run.testClip.height}`);
  }

  const frameRate = parseRatio(String(video.avg_frame_rate ?? video.r_frame_rate ?? ''));
  const expectedFrameRate = bundle.run.testClip.frameRateNumerator / bundle.run.testClip.frameRateDenominator;
  if (frameRate == null || !approxEqual(frameRate, expectedFrameRate, 0.01)) {
    throw new Error(`Encoded frame rate ${frameRate ?? 'unknown'} does not match canonical clip ${expectedFrameRate}`);
  }

  const pixelFormat = String(video.pix_fmt ?? '');
  if (pixelFormat && pixelFormat.toLowerCase() !== bundle.run.recipe.pixelFormat.toLowerCase()) {
    throw new Error(`Encoded pixel format ${pixelFormat} does not match recipe ${bundle.run.recipe.pixelFormat}`);
  }

  const bitDepth = inferBitDepth(pixelFormat, video.bits_per_raw_sample != null ? Number(video.bits_per_raw_sample) : null);
  if (bitDepth != null && bitDepth !== bundle.run.recipe.bitDepth) {
    throw new Error(`Encoded bit depth ${bitDepth} does not match recipe ${bundle.run.recipe.bitDepth}`);
  }

  const chroma = inferChromaSubsampling(pixelFormat);
  if (chroma && chroma !== bundle.run.recipe.chromaSubsampling) {
    throw new Error(`Encoded chroma subsampling ${chroma} does not match recipe ${bundle.run.recipe.chromaSubsampling}`);
  }

  const mediaContainer = inferMediaContainerFromFormatName(String(format?.format_name ?? ''));
  const expectedContainer = bundle.run.recipe.containerFormat?.toLowerCase() ?? null;
  if (expectedContainer && mediaContainer && !mediaContainer.includes(expectedContainer)) {
    throw new Error(`Encoded container ${mediaContainer} does not match recipe ${expectedContainer}`);
  }

  const codecName = String(video.codec_name ?? '').toLowerCase();
  const codecFamily = bundle.run.recipe.codecFamily.toLowerCase();
  if (codecName && !codecName.includes(codecFamily.replace('h265', 'hevc'))) {
    if (!(codecFamily === 'h264' && codecName.includes('avc')) && !(codecFamily === 'hevc' && codecName.includes('h265'))) {
      throw new Error(`Encoded codec ${codecName} does not match recipe family ${codecFamily}`);
    }
  }

  const observedCodecTag = String(video.codec_tag_string ?? '').toLowerCase() || null;
  if (bundle.run.recipe.videoCodecTag && observedCodecTag !== bundle.run.recipe.videoCodecTag.toLowerCase()) {
    throw new Error(`Encoded codec tag ${observedCodecTag ?? 'unknown'} does not match recipe ${bundle.run.recipe.videoCodecTag}`);
  }
  const observedProfile = String(video.profile ?? '').toLowerCase() || null;
  if (bundle.run.recipe.profile && observedProfile !== bundle.run.recipe.profile.toLowerCase()) {
    throw new Error(`Encoded profile ${observedProfile ?? 'unknown'} does not match recipe ${bundle.run.recipe.profile}`);
  }
  const observedLevel = video.level == null ? null : String(video.level).toLowerCase();
  if (bundle.run.recipe.level && observedLevel !== bundle.run.recipe.level.toLowerCase()) {
    throw new Error(`Encoded level ${observedLevel ?? 'unknown'} does not match recipe ${bundle.run.recipe.level}`);
  }
  const colorExpectations: ReadonlyArray<[string, unknown, string | null | undefined]> = [
    ['color primaries', video.color_primaries, bundle.run.testClip.colorPrimaries],
    ['transfer characteristics', video.color_transfer, bundle.run.testClip.transferCharacteristics],
    ['matrix coefficients', video.color_space, bundle.run.testClip.matrixCoefficients],
    ['color range', video.color_range, bundle.run.testClip.colorRange],
  ];
  for (const [label, observedRaw, expectedRaw] of colorExpectations) {
    if (expectedRaw && String(observedRaw ?? '').toLowerCase() !== expectedRaw.toLowerCase()) {
      throw new Error(`Encoded ${label} ${String(observedRaw ?? 'unknown')} does not match source ${expectedRaw}`);
    }
  }
  const observedBFrames = Number(video.has_b_frames ?? 0);
  if (bundle.run.recipe.bFrames === 0 && observedBFrames !== 0) {
    throw new Error(`Encoded stream contains B-frame reordering but recipe requires none`);
  }
  if (bundle.run.recipe.frameReordering === false && observedBFrames !== 0) {
    throw new Error(`Encoded stream reorders frames but recipe disables frame reordering`);
  }
  const keyframeIndexes = frames
    .map((frame, index) => Number(frame.key_frame ?? 0) === 1 ? index : null)
    .filter((index): index is number => index != null);
  const expectedKeyframeInterval = bundle.run.recipe.keyframeInterval ?? bundle.run.recipe.gopSize;
  if (expectedKeyframeInterval != null && keyframeIndexes.length > 1) {
    const intervals = keyframeIndexes.slice(1).map((index, offset) => index - keyframeIndexes[offset]!);
    if (intervals.some((interval) => interval > expectedKeyframeInterval)) {
      throw new Error(`Encoded keyframe interval exceeds recipe maximum ${expectedKeyframeInterval}`);
    }
  }

  const durationSeconds = Number(format?.duration ?? bundle.run.testClip.exactDurationSeconds);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw new Error('Unable to determine encoded artifact duration');
  }

  return {
    mediaContainer,
    durationSeconds,
    videoPacketBytesExpectedDurationSeconds: durationSeconds,
    stateDetails: {
      validatedAt: nowIso(),
      probe: probePayload,
      expected: {
        width: bundle.run.testClip.width,
        height: bundle.run.testClip.height,
        frameRate: expectedFrameRate,
        pixelFormat: bundle.run.recipe.pixelFormat,
        bitDepth: bundle.run.recipe.bitDepth,
        chromaSubsampling: bundle.run.recipe.chromaSubsampling,
      },
      observed: {
        codecName,
        codecTag: observedCodecTag,
        profile: observedProfile,
        level: observedLevel,
        hasBFrames: observedBFrames,
        keyframeIndexes,
        width,
        height,
        frameRate,
        pixelFormat,
        bitDepth,
        chromaSubsampling: chroma,
        mediaContainer,
      },
    },
  };
}

async function streamPacketEvidence(filePath: string): Promise<{ bytes: number; packetCount: number }> {
  return await new Promise<{ bytes: number; packetCount: number }>((resolve, reject) => {
    const child = spawn('ffprobe', [
      '-v', 'error',
      '-select_streams', 'v:0',
      '-show_entries', 'packet=size',
      '-of', 'csv=p=0',
      filePath,
    ]);
    let total = 0;
    let packetCount = 0;
    let pending = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => {
      pending += chunk;
      let newlineIndex = pending.indexOf('\n');
      while (newlineIndex >= 0) {
        const line = pending.slice(0, newlineIndex).trim();
        if (line) {
          total += Number(line);
          packetCount += 1;
        }
        pending = pending.slice(newlineIndex + 1);
        newlineIndex = pending.indexOf('\n');
      }
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk: string) => {
      stderr += chunk;
    });
    child.once('error', reject);
    child.once('close', (code) => {
      const line = pending.trim();
      if (line) {
        total += Number(line);
        packetCount += 1;
      }
      if (code !== 0) {
        reject(new Error(stderr || `ffprobe packet scan failed with exit code ${code}`));
        return;
      }
      resolve({ bytes: total, packetCount });
    });
  });
}

async function probeMedia(filePath: string): Promise<JsonObject> {
  const { stdout } = await execFileAsync('ffprobe', [
    '-v', 'error',
    '-print_format', 'json',
    '-show_format',
    '-show_streams',
    '-show_frames',
    filePath,
  ], { maxBuffer: 10 * 1024 * 1024 });
  return JSON.parse(stdout) as JsonObject;
}

async function readFfmpegVersion(): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync('ffmpeg', ['-version'], { maxBuffer: 1024 * 1024 });
    return stdout.split('\n')[0]?.trim() || null;
  } catch {
    return null;
  }
}

function resolveReferencePath(sourceProvenance: unknown): string {
  const provenance = asJsonObject(sourceProvenance);
  const candidates = [
    provenance?.referencePath,
    provenance?.localPath,
    provenance?.canonicalPath,
    provenance?.path,
  ];
  const value = candidates.find((candidate): candidate is string => typeof candidate === 'string' && candidate.trim().length > 0);
  if (!value) {
    throw new Error('Canonical source provenance does not provide a local reference path');
  }
  return value;
}

function flattenCliTokens(values: ReadonlyArray<string>): string[] {
  return values.flatMap((value) => value.split(' ').map((part) => part.trim()).filter(Boolean));
}

async function ensureCanonicalReferencePath(testClip: StoredTestClip): Promise<string> {
  const provenance = asJsonObject(testClip.sourceProvenance);
  const candidates = provenance ? [
    provenance.referencePath,
    provenance.localPath,
    provenance.canonicalPath,
    provenance.path,
  ] : [];
  for (const candidate of candidates) {
    if (typeof candidate !== 'string' || !candidate.trim()) continue;
    if (await fileExists(candidate)) {
      const existingBytes = await readFile(candidate);
      if (sha256Hex(existingBytes) === testClip.sha256) {
        return candidate;
      }
    }
  }

  const acquisition = asJsonObject(provenance?.acquisition);
  const fileName = typeof provenance?.fileName === 'string' ? provenance.fileName : `${testClip.workloadId}.mkv`;
  if (!acquisition || acquisition.kind !== 'generated' || typeof acquisition.ffmpegLavfi !== 'string') {
    throw new Error('Canonical source provenance does not provide a resolvable local path or deterministic generation recipe');
  }

  const deterministicFlags = Array.isArray(acquisition.deterministicFlags)
    ? acquisition.deterministicFlags.filter((value): value is string => typeof value === 'string')
    : [];
  const outputDir = path.join(os.tmpdir(), 'encodingdb-canonical-references');
  await mkdir(outputDir, { recursive: true });
  const absolutePath = path.join(outputDir, `${testClip.sha256}-${fileName}`);
  if (await fileExists(absolutePath)) {
    const cachedBytes = await readFile(absolutePath);
    if (sha256Hex(cachedBytes) === testClip.sha256) {
      return absolutePath;
    }
  }

  const tempDir = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-reference-build-'));
  const tempPath = path.join(tempDir, fileName);
  try {
    const ffmpegArgs = [
      '-hide_banner',
      '-loglevel', 'error',
      ...flattenCliTokens(deterministicFlags),
      '-f', 'lavfi',
      '-i', acquisition.ffmpegLavfi,
      '-frames:v', String(testClip.exactFrameCount),
      '-an',
      '-c:v', String(acquisition.videoCodec || 'ffv1'),
      '-pix_fmt', testClip.pixelFormat,
      ...(testClip.colorPrimaries ? ['-color_primaries', testClip.colorPrimaries] : []),
      ...(testClip.transferCharacteristics ? ['-color_trc', testClip.transferCharacteristics] : []),
      ...(testClip.matrixCoefficients ? ['-colorspace', testClip.matrixCoefficients] : []),
      ...(testClip.colorRange ? ['-color_range', testClip.colorRange] : []),
      tempPath,
    ];
    await execFileAsync('ffmpeg', ffmpegArgs, { maxBuffer: 10 * 1024 * 1024 });
    const builtBytes = await readFile(tempPath);
    const builtHash = sha256Hex(builtBytes);
    if (builtHash !== testClip.sha256) {
      throw new Error(`Generated canonical reference hash ${builtHash} did not match manifest ${testClip.sha256}`);
    }
    if (builtBytes.length !== testClip.byteSize) {
      throw new Error(`Generated canonical reference size ${builtBytes.length} did not match manifest ${testClip.byteSize}`);
    }
    const probe = await probeMedia(tempPath);
    const stream = Array.isArray(probe.streams) ? probe.streams.find((entry) => asJsonObject(entry)?.codec_type === 'video') : null;
    const video = asJsonObject(stream);
    if (!video || Number(video.width) !== testClip.width || Number(video.height) !== testClip.height) {
      throw new Error('Generated canonical reference did not match expected clip dimensions');
    }
    await ensureParentDir(absolutePath);
    await copyFile(tempPath, absolutePath);
    return absolutePath;
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
}

async function runFfmpegQualityFilter(args: string[]): Promise<string> {
  const { stderr } = await execFileAsync('ffmpeg', args, {
    maxBuffer: 10 * 1024 * 1024,
  });
  return stderr;
}

export class FfmpegArtifactAnalyzer implements ArtifactAnalyzer {
  private readonly vmafModelPath: string;

  constructor(private readonly analyzerVersion: string) {
    this.vmafModelPath = fileURLToPath(new URL(`../../resources/vmaf/${VMAF_MODEL_FILENAME}`, import.meta.url));
  }

  async analyze(input: AnalyzeArtifactInput): Promise<AuthoritativeAnalysisResult> {
    const probePayload = await probeMedia(input.artifactPath);
    const packetEvidence = await streamPacketEvidence(input.artifactPath);
    const ffmpegVersion = await readFfmpegVersion();
    const validation = validateProbeAgainstRun(input.bundle, probePayload);
    const referencePath = await ensureCanonicalReferencePath(input.bundle.run.testClip);
    const referenceStats = await stat(referencePath);
    if (!referenceStats.isFile()) {
      throw new Error(`Canonical reference path ${referencePath} is not a file`);
    }

    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-quality-'));
    try {
      const vmafLogPath = path.join(tempDir, 'vmaf.json');
      const source = {
        width: input.bundle.run.testClip.width,
        height: input.bundle.run.testClip.height,
        frameRate: input.bundle.run.testClip.frameRateNumerator / input.bundle.run.testClip.frameRateDenominator,
        dynamicRange: 'sdr' as const,
      };
      const plan = resolveQualityAnalysisExecutionPlan(source, this.vmafModelPath, vmafLogPath);
      await execFileAsync('ffmpeg', [
        '-hide_banner',
        '-loglevel', 'error',
        '-i', input.artifactPath,
        '-i', referencePath,
        '-lavfi', plan.filterGraph,
        '-an',
        '-f', 'null',
        '-',
      ], { maxBuffer: 10 * 1024 * 1024 });
      const vmafReport = await readFile(vmafLogPath, 'utf8');
      const xpsnrReport = await runFfmpegQualityFilter([
        '-hide_banner',
        '-i', input.artifactPath,
        '-i', referencePath,
        '-lavfi', '[0:v][1:v]xpsnr',
        '-an',
        '-f', 'null',
        '-',
      ]);
      const ssimReport = await runFfmpegQualityFilter([
        '-hide_banner',
        '-i', input.artifactPath,
        '-i', referencePath,
        '-lavfi', '[0:v][1:v]ssim',
        '-an',
        '-f', 'null',
        '-',
      ]);
      const psnrReport = await runFfmpegQualityFilter([
        '-hide_banner',
        '-i', input.artifactPath,
        '-i', referencePath,
        '-lavfi', '[0:v][1:v]psnr',
        '-an',
        '-f', 'null',
        '-',
      ]);

      const authoritative = buildAuthoritativeQualityAnalysisRecord({
        source,
        metricModelPath: this.vmafModelPath,
        analysisWorkerVersion: input.requestedAnalysisWorkerVersion || input.bundle.run.benchmarkProtocol.metricWorkerVersion || this.analyzerVersion,
        vmafReport,
        xpsnrReport,
        ssimReport,
        psnrReport,
        ffmpegVersion,
      });

      const fileStats = await stat(input.artifactPath);
      const videoBitrateBps = packetEvidence.bytes > 0
        ? Number(((packetEvidence.bytes * 8) / validation.videoPacketBytesExpectedDurationSeconds).toFixed(6))
        : null;
      const containerBitrateBps = fileStats.size > 0
        ? Number(((fileStats.size * 8) / validation.durationSeconds).toFixed(6))
        : null;
      const suspicious = authoritative.metricDisagreement.flagged;
      return {
        metricModelId: input.requestedMetricModelId || authoritative.metricModelId,
        qualityContextId: authoritative.qualityContextId,
        analysisWorkerVersion: input.requestedAnalysisWorkerVersion || authoritative.analysisWorkerVersion,
        analysisStatus: suspicious ? 'SUSPECT' : 'COMPLETE',
        analysisProvenance: {
          ...authoritative.analysisProvenance,
          pipelineVersion: ARTIFACT_PIPELINE_VERSION,
          ffprobeValidatedAt: nowIso(),
          referencePath,
          packetByteMethod: 'ffprobe-video-packet-size-sum',
        },
        vmafMean: authoritative.vmafMean,
        vmafMedian: authoritative.vmafMedian,
        vmafP1: authoritative.vmafP1,
        vmafP5: authoritative.vmafP5,
        vmafMin: authoritative.vmafMin,
        vmafMax: authoritative.vmafMax,
        vmafStdDev: authoritative.vmafStdDev,
        vmafHarmonicMean: authoritative.vmafHarmonicMean,
        worstFrameIndex: authoritative.worstFrameIndex,
        worstFrameTimestampMs: authoritative.worstFrameTimestampMs,
        belowThresholdFractions: authoritative.belowThresholdFractions,
        vmafDistribution: authoritative.vmafDistribution,
        xpsnr: authoritative.xpsnr,
        ssim: authoritative.ssim,
        psnr: authoritative.psnr,
        videoBitrateBps,
        videoPayloadBytes: packetEvidence.bytes,
        videoPacketCount: packetEvidence.packetCount,
        measuredDurationSeconds: validation.videoPacketBytesExpectedDurationSeconds,
        bitrateMethod: 'ffprobe-video-packet-size-sum',
        containerBitrateBps,
        fileSizeBytes: fileStats.size,
        runStatus: suspicious ? 'SUSPECT' : 'ACCEPTED',
        runStatusReason: suspicious ? 'Metric disagreement diagnostics flagged the run for review' : null,
        artifactState: suspicious ? 'VERIFIED' : 'RETAINED',
        artifactStateReason: suspicious ? 'Awaiting manual review after analysis disagreement diagnostic' : null,
        artifactStateDetails: validation.stateDetails,
      };
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  }
}

class WindowCounter {
  private readonly windows = new Map<string, { resetAt: number; count: number }>();

  constructor(
    private readonly max: number,
    private readonly windowMs: number,
  ) {}

  check(key: string): boolean {
    const now = Date.now();
    const current = this.windows.get(key);
    if (!current || current.resetAt <= now) {
      this.windows.set(key, { resetAt: now + this.windowMs, count: 1 });
      return true;
    }
    current.count += 1;
    if (current.count > this.max) return false;
    return true;
  }
}

function requestIp(req: express.Request): string {
  return String(req.ip || req.headers['x-forwarded-for'] || 'unknown');
}

function buildUploadToken(payload: {
  artifactId: string;
  benchmarkRunId: string;
  role: ArtifactRoleValue;
  sha256: string;
  byteSize: number;
  contentType: string | null;
  exp: number;
}): JsonObject {
  return payload;
}

function bundleToResponse(bundle: RunArtifactBundle): JsonObject {
  return {
    benchmarkRun: {
      id: bundle.run.id,
      status: bundle.run.status,
      statusReason: bundle.run.statusReason,
      workloadId: bundle.run.workloadId,
      clientQualityDebug: bundle.run.clientQualityDebug ?? null,
      energyDomains: bundle.run.energyDomains ?? null,
      decodeBenchmark: bundle.run.decodeBenchmark ?? null,
    },
    artifact: {
      id: bundle.artifact.id,
      role: bundle.artifact.role,
      sha256: bundle.artifact.sha256,
      byteSize: bundle.artifact.byteSize,
      storageState: bundle.artifact.storageState,
      stateReason: bundle.artifact.stateReason,
      mediaContainer: bundle.artifact.mediaContainer,
      storageKey: bundle.artifact.storageKey,
      uploadedAt: bundle.artifact.uploadedAt?.toISOString() ?? null,
      verifiedAt: bundle.artifact.verifiedAt?.toISOString() ?? null,
      retainedAt: bundle.artifact.retainedAt?.toISOString() ?? null,
      deletedAt: bundle.artifact.deletedAt?.toISOString() ?? null,
    },
    analyses: bundle.qualityAnalyses
      .slice()
      .sort((left, right) => right.createdAt.getTime() - left.createdAt.getTime())
      .map((analysis) => ({
        id: analysis.id,
        status: analysis.status,
        metricModelId: analysis.metricModelId,
        qualityContextId: analysis.qualityContextId,
        analysisWorkerVersion: analysis.analysisWorkerVersion,
        vmafMean: analysis.vmafMean,
        vmafMedian: analysis.vmafMedian,
        vmafP1: analysis.vmafP1,
        vmafP5: analysis.vmafP5,
        vmafMin: analysis.vmafMin,
        vmafMax: analysis.vmafMax,
        vmafStdDev: analysis.vmafStdDev,
        vmafHarmonicMean: analysis.vmafHarmonicMean,
        worstFrameIndex: analysis.worstFrameIndex,
        worstFrameTimestampMs: analysis.worstFrameTimestampMs,
        belowThresholdFractions: analysis.belowThresholdFractions,
        vmafDistribution: analysis.vmafDistribution,
        analysisProvenance: analysis.analysisProvenance,
        xpsnr: analysis.xpsnr,
        ssim: analysis.ssim,
        psnr: analysis.psnr,
        videoBitrateBps: analysis.videoBitrateBps,
        videoPayloadBytes: analysis.videoPayloadBytes,
        videoPacketCount: analysis.videoPacketCount,
        measuredDurationSeconds: analysis.measuredDurationSeconds,
        bitrateMethod: analysis.bitrateMethod,
        containerBitrateBps: analysis.containerBitrateBps,
        fileSizeBytes: analysis.fileSizeBytes,
        createdAt: analysis.createdAt.toISOString(),
        updatedAt: analysis.updatedAt.toISOString(),
      })),
  };
}

export class ArtifactPipelineService {
  private readonly storage: LocalArtifactStorage;
  private readonly authLimiter: WindowCounter;
  private readonly uploadLimiter: WindowCounter;
  private readonly suiteManifest: SuiteV1Manifest;

  constructor(
    private readonly persistence: ArtifactPipelinePersistence,
    private readonly analyzer: ArtifactAnalyzer,
    private readonly config: ArtifactPipelineConfig,
    suiteManifest: SuiteV1Manifest,
    private readonly onDerivedRecompute: ((payload: DerivedRecomputeHookPayload) => Promise<void> | void) | undefined,
  ) {
    this.storage = new LocalArtifactStorage(config.storage);
    this.authLimiter = new WindowCounter(config.authRateLimitMax, config.authRateLimitWindowMs);
    this.uploadLimiter = new WindowCounter(config.uploadRateLimitMax, config.uploadRateLimitWindowMs);
    this.suiteManifest = suiteManifest;
  }

  async createRun(input: CreateRunRequestInput): Promise<{ bundle: RunArtifactBundle; created: boolean }> {
    const resolvedInput = await this.resolveCreateRunInput(input);
    return await this.persistence.createOrFetchRun(resolvedInput);
  }

  async authorizeUpload(ip: string, benchmarkRunId: string, role: ArtifactRoleValue, body: z.infer<typeof UPLOAD_AUTH_SCHEMA>): Promise<JsonObject> {
    if (!this.authLimiter.check(ip)) {
      throw new HttpError(429, 'Artifact upload authorization rate limit exceeded');
    }
    const bundle = await this.requireBundle(benchmarkRunId, role);
    if (body.byteSize > this.config.maxArtifactBytes) {
      throw new HttpError(413, 'Artifact exceeds maximum allowed size');
    }
    if (body.contentType && !this.config.allowedMimeTypes.has(body.contentType)) {
      throw new HttpError(415, 'Artifact content type is not allowed');
    }
    if (bundle.artifact.storageState === 'RETAINED' || bundle.artifact.storageState === 'VERIFIED' || bundle.artifact.storageState === 'UPLOADED') {
      if (bundle.artifact.sha256 === body.sha256 && bundle.artifact.byteSize === body.byteSize) {
        return {
          uploadRequired: false,
          reason: 'artifact-already-bound',
          ...bundleToResponse(bundle),
        };
      }
      throw new HttpError(409, 'Artifact is already bound to immutable run metadata');
    }
    if (bundle.artifact.sha256 !== body.sha256 || bundle.artifact.byteSize !== body.byteSize) {
      throw new HttpError(409, 'Upload authorization must match immutable artifact metadata');
    }

    const existingObject = await this.storage.linkExistingObject(body.sha256, body.byteSize);
    if (existingObject) {
      const uploaded = await this.persistence.markArtifactUploaded({
        artifactId: bundle.artifact.id,
        sha256: body.sha256,
        byteSize: body.byteSize,
        mediaContainer: bundle.artifact.mediaContainer,
        storageProvider: this.config.storage.provider,
        storageBucket: this.config.storage.bucket,
        storageKey: existingObject.key,
        storageUrl: existingObject.absolutePath,
        stateDetails: {
          reusedExistingObject: true,
          authorizedAt: nowIso(),
        },
      });
      const analyzed = this.config.autoAnalyzeOnUpload ? await this.analyzeArtifact(uploaded, undefined, undefined) : uploaded;
      return {
        uploadRequired: false,
        reason: 'deduplicated-by-sha256',
        ...bundleToResponse(analyzed),
      };
    }

    const exp = Date.now() + this.config.uploadTokenTtlMs;
    const token = signUploadToken(buildUploadToken({
      artifactId: bundle.artifact.id,
      benchmarkRunId,
      role,
      sha256: body.sha256,
      byteSize: body.byteSize,
      contentType: body.contentType ?? null,
      exp,
    }), this.config.uploadTokenSecret);
    return {
      uploadRequired: true,
      token,
      expiresAt: new Date(exp).toISOString(),
    };
  }

  async acceptUpload(ip: string, token: string, contentType: string | null, body: Buffer): Promise<RunArtifactBundle> {
    if (!this.uploadLimiter.check(ip)) {
      throw new HttpError(429, 'Artifact upload rate limit exceeded');
    }
    const payload = verifyUploadToken(token, this.config.uploadTokenSecret);
    const exp = Number(payload.exp);
    if (!Number.isFinite(exp) || exp < Date.now()) {
      throw new HttpError(401, 'Artifact upload authorization expired');
    }
    const artifactId = String(payload.artifactId || '');
    const benchmarkRunId = String(payload.benchmarkRunId || '');
    const role = String(payload.role || '');
    const sha256 = String(payload.sha256 || '');
    const byteSize = Number(payload.byteSize);
    const expectedContentType = payload.contentType == null ? null : String(payload.contentType);
    assertArtifactRole(role);
    const bundle = await this.requireBundle(benchmarkRunId, role);
    if (bundle.artifact.id !== artifactId) {
      throw new HttpError(409, 'Upload token scope does not match artifact binding');
    }
    if (body.byteLength !== byteSize) {
      await this.persistence.markArtifactState({
        artifactId,
        storageState: 'REJECTED',
        stateReason: 'Artifact size mismatch during upload',
        stateDetails: {
          expectedBytes: byteSize,
          observedBytes: body.byteLength,
        },
      });
      throw new HttpError(400, 'Artifact byte size does not match authorization');
    }
    if (body.byteLength > this.config.maxArtifactBytes) {
      throw new HttpError(413, 'Artifact exceeds maximum allowed size');
    }
    if (expectedContentType && contentType && expectedContentType !== contentType) {
      throw new HttpError(415, 'Artifact content type does not match authorization');
    }
    if (contentType && !this.config.allowedMimeTypes.has(contentType)) {
      throw new HttpError(415, 'Artifact content type is not allowed');
    }
    const observedHash = sha256Hex(body);
    if (observedHash !== sha256) {
      await this.persistence.markArtifactState({
        artifactId,
        storageState: 'REJECTED',
        stateReason: 'Artifact sha256 mismatch during upload',
        stateDetails: {
          expectedSha256: sha256,
          observedSha256: observedHash,
        },
      });
      throw new HttpError(400, 'Artifact sha256 does not match authorization');
    }
    if (bundle.artifact.storageState === 'UPLOADED' || bundle.artifact.storageState === 'VERIFIED' || bundle.artifact.storageState === 'RETAINED') {
      if (bundle.artifact.sha256 === observedHash && bundle.artifact.byteSize === body.byteLength) {
        return await this.config.autoAnalyzeOnUpload ? this.analyzeArtifact(bundle, undefined, undefined) : bundle;
      }
      throw new HttpError(409, 'Artifact already uploaded for this immutable run');
    }
    const stored = await this.storage.writeObject(observedHash, body);
    const uploaded = await this.persistence.markArtifactUploaded({
      artifactId,
      sha256: observedHash,
      byteSize: body.byteLength,
      mediaContainer: bundle.artifact.mediaContainer,
      storageProvider: this.config.storage.provider,
      storageBucket: this.config.storage.bucket,
      storageKey: stored.key,
      storageUrl: stored.absolutePath,
      stateDetails: {
        uploadedAt: nowIso(),
        contentType,
      },
    });
    return await this.config.autoAnalyzeOnUpload ? this.analyzeArtifact(uploaded, undefined, undefined) : uploaded;
  }

  async analyzeArtifact(
    bundleOrRunId: RunArtifactBundle | string,
    requestedAnalysisWorkerVersion: string | null | undefined,
    requestedMetricModelId: string | null | undefined,
  ): Promise<RunArtifactBundle> {
    const bundle = typeof bundleOrRunId === 'string'
      ? await this.requireBundle(bundleOrRunId, 'ENCODED')
      : bundleOrRunId;
    const artifactPath = bundle.artifact.storageUrl;
    if (!artifactPath) {
      throw new HttpError(409, 'Artifact has not been uploaded to object storage');
    }
    const targetWorkerVersion = requestedAnalysisWorkerVersion || bundle.run.benchmarkProtocol.metricWorkerVersion || this.config.analyzerVersion;
    const existing = await this.persistence.getQualityAnalysis(
      bundle.run.id,
      requestedMetricModelId || inferExistingMetricModelId(bundle) || deriveMetricModelFallback(bundle),
      targetWorkerVersion,
    );
    if (existing && existing.status !== 'FAILED') {
      return bundle;
    }
    try {
      const result = await this.analyzer.analyze({
        bundle,
        artifactPath,
        requestedAnalysisWorkerVersion: targetWorkerVersion,
        requestedMetricModelId: requestedMetricModelId ?? null,
      });
      const saved = await this.persistence.saveAuthoritativeAnalysis({
        benchmarkRunId: bundle.run.id,
        artifactId: bundle.artifact.id,
        result,
      });
      if (this.onDerivedRecompute) {
        await this.onDerivedRecompute({
          benchmarkRunId: bundle.run.id,
          artifactId: bundle.artifact.id,
          metricModelId: result.metricModelId,
          analysisWorkerVersion: result.analysisWorkerVersion,
        });
      }
      return saved;
    } catch (error) {
      await this.persistence.markArtifactState({
        artifactId: bundle.artifact.id,
        storageState: 'REJECTED',
        stateReason: normalizeError(error),
        stateDetails: {
          failedAt: nowIso(),
          phase: 'analysis',
        },
      });
      throw error;
    }
  }

  async getBundle(benchmarkRunId: string, role: ArtifactRoleValue): Promise<RunArtifactBundle | null> {
    return await this.persistence.getRunArtifact(benchmarkRunId, role);
  }

  private async requireBundle(benchmarkRunId: string, role: ArtifactRoleValue): Promise<RunArtifactBundle> {
    const bundle = await this.persistence.getRunArtifact(benchmarkRunId, role);
    if (!bundle) {
      throw new HttpError(404, `Benchmark run ${benchmarkRunId} with artifact role ${role} was not found`);
    }
    return bundle;
  }

  private async resolveCreateRunInput(input: CreateRunRequestInput): Promise<CreateRunInput> {
    const canonicalBenchmarkProtocol = assertCanonicalProtocolRules(input.benchmarkProtocol, this.suiteManifest.suiteVersion);
    const benchmarkProtocol = await this.persistence.resolveOrBootstrapBenchmarkProtocol(canonicalBenchmarkProtocol);
    if (benchmarkProtocol.state && benchmarkProtocol.state !== 'ACTIVE') {
      throw new HttpError(409, `Benchmark protocol ${benchmarkProtocol.protocolVersion} is not active`);
    }

    const clip = this.resolveSuiteClip(input.testClip);
    if (benchmarkProtocol.sourceSuiteVersion !== clip.suiteVersion) {
      throw new HttpError(409, `Benchmark protocol suite ${benchmarkProtocol.sourceSuiteVersion} is incompatible with clip suite ${clip.suiteVersion}`);
    }
    const testClip = await this.persistence.upsertCanonicalTestClip(
      buildSuiteTestClipRecordInput(this.suiteManifest, clip.entry),
    );
    if (input.workloadId && input.workloadId !== testClip.workloadId) {
      throw new HttpError(409, `Declared workloadId ${input.workloadId} does not match canonical clip workload ${testClip.workloadId}`);
    }
    if (input.testClip.workloadId && input.testClip.workloadId !== testClip.workloadId) {
      throw new HttpError(409, `Declared testClip workloadId ${input.testClip.workloadId} does not match canonical clip workload ${testClip.workloadId}`);
    }

    const recipe = await this.persistence.resolveOrBootstrapRecipe(input.recipe);
    const environment = await this.persistence.resolveOrBootstrapEnvironment(input.environment);
    if (!environment.clientVersion) {
      throw new HttpError(409, 'Resolved environment is missing canonical clientVersion');
    }
    assertClientVersionMeetsMinimum(environment.clientVersion, benchmarkProtocol.minimumClientVersion);
    assertMetricModelCompatibility(input.expectedMetricModelId ?? null, testClip);

    let energyDomains: ReturnType<typeof normalizeEnergyDomains>;
    let decodeBenchmark: ReturnType<typeof normalizeDecodeBenchmark>;
    try {
      energyDomains = normalizeEnergyDomains({
        measurements: (input.energyDomains ?? null) as readonly EnergyDomainInput[] | null,
        sourceFrameCount: input.sourceFrameCount ?? null,
        sourceDurationSeconds: input.sourceFrameCount && input.sourceFps
          ? input.sourceFrameCount / input.sourceFps
          : null,
      });
      decodeBenchmark = normalizeDecodeBenchmark(
        (input.decodeBenchmark ?? null) as DecodeBenchmarkInput | null,
      );
    } catch (error) {
      throw new HttpError(400, `Invalid telemetry evidence: ${normalizeError(error)}`);
    }

    return {
      benchmarkProtocolId: benchmarkProtocol.id,
      testClipId: testClip.id,
      workloadId: testClip.workloadId,
      recipeId: recipe.id,
      environmentId: environment.id,
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
      telemetry: input.telemetry,
      telemetrySources: input.telemetrySources,
      telemetryMissing: input.telemetryMissing,
      energyDomains,
      decodeBenchmark,
      preRunEnvironmentCheck: input.preRunEnvironmentCheck,
      ffmpegProgressTelemetry: input.ffmpegProgressTelemetry,
      clientQualityDebug: input.clientQualityDebug,
      artifact: {
        role: input.artifact.role,
        sha256: input.artifact.sha256,
        byteSize: input.artifact.byteSize,
        mediaContainer: input.artifact.mediaContainer ?? null,
      },
    };
  }

  private resolveSuiteClip(input: TestClipBootstrapInput): { suiteVersion: string; entry: SuiteV1Manifest['clips'][number] } {
    if (input.suiteId !== this.suiteManifest.suiteId) {
      throw new HttpError(409, `Suite ${input.suiteId} is not the authoritative canonical suite ${this.suiteManifest.suiteId}`);
    }
    if (input.suiteVersion !== this.suiteManifest.suiteVersion) {
      throw new HttpError(409, `Suite version ${input.suiteVersion} is incompatible with canonical suite ${this.suiteManifest.suiteVersion}`);
    }
    const byClipKey = input.clipKey
      ? this.suiteManifest.clips.find((clip) => clip.id === input.clipKey)
      : null;
    const bySha = input.sha256
      ? this.suiteManifest.clips.find((clip) => clip.sha256 === input.sha256)
      : null;
    const resolved = byClipKey ?? bySha ?? null;
    if (!resolved) {
      throw new HttpError(404, 'Canonical suite clip could not be resolved by clipKey or sha256');
    }
    if (byClipKey && bySha && byClipKey.id !== bySha.id) {
      throw new HttpError(409, 'clipKey and sha256 resolve to different canonical suite clips');
    }
    return {
      suiteVersion: this.suiteManifest.suiteVersion,
      entry: resolved,
    };
  }
}

function inferExistingMetricModelId(bundle: RunArtifactBundle): string | null {
  return bundle.qualityAnalyses[0]?.metricModelId ?? null;
}

function deriveMetricModelFallback(bundle: RunArtifactBundle): string {
  const source = {
    width: bundle.run.testClip.width,
    height: bundle.run.testClip.height,
    frameRate: bundle.run.testClip.frameRateNumerator / bundle.run.testClip.frameRateDenominator,
    dynamicRange: 'sdr' as const,
  };
  const modelPath = fileURLToPath(new URL(`../../resources/vmaf/${VMAF_MODEL_FILENAME}`, import.meta.url));
  return resolveQualityAnalysisExecutionPlan(source, modelPath).metricModelId;
}

class HttpError extends Error {
  constructor(
    readonly statusCode: number,
    message: string,
  ) {
    super(message);
  }
}

function serializeError(error: unknown): { status: number; body: JsonObject } {
  if (error instanceof z.ZodError) {
    return {
      status: 400,
      body: {
        error: 'Invalid payload',
        details: error.flatten(),
      },
    };
  }
  if (error instanceof HttpError) {
    return {
      status: error.statusCode,
      body: { error: error.message },
    };
  }
  return {
    status: 500,
    body: {
      error: normalizeError(error),
    },
  };
}

function transformConstantsFromScoreContext(value: unknown): {
  qualityExponent?: number;
  speedCurveRate?: number;
  speedSaturationRealtime?: number;
} {
  const object = asJsonObject(value);
  return {
    ...(typeof object?.qualityExponent === 'number' ? { qualityExponent: object.qualityExponent } : {}),
    ...(typeof object?.speedCurveRate === 'number' ? { speedCurveRate: object.speedCurveRate } : {}),
    ...(typeof object?.speedSaturationRealtime === 'number' ? { speedSaturationRealtime: object.speedSaturationRealtime } : {}),
  };
}

const REFERENCE_CONTEXT_DIRECTORY = new URL('../../config/reference-contexts/', import.meta.url);
let cachedReferenceContexts: readonly ReferenceContext[] | null = null;

function loadFrozenReferenceContexts(): readonly ReferenceContext[] {
  if (cachedReferenceContexts) return cachedReferenceContexts;
  const directoryPath = fileURLToPath(REFERENCE_CONTEXT_DIRECTORY);
  const files = readdirSync(directoryPath)
    .filter((name) => name.endsWith('.context.json'))
    .sort();
  cachedReferenceContexts = files.map((name) => loadReferenceContext(path.join(directoryPath, name)));
  return cachedReferenceContexts;
}

async function seedFrozenScoreContextsForProtocol(client: PrismaClient, benchmarkProtocolId: string, sourceSuiteVersion: string): Promise<void> {
  const allowTestOnly = process.env.ALLOW_TEST_ONLY_REFERENCE_CONTEXTS === '1';
  const contexts = loadFrozenReferenceContexts().filter((entry) => (
    entry.sourceSuiteVersion === sourceSuiteVersion
    && (entry.activation.productionActivationAllowed || allowTestOnly)
  ));
  for (const context of contexts) {
    for (const workload of buildScoreContextSeedRecords(context, benchmarkProtocolId)) {
      await client.scoreContext.upsert({
        where: {
          formulaVersion_contextVersion_workloadId_qualityModelId: {
            formulaVersion: context.formulaVersion,
            contextVersion: context.contextVersion,
            workloadId: workload.workloadId,
            qualityModelId: context.qualityModelId,
          },
        },
        create: {
          benchmarkProtocolId: workload.benchmarkProtocolId,
          formulaVersion: workload.formulaVersion,
          contextVersion: workload.contextVersion,
          workloadId: workload.workloadId,
          qualityModelId: workload.qualityModelId,
          workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps,
          transformConstants: workload.transformConstants as any,
          referenceFrontier: workload.referenceFrontier as any,
        } as any,
        update: {
          benchmarkProtocolId,
          workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps,
          transformConstants: workload.transformConstants as any,
          referenceFrontier: workload.referenceFrontier as any,
        } as any,
      });
    }
  }
}

export function createDefaultDerivedRecomputeCallback(client: PrismaClient) {
  return async (payload: DerivedRecomputeHookPayload): Promise<void> => {
    const triggerRun = await client.benchmarkRun.findUnique({
      where: { id: payload.benchmarkRunId },
      include: {
        benchmarkProtocol: true,
        testClip: true,
        recipe: true,
        environment: true,
      },
    });
    if (!triggerRun) return;

    let scoreContexts = await client.scoreContext.findMany({
      where: {
        benchmarkProtocolId: triggerRun.benchmarkProtocolId,
        workloadId: triggerRun.workloadId,
        qualityModelId: payload.metricModelId,
      },
      orderBy: { updatedAt: 'desc' },
    });
    if (!scoreContexts.length) {
      scoreContexts = await client.scoreContext.findMany({
        where: {
          benchmarkProtocolId: triggerRun.benchmarkProtocolId,
          workloadId: triggerRun.workloadId,
        },
        orderBy: { updatedAt: 'desc' },
      });
    }
    if (!scoreContexts.length) return;

    const analyses = await client.qualityAnalysis.findMany({
      where: {
        metricModelId: payload.metricModelId,
        benchmarkRun: {
          benchmarkProtocolId: triggerRun.benchmarkProtocolId,
          workloadId: triggerRun.workloadId,
          recipeId: triggerRun.recipeId,
          environmentId: triggerRun.environmentId,
        },
      },
      include: {
        benchmarkRun: true,
      },
      orderBy: [
        { updatedAt: 'desc' },
      ],
    });

    const latestPerRun = new Map<string, typeof analyses[number]>();
    for (const analysis of analyses) {
      if (!latestPerRun.has(analysis.benchmarkRunId)) {
        latestPerRun.set(analysis.benchmarkRunId, analysis);
      }
    }

    const aggregateAnalyses = [...latestPerRun.values()].map((analysis) => ({
      qualityAnalysisId: analysis.id,
      analysisWorkerVersion: analysis.analysisWorkerVersion,
      benchmarkRunId: analysis.benchmarkRunId,
      benchmarkRunStatus: analysis.benchmarkRun.status,
      qualityAnalysisStatus: analysis.status,
      encodeFps: analysis.benchmarkRun.encodeFps,
      sourceFps: analysis.benchmarkRun.sourceFps,
      videoBitrateBps: analysis.videoBitrateBps,
      fileSizeBytes: analysis.fileSizeBytes,
      vmafMean: analysis.vmafMean,
      vmafP5: analysis.vmafP5,
      repetitionGroupId: analysis.benchmarkRun.repetitionGroupId,
      campaignId: analysis.benchmarkRun.campaignId,
      machineKey: analysis.benchmarkRun.environmentId,
      contributorKey: null,
    }));

    for (const scoreContext of scoreContexts) {
      const transform = transformConstantsFromScoreContext(scoreContext.transformConstants);
      await persistDerivedResultAggregate(client, {
        identity: {
          kind: 'workload',
          benchmarkProtocolId: triggerRun.benchmarkProtocolId,
          protocolVersion: triggerRun.benchmarkProtocol.protocolVersion,
          sourceSuiteVersion: triggerRun.benchmarkProtocol.sourceSuiteVersion,
          workloadId: triggerRun.workloadId,
          testClipId: triggerRun.testClipId,
          recipeId: triggerRun.recipeId,
          recipeFingerprint: triggerRun.recipe.fingerprint,
          environmentId: triggerRun.environmentId,
          environmentFingerprint: triggerRun.environment.fingerprint,
          scoreContextId: scoreContext.id,
          scoreContextVersion: scoreContext.contextVersion,
          qualityModelId: scoreContext.qualityModelId,
          formulaVersion: scoreContext.formulaVersion,
        },
        scoreContext: {
          workloadId: scoreContext.workloadId,
          workloadReferenceBitrateBps: scoreContext.workloadReferenceBitrateBps,
          scoreFormulaVersion: '7.0',
          ...transform,
        },
        evidencePolicy: DEFAULT_RECOMMENDATION_EVIDENCE_POLICY,
        analyses: aggregateAnalyses,
      });

      await persistGeneralDerivedResultFromWorkloadEvidence(client as unknown as Parameters<typeof persistGeneralDerivedResultFromWorkloadEvidence>[0], {
        benchmarkProtocolId: triggerRun.benchmarkProtocolId,
        protocolVersion: triggerRun.benchmarkProtocol.protocolVersion,
        sourceSuiteVersion: triggerRun.benchmarkProtocol.sourceSuiteVersion,
        contextVersion: scoreContext.contextVersion,
        formulaVersion: scoreContext.formulaVersion,
        qualityModelId: scoreContext.qualityModelId,
        recipeId: triggerRun.recipeId,
        recipeFingerprint: triggerRun.recipe.fingerprint,
        environmentId: triggerRun.environmentId,
        environmentFingerprint: triggerRun.environment.fingerprint,
      });
    }
  };
}

export function createArtifactPipelineRouter(options: ArtifactPipelineOptions = {}): Router {
  const config = mergeArtifactPipelineConfig(options.config);
  const persistence = options.persistence ?? createPrismaArtifactPipelinePersistence(prisma);
  const analyzer = options.analyzer ?? new FfmpegArtifactAnalyzer(config.analyzerVersion);
  const suiteManifest = options.suiteManifest == null
    ? loadAuthoritativeSuiteManifest()
    : parseSuiteManifest(options.suiteManifest, 'artifact pipeline suite manifest');
  const onDerivedRecompute = options.onDerivedRecompute ?? createDefaultDerivedRecomputeCallback(prisma);
  const service = new ArtifactPipelineService(persistence, analyzer, config, suiteManifest, onDerivedRecompute);
  const router = Router();

  router.post('/v7/benchmark-runs', async (req, res) => {
    try {
      const input = RUN_CREATE_SCHEMA.parse(req.body);
      const normalizedInput: CreateRunRequestInput = {
        benchmarkProtocol: input.benchmarkProtocol,
        testClip: {
          suiteId: input.testClip.suiteId,
          suiteVersion: input.testClip.suiteVersion,
          clipKey: input.testClip.clipKey ?? null,
          sha256: input.testClip.sha256 ?? null,
          workloadId: input.testClip.workloadId ?? null,
        },
        recipe: input.recipe,
        environment: input.environment,
        payloadHash: input.payloadHash,
        workloadId: input.workloadId ?? null,
        expectedMetricModelId: input.expectedMetricModelId ?? null,
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
        telemetry: input.telemetry,
        telemetrySources: input.telemetrySources,
        telemetryMissing: input.telemetryMissing,
        energyDomains: input.energyDomains,
        decodeBenchmark: input.decodeBenchmark,
        preRunEnvironmentCheck: input.preRunEnvironmentCheck,
        ffmpegProgressTelemetry: input.ffmpegProgressTelemetry,
        clientQualityDebug: input.clientQualityDebug,
        artifact: {
          role: input.artifact.role,
          sha256: input.artifact.sha256,
          byteSize: input.artifact.byteSize,
          mediaContainer: input.artifact.mediaContainer ?? null,
        },
      };
      const created = await service.createRun(normalizedInput);
      res.status(created.created ? 201 : 200).json({
        created: created.created,
        ...bundleToResponse(created.bundle),
      });
    } catch (error) {
      const serialized = serializeError(error);
      res.status(serialized.status).json(serialized.body);
    }
  });

  router.post('/v7/benchmark-runs/:benchmarkRunId/artifacts/:role/upload-authorizations', async (req, res) => {
    try {
      const payload = UPLOAD_AUTH_SCHEMA.parse(req.body);
      const role = String(req.params.role || '');
      assertArtifactRole(role);
      const response = await service.authorizeUpload(requestIp(req), String(req.params.benchmarkRunId), role, payload);
      res.json(response);
    } catch (error) {
      const serialized = serializeError(error);
      res.status(serialized.status).json(serialized.body);
    }
  });

  router.put('/v7/artifact-uploads/:token', express.raw({ type: () => true, limit: config.maxArtifactBytes }), async (req, res) => {
    try {
      const body = Buffer.isBuffer(req.body) ? req.body : Buffer.from([]);
      const bundle = await service.acceptUpload(requestIp(req), String(req.params.token), req.get('content-type') ?? null, body);
      res.json(bundleToResponse(bundle));
    } catch (error) {
      const serialized = serializeError(error);
      res.status(serialized.status).json(serialized.body);
    }
  });

  router.post('/v7/benchmark-runs/:benchmarkRunId/artifacts/:role/reanalyze', async (req, res) => {
    try {
      const role = String(req.params.role || '');
      assertArtifactRole(role);
      if (role !== 'ENCODED') {
        throw new HttpError(400, 'Only encoded artifacts support authoritative reanalysis');
      }
      const payload = REANALYZE_SCHEMA.parse(req.body ?? {});
      const bundle = await service.analyzeArtifact(
        String(req.params.benchmarkRunId),
        payload.analysisWorkerVersion,
        payload.metricModelId,
      );
      res.json(bundleToResponse(bundle));
    } catch (error) {
      const serialized = serializeError(error);
      res.status(serialized.status).json(serialized.body);
    }
  });

  router.get('/v7/benchmark-runs/:benchmarkRunId/artifacts/:role', async (req, res) => {
    try {
      const role = String(req.params.role || '');
      assertArtifactRole(role);
      const bundle = await service.getBundle(String(req.params.benchmarkRunId), role);
      if (!bundle) {
        throw new HttpError(404, 'Artifact not found');
      }
      res.json(bundleToResponse(bundle));
    } catch (error) {
      const serialized = serializeError(error);
      res.status(serialized.status).json(serialized.body);
    }
  });

  return router;
}

function normalizeBundle(rawRun: any, role: ArtifactRoleValue): RunArtifactBundle {
  const artifact = (rawRun.artifacts as any[]).find((item) => item.role === role);
  if (!artifact) {
    throw new Error(`Benchmark run ${rawRun.id} is missing artifact role ${role}`);
  }
  return {
    run: {
      id: rawRun.id,
      benchmarkProtocolId: rawRun.benchmarkProtocolId,
      testClipId: rawRun.testClipId,
      workloadId: rawRun.workloadId,
      recipeId: rawRun.recipeId,
      environmentId: rawRun.environmentId,
      payloadHash: rawRun.payloadHash,
      inputHash: rawRun.inputHash,
      campaignId: rawRun.campaignId,
      repetitionGroupId: rawRun.repetitionGroupId,
      repetitionIndex: rawRun.repetitionIndex,
      encodeWallTimeMs: rawRun.encodeWallTimeMs,
      encodeFps: rawRun.encodeFps,
      sourceFps: rawRun.sourceFps,
      realTimeRatio: rawRun.realTimeRatio,
      sourceFrameCount: rawRun.sourceFrameCount,
      encodedFrameCount: rawRun.encodedFrameCount,
      telemetry: rawRun.telemetry,
      telemetrySources: rawRun.telemetrySources,
      telemetryMissing: rawRun.telemetryMissing,
      energyDomains: rawRun.energyDomains,
      decodeBenchmark: rawRun.decodeBenchmark,
      preRunEnvironmentCheck: rawRun.preRunEnvironmentCheck,
      ffmpegProgressTelemetry: rawRun.ffmpegProgressTelemetry,
      clientQualityDebug: rawRun.clientQualityDebug,
      status: rawRun.status,
      statusReason: rawRun.statusReason,
      benchmarkProtocol: {
        id: rawRun.benchmarkProtocol.id,
        protocolVersion: rawRun.benchmarkProtocol.protocolVersion,
        sourceSuiteVersion: rawRun.benchmarkProtocol.sourceSuiteVersion,
        minimumClientVersion: rawRun.benchmarkProtocol.minimumClientVersion,
        metricWorkerVersion: rawRun.benchmarkProtocol.metricWorkerVersion,
        canonicalRecipeRules: rawRun.benchmarkProtocol.canonicalRecipeRules,
        canonicalOutputRules: rawRun.benchmarkProtocol.canonicalOutputRules,
        state: rawRun.benchmarkProtocol.state,
      },
      testClip: {
        id: rawRun.testClip.id,
        workloadId: rawRun.testClip.workloadId,
        displayName: rawRun.testClip.displayName,
        sourceProvenance: rawRun.testClip.sourceProvenance,
        sha256: rawRun.testClip.sha256,
        byteSize: rawRun.testClip.byteSize,
        exactFrameCount: rawRun.testClip.exactFrameCount,
        exactDurationSeconds: rawRun.testClip.exactDurationSeconds,
        frameRateNumerator: rawRun.testClip.frameRateNumerator,
        frameRateDenominator: rawRun.testClip.frameRateDenominator,
        width: rawRun.testClip.width,
        height: rawRun.testClip.height,
        pixelFormat: rawRun.testClip.pixelFormat,
        bitDepth: rawRun.testClip.bitDepth,
        chromaSubsampling: rawRun.testClip.chromaSubsampling,
        colorPrimaries: rawRun.testClip.colorPrimaries,
        transferCharacteristics: rawRun.testClip.transferCharacteristics,
        matrixCoefficients: rawRun.testClip.matrixCoefficients,
        colorRange: rawRun.testClip.colorRange,
      },
      recipe: {
        id: rawRun.recipe.id,
        fingerprint: rawRun.recipe.fingerprint,
        canonicalJson: rawRun.recipe.canonicalJson,
        codecFamily: rawRun.recipe.codecFamily,
        encoderImplementation: rawRun.recipe.encoderImplementation,
        pixelFormat: rawRun.recipe.pixelFormat,
        bitDepth: rawRun.recipe.bitDepth,
        chromaSubsampling: rawRun.recipe.chromaSubsampling,
        containerFormat: rawRun.recipe.containerFormat,
        videoCodecTag: rawRun.recipe.videoCodecTag,
        profile: rawRun.recipe.profile,
        level: rawRun.recipe.level,
        gopSize: rawRun.recipe.gopSize,
        keyframeInterval: rawRun.recipe.keyframeInterval,
        bFrames: rawRun.recipe.bFrames,
        frameReordering: rawRun.recipe.frameReordering,
      },
      environment: {
        id: rawRun.environment.id,
        fingerprint: rawRun.environment.fingerprint,
        canonicalJson: rawRun.environment.canonicalJson,
        clientVersion: rawRun.environment.clientVersion,
        ffmpegVersion: rawRun.environment.ffmpegVersion,
      },
    },
    artifact: {
      id: artifact.id,
      benchmarkRunId: artifact.benchmarkRunId,
      role: artifact.role,
      sha256: artifact.sha256,
      byteSize: artifact.byteSize,
      storageState: artifact.storageState,
      storageProvider: artifact.storageProvider,
      storageBucket: artifact.storageBucket,
      storageKey: artifact.storageKey,
      storageUrl: artifact.storageUrl,
      mediaContainer: artifact.mediaContainer,
      stateReason: artifact.stateReason,
      stateDetails: artifact.stateDetails,
      uploadedAt: artifact.uploadedAt,
      verifiedAt: artifact.verifiedAt,
      retainedAt: artifact.retainedAt,
      deletedAt: artifact.deletedAt,
    },
    qualityAnalyses: (rawRun.qualityAnalyses as any[]).map((analysis) => ({
      id: analysis.id,
      benchmarkRunId: analysis.benchmarkRunId,
      artifactId: analysis.artifactId,
      status: analysis.status,
      metricModelId: analysis.metricModelId,
      qualityContextId: analysis.qualityContextId,
      analysisWorkerVersion: analysis.analysisWorkerVersion,
      analysisProvenance: analysis.analysisProvenance,
      vmafMean: analysis.vmafMean,
      vmafMedian: analysis.vmafMedian,
      vmafP1: analysis.vmafP1,
      vmafP5: analysis.vmafP5,
      vmafMin: analysis.vmafMin,
      vmafMax: analysis.vmafMax,
      vmafStdDev: analysis.vmafStdDev,
      vmafHarmonicMean: analysis.vmafHarmonicMean,
      worstFrameIndex: analysis.worstFrameIndex,
      worstFrameTimestampMs: analysis.worstFrameTimestampMs,
      belowThresholdFractions: analysis.belowThresholdFractions,
      vmafDistribution: analysis.vmafDistribution,
      xpsnr: analysis.xpsnr,
      ssim: analysis.ssim,
      psnr: analysis.psnr,
      videoBitrateBps: analysis.videoBitrateBps,
      videoPayloadBytes: analysis.videoPayloadBytes,
      videoPacketCount: analysis.videoPacketCount,
      measuredDurationSeconds: analysis.measuredDurationSeconds,
      bitrateMethod: analysis.bitrateMethod,
      containerBitrateBps: analysis.containerBitrateBps,
      fileSizeBytes: analysis.fileSizeBytes,
      createdAt: analysis.createdAt,
      updatedAt: analysis.updatedAt,
    })),
  };
}

const PRISMA_RUN_INCLUDE = {
  benchmarkProtocol: true,
  testClip: true,
  recipe: true,
  environment: true,
  artifacts: true,
  qualityAnalyses: true,
} as const;

export function createPrismaArtifactPipelinePersistence(client: PrismaClient): ArtifactPipelinePersistence {
  return {
    async resolveOrBootstrapBenchmarkProtocol(input) {
      const activeProtocol = await client.benchmarkProtocol.findFirst({
        where: { state: 'ACTIVE' },
        orderBy: { activatedAt: 'desc' },
      });
      if (activeProtocol && (
        activeProtocol.protocolVersion !== input.protocolVersion
        || activeProtocol.sourceSuiteVersion !== input.sourceSuiteVersion
        || activeProtocol.metricWorkerVersion !== input.metricWorkerVersion
      )) {
        throw new HttpError(
          409,
          `Server canonical protocol is ${activeProtocol.protocolVersion}/${activeProtocol.sourceSuiteVersion}/${activeProtocol.metricWorkerVersion}; client declared ${input.protocolVersion}/${input.sourceSuiteVersion}/${input.metricWorkerVersion}`,
        );
      }
      const existing = await client.benchmarkProtocol.findUnique({
        where: {
          protocolVersion_sourceSuiteVersion_metricWorkerVersion: {
            protocolVersion: input.protocolVersion,
            sourceSuiteVersion: input.sourceSuiteVersion,
            metricWorkerVersion: input.metricWorkerVersion,
          },
        },
      });
      const canonicalRecipeRules = toCanonicalJsonString(input.canonicalRecipeRules, 'benchmarkProtocol.canonicalRecipeRules');
      const canonicalOutputRules = toCanonicalJsonString(input.canonicalOutputRules, 'benchmarkProtocol.canonicalOutputRules');
      if (existing) {
        if (existing.minimumClientVersion !== input.minimumClientVersion) {
          throw new HttpError(409, `Benchmark protocol ${input.protocolVersion} minimum client version does not match stored canonical value`);
        }
        if (canonicalJsonString(existing.canonicalRecipeRules as JsonValue) !== canonicalRecipeRules) {
          throw new HttpError(409, `Benchmark protocol ${input.protocolVersion} canonicalRecipeRules do not match stored canonical value`);
        }
        if (canonicalJsonString(existing.canonicalOutputRules as JsonValue) !== canonicalOutputRules) {
          throw new HttpError(409, `Benchmark protocol ${input.protocolVersion} canonicalOutputRules do not match stored canonical value`);
        }
        await seedFrozenScoreContextsForProtocol(client, existing.id, existing.sourceSuiteVersion);
        return {
          id: existing.id,
          protocolVersion: existing.protocolVersion,
          sourceSuiteVersion: existing.sourceSuiteVersion,
          minimumClientVersion: existing.minimumClientVersion,
          metricWorkerVersion: existing.metricWorkerVersion,
          canonicalRecipeRules: existing.canonicalRecipeRules,
          canonicalOutputRules: existing.canonicalOutputRules,
          state: existing.state,
        };
      }
      const created = await client.benchmarkProtocol.create({
        data: {
          protocolVersion: input.protocolVersion,
          sourceSuiteVersion: input.sourceSuiteVersion,
          minimumClientVersion: input.minimumClientVersion,
          canonicalRecipeRules: input.canonicalRecipeRules as any,
          canonicalOutputRules: input.canonicalOutputRules as any,
          metricWorkerVersion: input.metricWorkerVersion,
          state: 'ACTIVE',
          activatedAt: new Date(),
        } as any,
      });
      await seedFrozenScoreContextsForProtocol(client, created.id, created.sourceSuiteVersion);
      return {
        id: created.id,
        protocolVersion: created.protocolVersion,
        sourceSuiteVersion: created.sourceSuiteVersion,
        minimumClientVersion: created.minimumClientVersion,
        metricWorkerVersion: created.metricWorkerVersion,
        canonicalRecipeRules: created.canonicalRecipeRules,
        canonicalOutputRules: created.canonicalOutputRules,
        state: created.state,
      };
    },
    async upsertCanonicalTestClip(input) {
      const existing = await client.testClip.findUnique({
        where: {
          suiteId_suiteVersion_clipKey: {
            suiteId: input.suiteId,
            suiteVersion: input.suiteVersion,
            clipKey: input.clipKey,
          },
        },
      });
      if (existing) {
        const canonicalExisting = canonicalJsonString({
          suiteId: existing.suiteId,
          suiteVersion: existing.suiteVersion,
          manifestVersion: existing.manifestVersion,
          clipKey: existing.clipKey,
          displayName: existing.displayName,
          workloadId: existing.workloadId,
          contentClass: existing.contentClass,
          sourceProvenance: existing.sourceProvenance as JsonValue,
          sha256: existing.sha256,
          byteSize: existing.byteSize,
          exactFrameCount: existing.exactFrameCount,
          exactDurationSeconds: existing.exactDurationSeconds,
          frameRateNumerator: existing.frameRateNumerator,
          frameRateDenominator: existing.frameRateDenominator,
          width: existing.width,
          height: existing.height,
          pixelFormat: existing.pixelFormat,
          bitDepth: existing.bitDepth,
          chromaSubsampling: existing.chromaSubsampling,
          colorPrimaries: existing.colorPrimaries,
          transferCharacteristics: existing.transferCharacteristics,
          matrixCoefficients: existing.matrixCoefficients,
          colorRange: existing.colorRange,
          scanType: existing.scanType,
          hdrMetadata: existing.hdrMetadata as JsonValue | null,
        } as JsonValue);
        const canonicalIncoming = canonicalJsonString(input as unknown as JsonValue);
        if (canonicalExisting !== canonicalIncoming) {
          throw new HttpError(409, `Canonical TestClip ${input.clipKey} already exists with immutable fields that differ from the current suite manifest`);
        }
        return {
          id: existing.id,
          workloadId: existing.workloadId,
          displayName: existing.displayName,
          sourceProvenance: existing.sourceProvenance,
          sha256: existing.sha256,
          byteSize: existing.byteSize,
          exactFrameCount: existing.exactFrameCount,
          exactDurationSeconds: existing.exactDurationSeconds,
          frameRateNumerator: existing.frameRateNumerator,
          frameRateDenominator: existing.frameRateDenominator,
          width: existing.width,
          height: existing.height,
          pixelFormat: existing.pixelFormat,
          bitDepth: existing.bitDepth,
          chromaSubsampling: existing.chromaSubsampling,
          colorPrimaries: existing.colorPrimaries,
          transferCharacteristics: existing.transferCharacteristics,
          matrixCoefficients: existing.matrixCoefficients,
          colorRange: existing.colorRange,
        };
      }
      const clip = await client.testClip.create({
        data: input as any,
      });
      return {
        id: clip.id,
        workloadId: clip.workloadId,
        displayName: clip.displayName,
        sourceProvenance: clip.sourceProvenance,
        sha256: clip.sha256,
        byteSize: clip.byteSize,
        exactFrameCount: clip.exactFrameCount,
        exactDurationSeconds: clip.exactDurationSeconds,
        frameRateNumerator: clip.frameRateNumerator,
        frameRateDenominator: clip.frameRateDenominator,
        width: clip.width,
        height: clip.height,
        pixelFormat: clip.pixelFormat,
        bitDepth: clip.bitDepth,
        chromaSubsampling: clip.chromaSubsampling,
        colorPrimaries: clip.colorPrimaries,
        transferCharacteristics: clip.transferCharacteristics,
        matrixCoefficients: clip.matrixCoefficients,
        colorRange: clip.colorRange,
      };
    },
    async resolveOrBootstrapRecipe(input) {
      const identity = asRecipeIdentityInput(input.identity);
      let fingerprintResult;
      try {
        fingerprintResult = buildRecipeFingerprint(identity);
      } catch (error) {
        throw new HttpError(400, `Invalid canonical recipe identity: ${normalizeError(error)}`);
      }
      if (fingerprintResult.fingerprint !== input.fingerprint) {
        throw new HttpError(409, 'Recipe fingerprint does not match canonical normalized identity');
      }
      assertCanonicalJsonMatch(fingerprintResult.canonicalJson, input.canonicalJson, 'recipe.canonicalJson');

      const existing = await client.recipe.findUnique({
        where: { fingerprint: input.fingerprint },
      });
      if (existing) {
        if (canonicalJsonString(existing.canonicalJson as JsonValue) !== fingerprintResult.canonicalJson) {
          throw new HttpError(409, `Recipe fingerprint ${input.fingerprint} already exists with different canonical JSON`);
        }
        return {
          id: existing.id,
          fingerprint: existing.fingerprint,
          canonicalJson: existing.canonicalJson,
          codecFamily: existing.codecFamily,
          encoderImplementation: existing.encoderImplementation,
          pixelFormat: existing.pixelFormat,
          bitDepth: existing.bitDepth,
          chromaSubsampling: existing.chromaSubsampling,
          containerFormat: existing.containerFormat,
          videoCodecTag: existing.videoCodecTag,
          profile: existing.profile,
          level: existing.level,
          gopSize: existing.gopSize,
          keyframeInterval: existing.keyframeInterval,
          bFrames: existing.bFrames,
          frameReordering: existing.frameReordering,
        };
      }

      const normalized = fingerprintResult.normalized;
      const created = await client.recipe.create({
        data: {
          fingerprint: fingerprintResult.fingerprint,
          canonicalJson: JSON.parse(fingerprintResult.canonicalJson),
          codecFamily: normalized.codecFamily,
          encoderImplementation: normalized.encoderImplementation,
          encoderVersion: normalized.encoderVersion,
          preset: normalized.preset,
          tune: normalized.tune,
          profile: normalized.profile,
          level: normalized.level,
          tier: normalized.tier,
          pixelFormat: normalized.pixelFormat,
          bitDepth: normalized.bitDepth,
          chromaSubsampling: normalized.chromaSubsampling,
          containerFormat: normalized.containerFormat,
          videoCodecTag: normalized.videoCodecTag,
          requestedRateControlMode: toPrismaRateControlMode(normalized.requestedRateControl.mode) as any,
          requestedQualityValue: normalized.requestedRateControl.qualityValue,
          requestedTargetBitrateKbps: normalized.requestedRateControl.targetBitrateKbps,
          requestedMaxBitrateKbps: normalized.requestedRateControl.maxBitrateKbps,
          requestedBufferSizeKbits: normalized.requestedRateControl.bufferSizeKbits,
          requestedQmin: normalized.requestedRateControl.qmin,
          requestedQmax: normalized.requestedRateControl.qmax,
          effectiveRateControlMode: toPrismaRateControlMode(normalized.effectiveRateControl.mode) as any,
          effectiveQualityValue: normalized.effectiveRateControl.qualityValue,
          effectiveTargetBitrateKbps: normalized.effectiveRateControl.targetBitrateKbps,
          effectiveMaxBitrateKbps: normalized.effectiveRateControl.maxBitrateKbps,
          effectiveBufferSizeKbits: normalized.effectiveRateControl.bufferSizeKbits,
          effectiveQmin: normalized.effectiveRateControl.qmin,
          effectiveQmax: normalized.effectiveRateControl.qmax,
          requestedRateControl: normalized.requestedRateControl as any,
          effectiveRateControl: normalized.effectiveRateControl as any,
          requestedOutputSettings: normalized.requestedOutputSettings as any,
          effectiveOutputSettings: normalized.effectiveOutputSettings as any,
          normalizedRequestedOptions: normalized.normalizedRequestedOptions as any,
          normalizedEffectiveOptions: normalized.normalizedEffectiveOptions as any,
          gopSize: normalized.gopSize,
          keyframeInterval: normalized.keyframeInterval,
          bFrames: normalized.bFrames,
          frameReordering: normalized.frameReordering,
          lookahead: normalized.lookahead,
          filmGrainSynthesis: normalized.filmGrainSynthesis as any,
          majorTools: normalized.majorTools as any,
        } as any,
      });
      return {
        id: created.id,
        fingerprint: created.fingerprint,
        canonicalJson: created.canonicalJson,
        codecFamily: created.codecFamily,
        encoderImplementation: created.encoderImplementation,
        pixelFormat: created.pixelFormat,
        bitDepth: created.bitDepth,
        chromaSubsampling: created.chromaSubsampling,
        containerFormat: created.containerFormat,
        videoCodecTag: created.videoCodecTag,
        profile: created.profile,
        level: created.level,
        gopSize: created.gopSize,
        keyframeInterval: created.keyframeInterval,
        bFrames: created.bFrames,
        frameReordering: created.frameReordering,
      };
    },
    async resolveOrBootstrapEnvironment(input) {
      const identity = asEnvironmentIdentityInput(input.identity);
      let fingerprintResult;
      try {
        fingerprintResult = buildEnvironmentFingerprint(identity);
      } catch (error) {
        throw new HttpError(400, `Invalid canonical environment identity: ${normalizeError(error)}`);
      }
      if (fingerprintResult.fingerprint !== input.fingerprint) {
        throw new HttpError(409, 'Environment fingerprint does not match canonical normalized identity');
      }
      assertCanonicalJsonMatch(fingerprintResult.canonicalJson, input.canonicalJson, 'environment.canonicalJson');
      const existing = await client.environment.findUnique({
        where: { fingerprint: input.fingerprint },
      });
      if (existing) {
        if (canonicalJsonString(existing.canonicalJson as JsonValue) !== fingerprintResult.canonicalJson) {
          throw new HttpError(409, `Environment fingerprint ${input.fingerprint} already exists with different canonical JSON`);
        }
        return {
          id: existing.id,
          fingerprint: existing.fingerprint,
          canonicalJson: existing.canonicalJson,
          clientVersion: existing.clientVersion,
          ffmpegVersion: existing.ffmpegVersion,
        };
      }
      const normalized = fingerprintResult.normalized;
      const created = await client.environment.create({
        data: {
          fingerprint: fingerprintResult.fingerprint,
          canonicalJson: JSON.parse(fingerprintResult.canonicalJson),
          cpuModel: normalized.cpuModel,
          cpuArchitecture: normalized.cpuArchitecture,
          physicalCoreCount: normalized.physicalCoreCount,
          logicalThreadCount: normalized.logicalThreadCount,
          gpuModel: normalized.gpuModel,
          selectedAcceleratorId: normalized.selectedAcceleratorId,
          selectedAccelerator: normalized.selectedAccelerator,
          driverVersion: normalized.driverVersion,
          osName: normalized.osName,
          osVersion: normalized.osVersion,
          ffmpegBuildFingerprint: normalized.ffmpegBuildFingerprint,
          ffmpegVersion: normalized.ffmpegVersion,
          encoderVersion: normalized.encoderVersion,
          clientVersion: normalized.clientVersion,
        } as any,
      });
      return {
        id: created.id,
        fingerprint: created.fingerprint,
        canonicalJson: created.canonicalJson,
        clientVersion: created.clientVersion,
        ffmpegVersion: created.ffmpegVersion,
      };
    },
    async createOrFetchRun(input) {
      const result = await client.$transaction(async (tx) => {
        const existing = await tx.benchmarkRun.findUnique({
          where: { payloadHash: input.payloadHash },
          include: PRISMA_RUN_INCLUDE,
        });
        if (existing) {
          return { run: existing, created: false };
        }
        const created = await tx.benchmarkRun.create({
          data: {
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
            telemetry: input.telemetry as any,
            telemetrySources: input.telemetrySources as any,
            telemetryMissing: input.telemetryMissing as any,
            energyDomains: input.energyDomains as any,
            decodeBenchmark: input.decodeBenchmark as any,
            preRunEnvironmentCheck: input.preRunEnvironmentCheck as any,
            ffmpegProgressTelemetry: input.ffmpegProgressTelemetry as any,
            clientQualityDebug: input.clientQualityDebug as any,
            artifacts: {
              create: {
                role: input.artifact.role,
                sha256: input.artifact.sha256,
                byteSize: input.artifact.byteSize,
                mediaContainer: input.artifact.mediaContainer ?? null,
              },
            },
          } as any,
          include: PRISMA_RUN_INCLUDE,
        });
        return { run: created, created: true };
      });
      return { bundle: normalizeBundle(result.run, input.artifact.role), created: result.created };
    },
    async getRunArtifact(benchmarkRunId, role) {
      const run = await client.benchmarkRun.findUnique({
        where: { id: benchmarkRunId },
        include: PRISMA_RUN_INCLUDE,
      });
      return run ? normalizeBundle(run, role) : null;
    },
    async getArtifactBySha256(sha256) {
      const artifact = await client.artifact.findFirst({
        where: { sha256 },
      });
      if (!artifact) return null;
      return {
        id: artifact.id,
        benchmarkRunId: artifact.benchmarkRunId,
        role: artifact.role as ArtifactRoleValue,
        sha256: artifact.sha256,
        byteSize: artifact.byteSize,
        storageState: artifact.storageState as ArtifactStorageStateValue,
        storageProvider: artifact.storageProvider,
        storageBucket: artifact.storageBucket,
        storageKey: artifact.storageKey,
        storageUrl: artifact.storageUrl,
        mediaContainer: artifact.mediaContainer,
        stateReason: (artifact as any).stateReason ?? null,
        stateDetails: (artifact as any).stateDetails ?? null,
        uploadedAt: (artifact as any).uploadedAt ?? null,
        verifiedAt: (artifact as any).verifiedAt ?? null,
        retainedAt: (artifact as any).retainedAt ?? null,
        deletedAt: (artifact as any).deletedAt ?? null,
      };
    },
    async markArtifactUploaded(input) {
      const run = await client.$transaction(async (tx) => {
        const artifact = await tx.artifact.update({
          where: { id: input.artifactId },
          data: {
            sha256: input.sha256,
            byteSize: input.byteSize,
            mediaContainer: input.mediaContainer,
            storageState: 'UPLOADED',
            storageProvider: input.storageProvider,
            storageBucket: input.storageBucket,
            storageKey: input.storageKey,
            storageUrl: input.storageUrl,
            stateReason: null,
            stateDetails: input.stateDetails as any,
            uploadedAt: new Date(),
          } as any,
        });
        return await tx.benchmarkRun.findUniqueOrThrow({
          where: { id: artifact.benchmarkRunId },
          include: PRISMA_RUN_INCLUDE,
        });
      });
      return normalizeBundle(run, 'ENCODED');
    },
    async markArtifactState(input) {
      const run = await client.$transaction(async (tx) => {
        const artifact = await tx.artifact.update({
          where: { id: input.artifactId },
          data: {
            storageState: input.storageState,
            stateReason: input.stateReason ?? null,
            stateDetails: input.stateDetails as any,
            verifiedAt: input.storageState === 'VERIFIED' ? new Date() : undefined,
            retainedAt: input.storageState === 'RETAINED' ? new Date() : undefined,
            deletedAt: input.storageState === 'DELETED' ? new Date() : undefined,
          } as any,
        });
        return await tx.benchmarkRun.findUniqueOrThrow({
          where: { id: artifact.benchmarkRunId },
          include: PRISMA_RUN_INCLUDE,
        });
      });
      return normalizeBundle(run, 'ENCODED');
    },
    async getQualityAnalysis(benchmarkRunId, metricModelId, analysisWorkerVersion) {
      const analysis = await client.qualityAnalysis.findUnique({
        where: {
          benchmarkRunId_metricModelId_analysisWorkerVersion: {
            benchmarkRunId,
            metricModelId,
            analysisWorkerVersion,
          },
        },
      });
      if (!analysis) return null;
      return {
        id: analysis.id,
        benchmarkRunId: analysis.benchmarkRunId,
        artifactId: analysis.artifactId,
        status: analysis.status as QualityAnalysisStatusValue,
        metricModelId: analysis.metricModelId,
        qualityContextId: analysis.qualityContextId,
        analysisWorkerVersion: analysis.analysisWorkerVersion,
        analysisProvenance: analysis.analysisProvenance,
        vmafMean: analysis.vmafMean,
        vmafMedian: analysis.vmafMedian,
        vmafP1: analysis.vmafP1,
        vmafP5: analysis.vmafP5,
        vmafMin: analysis.vmafMin,
        vmafMax: analysis.vmafMax,
        vmafStdDev: analysis.vmafStdDev,
        vmafHarmonicMean: analysis.vmafHarmonicMean,
        worstFrameIndex: analysis.worstFrameIndex,
        worstFrameTimestampMs: analysis.worstFrameTimestampMs,
        belowThresholdFractions: analysis.belowThresholdFractions,
        vmafDistribution: analysis.vmafDistribution,
        xpsnr: analysis.xpsnr,
        ssim: analysis.ssim,
        psnr: analysis.psnr,
        videoBitrateBps: analysis.videoBitrateBps,
        videoPayloadBytes: analysis.videoPayloadBytes,
        videoPacketCount: analysis.videoPacketCount,
        measuredDurationSeconds: analysis.measuredDurationSeconds,
        bitrateMethod: analysis.bitrateMethod,
        containerBitrateBps: analysis.containerBitrateBps,
        fileSizeBytes: analysis.fileSizeBytes,
        createdAt: analysis.createdAt,
        updatedAt: analysis.updatedAt,
      };
    },
    async saveAuthoritativeAnalysis(input) {
      const run = await client.$transaction(async (tx) => {
        const existingAnalysis = await tx.qualityAnalysis.findUnique({
          where: {
            benchmarkRunId_metricModelId_analysisWorkerVersion: {
              benchmarkRunId: input.benchmarkRunId,
              metricModelId: input.result.metricModelId,
              analysisWorkerVersion: input.result.analysisWorkerVersion,
            },
          },
        });
        if (!existingAnalysis) {
          await tx.qualityAnalysis.create({
            data: {
              benchmarkRunId: input.benchmarkRunId,
              artifactId: input.artifactId,
              status: input.result.analysisStatus,
              metricModelId: input.result.metricModelId,
              qualityContextId: input.result.qualityContextId,
              analysisWorkerVersion: input.result.analysisWorkerVersion,
              analysisProvenance: input.result.analysisProvenance as any,
              vmafMean: input.result.vmafMean,
              vmafMedian: input.result.vmafMedian,
              vmafP1: input.result.vmafP1,
              vmafP5: input.result.vmafP5,
              vmafMin: input.result.vmafMin,
              vmafMax: input.result.vmafMax,
              vmafStdDev: input.result.vmafStdDev,
              vmafHarmonicMean: input.result.vmafHarmonicMean,
              worstFrameIndex: input.result.worstFrameIndex,
              worstFrameTimestampMs: input.result.worstFrameTimestampMs,
              belowThresholdFractions: input.result.belowThresholdFractions as any,
              vmafDistribution: input.result.vmafDistribution as any,
              xpsnr: input.result.xpsnr,
              ssim: input.result.ssim,
              psnr: input.result.psnr,
              videoBitrateBps: input.result.videoBitrateBps,
              videoPayloadBytes: input.result.videoPayloadBytes,
              videoPacketCount: input.result.videoPacketCount,
              measuredDurationSeconds: input.result.measuredDurationSeconds,
              bitrateMethod: input.result.bitrateMethod,
              containerBitrateBps: input.result.containerBitrateBps,
              fileSizeBytes: input.result.fileSizeBytes,
            } as any,
          });
        }
        await tx.benchmarkRun.update({
          where: { id: input.benchmarkRunId },
          data: {
            status: input.result.runStatus,
            statusReason: input.result.runStatusReason,
            decidedAt: new Date(),
          },
        });
        await tx.artifact.update({
          where: { id: input.artifactId },
          data: {
            storageState: input.result.artifactState,
            stateReason: input.result.artifactStateReason ?? null,
            stateDetails: input.result.artifactStateDetails as any,
            verifiedAt: input.result.artifactState === 'VERIFIED' || input.result.artifactState === 'RETAINED' ? new Date() : undefined,
            retainedAt: input.result.artifactState === 'RETAINED' ? new Date() : undefined,
          } as any,
        });
        return await tx.benchmarkRun.findUniqueOrThrow({
          where: { id: input.benchmarkRunId },
          include: PRISMA_RUN_INCLUDE,
        });
      });
      return normalizeBundle(run, 'ENCODED');
    },
  };
}
