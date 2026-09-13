#!/usr/bin/env node

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const serverRoot = path.join(repoRoot, 'server');

function parseArgs(argv) {
  const flags = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) throw new Error(`Unexpected argument ${token}`);
    const next = argv[index + 1];
    if (next && !next.startsWith('--')) {
      flags.set(token, next);
      index += 1;
    } else {
      flags.set(token, 'true');
    }
  }
  for (const required of ['--benchmark-protocol-id', '--reference-context']) {
    if (!flags.get(required)) throw new Error(`${required} is required`);
  }
  if (!flags.has('--apply') && (flags.has('--promoted-context-output') || flags.has('--env-output'))) {
    throw new Error('--promoted-context-output and --env-output require --apply');
  }
  return flags;
}

function sortedWorkloadBitrates(context) {
  return Object.fromEntries(
    [...context.workloads]
      .map((workload) => [workload.workloadId, workload.workloadReferenceBitrateBps])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

export function buildProductionEnvBindings(context, referenceContextPath) {
  if (context.activation?.stage !== 'PRODUCTION' || context.activation?.productionActivationAllowed !== true) {
    throw new Error(`Reference context ${context.contextVersion} is not production-activated`);
  }
  return {
    PL_V7_REFERENCE_CONTEXT_VERSION: context.contextVersion,
    PL_V7_REFERENCE_BITRATES_JSON: JSON.stringify(sortedWorkloadBitrates(context)),
    PL_V7_REFERENCE_CONTEXT_PATH: referenceContextPath,
    ALLOW_TEST_ONLY_REFERENCE_CONTEXTS: '0',
  };
}

export function formatEnvBindings(bindings) {
  return Object.entries(bindings)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n')
    .concat('\n');
}

function latestAnalysesByRun(rows) {
  const latest = new Map();
  for (const row of rows) {
    if (!latest.has(row.benchmarkRunId)) latest.set(row.benchmarkRunId, row);
  }
  return [...latest.values()];
}

async function loadModules() {
  const [dbModule, referenceContextModule, calibrationModule, aggregationModule] = await Promise.all([
    import(path.join(serverRoot, 'dist', 'db.js')),
    import(path.join(serverRoot, 'dist', 'v7', 'referenceContext.js')),
    import(path.join(serverRoot, 'dist', 'v7', 'calibration.js')),
    import(path.join(serverRoot, 'dist', 'v7', 'aggregation.js')),
  ]);
  return { ...dbModule, ...referenceContextModule, ...calibrationModule, ...aggregationModule };
}

export async function loadProductionActivationPlan(options) {
  const modules = options.modules ?? await loadModules();
  const {
    parseReferenceContext,
    parseCalibrationEvidence,
    activateReferenceContextForProduction,
  } = modules;

  const referenceContextPath = path.resolve(process.cwd(), options.referenceContextPath);
  const context = parseReferenceContext(readFileSync(referenceContextPath, 'utf8'));
  const calibrationPath = options.calibrationEvidencePath
    ? path.resolve(process.cwd(), options.calibrationEvidencePath)
    : null;

  let promotedContext = context;
  let calibration = null;

  if (calibrationPath) {
    calibration = parseCalibrationEvidence(readFileSync(calibrationPath, 'utf8'));
  }

  if (context.activation?.stage !== 'PRODUCTION') {
    if (!calibration) {
      throw new Error('A complete --calibration-evidence document is required to activate a provisional reference context');
    }
    promotedContext = activateReferenceContextForProduction(context, calibration);
  } else if (calibration) {
    if (context.activation.calibrationVersion !== calibration.calibrationVersion
      || context.activation.calibrationReviewHash !== calibration.reviewHash) {
      throw new Error('Production reference context does not match the supplied calibration version/review hash');
    }
  }

  if (promotedContext.provenance?.sourceMode !== 'retained-benchmark-evidence') {
    throw new Error('Only retained authoritative evidence can be activated for production');
  }

  return {
    modules,
    calibration,
    promotedContext,
    referenceContextPath,
  };
}

function buildUnavailableMetricInterval() {
  return {
    lower: null,
    upper: null,
    width: null,
    confidenceLevel: 0.95,
    method: 'unavailable',
  };
}

function buildUnavailableDispersion() {
  return {
    sampleCount: 0,
    median: null,
    minimum: null,
    maximum: null,
    q1: null,
    q3: null,
    iqr: null,
  };
}

function uniqueMembers(rows) {
  return [...new Map(rows.map((row) => [row.qualityAnalysisId, row])).values()]
    .sort((left, right) => left.qualityAnalysisId.localeCompare(right.qualityAnalysisId));
}

function buildDerivedResultPersistenceShape(result, benchmarkProtocolId, scoreContextId) {
  const evidenceSummary = {
    sourceRecordKind: 'reference-context-recompute',
    aggregation: result.kind === 'GENERAL' ? 'equal-class-geometric-mean' : 'workload-mean',
    contributingWorkloadIds: [...result.contributingWorkloadIds],
    memberBenchmarkRunIds: [...result.memberBenchmarkRunIds],
    selectedAnalysisIds: [...result.recomputationSpec.selectedAnalysisIds],
    includedStatuses: [...result.recomputationSpec.includedStatuses],
    coverageComplete: result.kind === 'GENERAL' ? result.contributingWorkloadIds.length > 0 : true,
  };
  const confidenceIntervals = {
    plTotal: buildUnavailableMetricInterval(),
    plQuality: buildUnavailableMetricInterval(),
    plBitrate: buildUnavailableMetricInterval(),
    plSpeed: buildUnavailableMetricInterval(),
    vmafMean: buildUnavailableMetricInterval(),
    vmafP5: buildUnavailableMetricInterval(),
    encodeFps: buildUnavailableMetricInterval(),
    realTimeRatio: buildUnavailableMetricInterval(),
    videoBitrateBps: buildUnavailableMetricInterval(),
    fileSizeBytes: buildUnavailableMetricInterval(),
  };
  const dispersion = {
    plTotal: buildUnavailableDispersion(),
    plQuality: buildUnavailableDispersion(),
    plBitrate: buildUnavailableDispersion(),
    plSpeed: buildUnavailableDispersion(),
    vmafMean: buildUnavailableDispersion(),
    vmafP5: buildUnavailableDispersion(),
    encodeFps: buildUnavailableDispersion(),
    realTimeRatio: buildUnavailableDispersion(),
    videoBitrateBps: buildUnavailableDispersion(),
    fileSizeBytes: buildUnavailableDispersion(),
  };
  return {
    kind: result.kind,
    scopeKey: result.scopeKey,
    benchmarkProtocolId,
    workloadId: result.workloadId,
    testClipId: null,
    recipeId: result.recipeId,
    environmentId: result.environmentId,
    scoreContextId,
    aggregatorVersion: result.recomputationSpec.aggregatorVersion,
    acceptedRunCount: result.acceptedRunCount,
    suspectRunCount: result.suspectRunCount,
    rejectedRunCount: result.rejectedRunCount,
    invalidRunCount: 0,
    repetitionCount: result.repetitionCount,
    centerEncodeFps: result.centerEncodeFps,
    centerRealTimeRatio: result.centerRealTimeRatio,
    centerVideoBitrateBps: result.centerVideoBitrateBps,
    centerFileSizeBytes: result.centerFileSizeBytes,
    centerVmafMean: result.centerVmafMean,
    centerVmafP5: result.centerVmafP5,
    plQuality: result.plQuality,
    plBitrate: result.plBitrate,
    plSpeed: result.plSpeed,
    plTotal: result.plTotal,
    confidenceLower: null,
    confidenceUpper: null,
    evidenceTier: result.evidenceTier,
    evidenceSummary,
    confidenceIntervals,
    dispersion,
    recomputationSpec: result.recomputationSpec,
  };
}

export function buildActivationPersistencePayloads({
  benchmarkProtocolId,
  evidence,
  recomputed,
  scoreContexts,
}) {
  const scoreContextIdByWorkload = new Map(scoreContexts.map((record) => [record.workloadId, record.id]));
  const evidenceByRunId = new Map(evidence.map((row) => [row.benchmarkRunId, row]));
  const evidenceByAnalysisId = new Map(
    evidence
      .filter((row) => typeof row.qualityAnalysisId === 'string' && row.qualityAnalysisId.length > 0)
      .map((row) => [row.qualityAnalysisId, row]),
  );

  return recomputed.derivedResults.map((result) => {
    const scoreContextId = scoreContextIdByWorkload.get(result.workloadId);
    if (!scoreContextId) {
      throw new Error(`Missing persisted score context for workload ${result.workloadId}`);
    }

    const membersFromSelectedAnalyses = result.recomputationSpec.selectedAnalysisIds
      .map((analysisId) => evidenceByAnalysisId.get(analysisId))
      .filter((row) => row != null)
      .map((row) => ({
        benchmarkRunId: row.benchmarkRunId,
        qualityAnalysisId: row.qualityAnalysisId,
      }));

    const members = membersFromSelectedAnalyses.length > 0
      ? uniqueMembers(membersFromSelectedAnalyses)
      : uniqueMembers(result.memberBenchmarkRunIds.map((benchmarkRunId) => {
          const row = evidenceByRunId.get(benchmarkRunId);
          if (!row?.qualityAnalysisId) {
            throw new Error(`Missing retained analysis identity for benchmark run ${benchmarkRunId}`);
          }
          return {
            benchmarkRunId: row.benchmarkRunId,
            qualityAnalysisId: row.qualityAnalysisId,
          };
        }));

    return {
      kind: result.kind,
      workloadId: result.workloadId,
      scopeKey: result.scopeKey,
      derivedResult: buildDerivedResultPersistenceShape(result, benchmarkProtocolId, scoreContextId),
      members,
    };
  });
}

export async function persistActivationState(client, {
  modules,
  benchmarkProtocolId,
  promotedContext,
  evidence,
  recomputed,
}) {
  const scoreContexts = await modules.persistScoreContextsFromReferenceContext(
    client,
    promotedContext,
    benchmarkProtocolId,
  );
  const payloads = buildActivationPersistencePayloads({
    benchmarkProtocolId,
    evidence,
    recomputed,
    scoreContexts,
  });
  const derivedResults = [];
  for (const payload of payloads) {
    const id = await modules.persistDerivedResultRecord(client, payload.derivedResult, payload.members);
    derivedResults.push({
      id,
      kind: payload.kind,
      workloadId: payload.workloadId,
      memberCount: payload.members.length,
    });
  }
  return {
    scoreContexts,
    derivedResults,
  };
}

async function loadRecomputeInputs(prisma, benchmarkProtocolId, promotedContext) {
  const analyses = await prisma.qualityAnalysis.findMany({
    where: {
      metricModelId: promotedContext.qualityModelId,
      status: { in: ['COMPLETE', 'SUSPECT', 'REJECTED'] },
      benchmarkRun: {
        benchmarkProtocolId,
        status: { in: ['ACCEPTED', 'SUSPECT', 'REJECTED'] },
      },
    },
    include: {
      benchmarkRun: {
        include: {
          benchmarkProtocol: true,
          testClip: true,
          recipe: true,
          environment: true,
        },
      },
    },
    orderBy: [{ updatedAt: 'desc' }, { id: 'desc' }],
  });

  return latestAnalysesByRun(analyses).map((analysis) => ({
    qualityAnalysisId: analysis.id,
    analysisWorkerVersion: analysis.analysisWorkerVersion,
    benchmarkRunId: analysis.benchmarkRunId,
    benchmarkProtocolVersion: analysis.benchmarkRun.benchmarkProtocol.protocolVersion,
    sourceSuiteVersion: analysis.benchmarkRun.benchmarkProtocol.sourceSuiteVersion,
    workloadId: analysis.benchmarkRun.workloadId,
    testClipId: analysis.benchmarkRun.testClipId,
    contentClass: analysis.benchmarkRun.testClip.contentClass,
    recipeId: analysis.benchmarkRun.recipeId,
    recipeFingerprint: analysis.benchmarkRun.recipe.fingerprint,
    environmentId: analysis.benchmarkRun.environmentId,
    environmentFingerprint: analysis.benchmarkRun.environment.fingerprint,
    qualityModelId: analysis.metricModelId,
    benchmarkRunStatus: analysis.benchmarkRun.status,
    qualityAnalysisStatus: analysis.status,
    encodeFps: analysis.benchmarkRun.encodeFps,
    sourceFps: analysis.benchmarkRun.sourceFps,
    realTimeRatio: analysis.benchmarkRun.realTimeRatio,
    videoBitrateBps: analysis.videoBitrateBps,
    fileSizeBytes: analysis.fileSizeBytes,
    vmafMean: analysis.vmafMean,
    vmafP5: analysis.vmafP5,
  }));
}

export async function runProductionActivation(options) {
  const plan = options.plan ?? await loadProductionActivationPlan(options);
  const {
    modules,
    calibration,
    promotedContext,
    referenceContextPath,
  } = plan;
  const {
    prisma,
    recomputeReferenceScores,
  } = modules;

  const envBindings = buildProductionEnvBindings(
    promotedContext,
    options.promotedContextOutputPath
      ? path.resolve(process.cwd(), options.promotedContextOutputPath)
      : referenceContextPath,
  );

  try {
    const evidence = await loadRecomputeInputs(prisma, options.benchmarkProtocolId, promotedContext);
    const recomputed = recomputeReferenceScores(evidence, promotedContext);
    const persisted = options.apply === true
      ? await prisma.$transaction((tx) => persistActivationState(tx, {
          modules,
          benchmarkProtocolId: options.benchmarkProtocolId,
          promotedContext,
          evidence,
          recomputed,
        }))
      : { scoreContexts: [], derivedResults: [] };

    if (options.apply === true && options.promotedContextOutputPath) {
      const outputPath = path.resolve(process.cwd(), options.promotedContextOutputPath);
      mkdirSync(path.dirname(outputPath), { recursive: true });
      writeFileSync(outputPath, `${JSON.stringify(promotedContext, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    }
    if (options.apply === true && options.envOutputPath) {
      const outputPath = path.resolve(process.cwd(), options.envOutputPath);
      mkdirSync(path.dirname(outputPath), { recursive: true });
      writeFileSync(outputPath, formatEnvBindings(envBindings), { encoding: 'utf8', flag: 'wx' });
    }

    return {
      mode: options.apply === true ? 'apply' : 'dry-run',
      benchmarkProtocolId: options.benchmarkProtocolId,
      contextVersion: promotedContext.contextVersion,
      contextHash: promotedContext.hash,
      calibrationVersion: promotedContext.activation.calibrationVersion ?? calibration?.calibrationVersion ?? null,
      calibrationReviewHash: promotedContext.activation.calibrationReviewHash ?? calibration?.reviewHash ?? null,
      scoreContextSeedCount: promotedContext.workloads.length + 1,
      persistedScoreContextCount: persisted.scoreContexts.length,
      persistedDerivedResultCount: persisted.derivedResults.length,
      retainedLatestAnalysisCount: evidence.length,
      recomputedDerivedResultCount: recomputed.derivedResults.length,
      recomputedGeneralResultCount: recomputed.derivedResults.filter((result) => result.kind === 'GENERAL').length,
      envBindings,
    };
  } finally {
    if (typeof prisma?.$disconnect === 'function') {
      await prisma.$disconnect().catch(() => {});
    }
  }
}

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const summary = await runProductionActivation({
    apply: flags.has('--apply'),
    benchmarkProtocolId: flags.get('--benchmark-protocol-id'),
    referenceContextPath: flags.get('--reference-context'),
    calibrationEvidencePath: flags.get('--calibration-evidence') ?? null,
    promotedContextOutputPath: flags.get('--promoted-context-output') ?? null,
    envOutputPath: flags.get('--env-output') ?? null,
  });
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`activate-pl-v7-production failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
