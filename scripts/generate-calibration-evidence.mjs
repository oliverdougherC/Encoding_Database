#!/usr/bin/env node

import crypto from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const serverRoot = path.join(repoRoot, 'server');

function parseArgs(argv) {
  const flags = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith('--')) throw new Error(`Unexpected argument ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${key}`);
    flags.set(key, value);
    index += 1;
  }
  for (const required of ['--benchmark-protocol-id', '--quality-model-id', '--calibration-version', '--output']) {
    if (!flags.get(required)) throw new Error(`${required} is required`);
  }
  return flags;
}

function jsonObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function machineSourceId(canonicalEnvironment) {
  const environment = jsonObject(canonicalEnvironment);
  const identity = {
    cpuModel: environment.cpuModel ?? null,
    cpuArchitecture: environment.cpuArchitecture ?? null,
    gpuModel: environment.gpuModel ?? null,
    osName: environment.osName ?? null,
    osVersion: environment.osVersion ?? null,
    physicalCoreCount: environment.physicalCoreCount ?? null,
    logicalThreadCount: environment.logicalThreadCount ?? null,
  };
  return `machine:${crypto.createHash('sha256').update(JSON.stringify(identity)).digest('hex')}`;
}

function hardwareFamily(implementation) {
  const value = implementation.toLowerCase();
  if (value.includes('videotoolbox')) return 'videotoolbox';
  if (value.includes('nvenc')) return 'nvenc';
  if (value.includes('qsv')) return 'qsv';
  if (value.includes('amf')) return 'amf';
  if (value.includes('vaapi')) return 'vaapi';
  return 'software';
}

function numeric(value, field, evidenceId) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Evidence ${evidenceId} is missing finite ${field}`);
  }
  return value;
}

const flags = parseArgs(process.argv.slice(2));
const outputPath = path.resolve(process.cwd(), flags.get('--output'));
const since = flags.get('--since') ? new Date(flags.get('--since')) : null;
if (since && Number.isNaN(since.getTime())) throw new Error('--since must be an ISO-8601 timestamp');

const [{ prisma }, calibration] = await Promise.all([
  import(path.join(serverRoot, 'dist', 'db.js')),
  import(path.join(serverRoot, 'dist', 'v7', 'calibration.js')),
]);

try {
  const runs = await prisma.benchmarkRun.findMany({
    where: {
      benchmarkProtocolId: flags.get('--benchmark-protocol-id'),
      ...(since ? { createdAt: { gte: since } } : {}),
      status: { in: ['ACCEPTED', 'SUSPECT'] },
      artifacts: {
        some: {
          role: 'ENCODED',
          storageState: { in: ['RETAINED', 'VERIFIED'] },
          sha256: { not: null },
        },
      },
      qualityAnalyses: {
        some: {
          metricModelId: flags.get('--quality-model-id'),
          status: { in: ['COMPLETE', 'SUSPECT'] },
        },
      },
    },
    include: {
      benchmarkProtocol: true,
      testClip: true,
      recipe: true,
      environment: true,
      artifacts: {
        where: { role: 'ENCODED', storageState: { in: ['RETAINED', 'VERIFIED'] }, sha256: { not: null } },
        orderBy: [{ updatedAt: 'desc' }, { id: 'desc' }],
      },
      qualityAnalyses: {
        where: { metricModelId: flags.get('--quality-model-id'), status: { in: ['COMPLETE', 'SUSPECT'] } },
        orderBy: [{ updatedAt: 'desc' }, { id: 'desc' }],
      },
    },
    orderBy: [{ workloadId: 'asc' }, { id: 'asc' }],
  });

  const timestamps = [];
  const corpus = runs.map((run) => {
    const artifact = run.artifacts[0];
    const analysis = run.qualityAnalyses[0];
    if (!artifact?.sha256 || !analysis) throw new Error(`Run ${run.id} lost required retained evidence during generation`);
    timestamps.push(analysis.updatedAt, artifact.updatedAt, run.updatedAt);
    const implementation = run.recipe.encoderImplementation;
    const evidenceId = analysis.id;
    const realTimeRatio = run.realTimeRatio ?? (
      run.encodeFps != null && run.sourceFps != null && run.sourceFps > 0 ? run.encodeFps / run.sourceFps : null
    );
    return {
      evidenceId,
      partition: 'CALIBRATION',
      benchmarkRunId: run.id,
      artifactId: artifact.id,
      artifactSha256: artifact.sha256,
      artifactStorageState: artifact.storageState,
      qualityAnalysisId: analysis.id,
      analysisWorkerVersion: analysis.analysisWorkerVersion,
      recipeFingerprint: run.recipe.fingerprint,
      environmentFingerprint: run.environment.fingerprint,
      machineSourceId: machineSourceId(run.environment.canonicalJson),
      workloadId: run.workloadId,
      contentClass: run.testClip.contentClass,
      encoderFamily: run.recipe.codecFamily,
      encoderImplementation: implementation,
      hardwareFamily: hardwareFamily(implementation),
      nativeRateControl: jsonObject(run.recipe.requestedRateControl),
      preset: run.recipe.preset ?? 'unspecified',
      runStatus: run.status,
      analysisStatus: analysis.status,
      vmafMean: numeric(analysis.vmafMean, 'vmafMean', evidenceId),
      vmafP5: numeric(analysis.vmafP5, 'vmafP5', evidenceId),
      xpsnr: numeric(analysis.xpsnr, 'xpsnr', evidenceId),
      videoBitrateBps: numeric(analysis.videoBitrateBps, 'videoBitrateBps', evidenceId),
      realTimeRatio: numeric(realTimeRatio, 'realTimeRatio', evidenceId),
    };
  }).sort((left, right) => left.workloadId.localeCompare(right.workloadId)
    || left.encoderImplementation.localeCompare(right.encoderImplementation)
    || left.videoBitrateBps - right.videoBitrateBps
    || left.evidenceId.localeCompare(right.evidenceId));

  if (!corpus.length) throw new Error('No retained authoritative calibration evidence matched the requested scope');
  const generatedAt = new Date(Math.max(...timestamps.map((value) => value.getTime()))).toISOString();
  const firstRun = runs[0];
  const document = {
    schemaVersion: calibration.CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    calibrationVersion: flags.get('--calibration-version'),
    status: 'DRAFT',
    benchmarkProtocolVersion: firstRun.benchmarkProtocol.protocolVersion,
    sourceSuiteVersion: firstRun.benchmarkProtocol.sourceSuiteVersion,
    qualityModelId: flags.get('--quality-model-id'),
    scoreFormulaVersion: '7.0',
    generatedAt,
    corpus,
    goldenDecisions: [],
    holdoutEvaluations: [],
    topResultReviews: [],
    metricSanityReviews: [],
    freeze: null,
    reviewHash: '',
    evidenceHash: '',
  };
  document.reviewHash = calibration.buildCalibrationReviewHash(document);
  document.evidenceHash = calibration.buildCalibrationEvidenceHash(document);
  const assessment = calibration.assessCalibrationEvidence(document);
  mkdirSync(path.dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(document, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({
    output: outputPath,
    evidenceHash: document.evidenceHash,
    coverage: assessment.coverage,
    blockingFindingCodes: [...new Set(assessment.errors.map((finding) => finding.code))].sort(),
  })}\n`);
} finally {
  await prisma.$disconnect().catch(() => {});
}
