#!/usr/bin/env node

import crypto from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { PrismaClient } from '@prisma/client';
import { pathToFileURL } from 'node:url';

export const E2E_EVIDENCE_VERSION = 'encodingdb-pl-v7-e2e/v1';

function fail(message) {
  throw new Error(message);
}

function sha256Json(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

function analysisIsAuthoritative(analysis) {
  const provenance = analysis?.analysisProvenance;
  return Boolean(
    provenance
    && typeof provenance === 'object'
    && provenance.pipelineVersion === 'encodingdb-artifact-pipeline/v1'
    && typeof provenance.contractVersion === 'string'
    && provenance.contractVersion.length > 0
    && typeof provenance.modelSha256 === 'string'
    && /^[0-9a-f]{64}$/.test(provenance.modelSha256)
    && typeof provenance.referencePath === 'string'
    && provenance.referencePath.length > 0
    && typeof analysis.analysisWorkerVersion === 'string'
    && analysis.analysisWorkerVersion.length > 0
  );
}

export function validateCertificationSnapshot(snapshot, expectedEncoders) {
  if (!snapshot || typeof snapshot !== 'object') fail('Certification snapshot is missing');
  if (!Array.isArray(expectedEncoders) || expectedEncoders.length !== 2) {
    fail('Certification requires exactly one software and one hardware encoder');
  }
  if (expectedEncoders[0] === expectedEncoders[1]) fail('Software and hardware encoders must be distinct');
  if (!Array.isArray(snapshot.runs) || snapshot.runs.length === 0) fail('No v7 benchmark runs were retained');

  const paths = expectedEncoders.map((encoderImplementation, index) => {
    const matching = snapshot.runs.filter((run) => run.recipe?.encoderImplementation === encoderImplementation);
    if (matching.length === 0) fail(`No v7 run was persisted for ${encoderImplementation}`);
    if (matching.length < 2) fail(`${encoderImplementation} did not retain the required repeated measurements`);
    for (const run of matching) {
      if (run.status !== 'ACCEPTED') fail(`${encoderImplementation} run ${run.id} is ${run.status}, not ACCEPTED`);
      const encoded = run.artifacts?.find((artifact) => artifact.role === 'ENCODED');
      if (!encoded) fail(`${encoderImplementation} run ${run.id} has no encoded artifact`);
      if (encoded.storageState !== 'RETAINED') {
        fail(`${encoderImplementation} artifact ${encoded.id} is ${encoded.storageState}, not RETAINED`);
      }
      if (!/^[0-9a-f]{64}$/.test(encoded.sha256 || '')) fail(`${encoderImplementation} artifact hash is invalid`);
      if (!(encoded.byteSize > 0)) fail(`${encoderImplementation} artifact is empty`);
      const analyses = run.qualityAnalyses || [];
      if (analyses.length === 0) fail(`${encoderImplementation} run ${run.id} has no server analysis`);
      for (const analysis of analyses) {
        if (analysis.status !== 'COMPLETE') fail(`${encoderImplementation} analysis ${analysis.id} is ${analysis.status}`);
        if (!analysisIsAuthoritative(analysis)) {
          fail(`${encoderImplementation} analysis ${analysis.id} lacks authoritative server provenance`);
        }
        if (!(analysis.vmafDistribution?.frameCount > 0)) {
          fail(`${encoderImplementation} analysis ${analysis.id} lacks the VMAF frame distribution`);
        }
        if (analysis.vmafMean == null || analysis.vmafP5 == null || analysis.videoBitrateBps == null) {
          fail(`${encoderImplementation} analysis ${analysis.id} lacks canonical scoring inputs`);
        }
      }
      if (!Array.isArray(run.derivedMembers) || run.derivedMembers.length === 0) {
        fail(`${encoderImplementation} run ${run.id} did not reach PL aggregation`);
      }
      if (!run.derivedMembers.some((member) => member.derivedResult?.acceptedRunCount >= 2)) {
        fail(`${encoderImplementation} run ${run.id} is not in a repeated-measurement PL aggregate`);
      }
    }
    return {
      kind: index === 0 ? 'software' : 'hardware',
      encoderImplementation,
      runIds: matching.map((run) => run.id),
      artifactSha256: matching.flatMap((run) => run.artifacts.map((artifact) => artifact.sha256)).filter(Boolean),
      analysisIds: matching.flatMap((run) => run.qualityAnalyses.map((analysis) => analysis.id)),
      derivedResultIds: [...new Set(matching.flatMap((run) => run.derivedMembers.map((member) => member.derivedResultId)))],
    };
  });

  const softwareEnvironmentIds = new Set(snapshot.runs
    .filter((run) => run.recipe?.encoderImplementation === expectedEncoders[0])
    .map((run) => run.environmentId));
  const hardwareRuns = snapshot.runs.filter((run) => run.recipe?.encoderImplementation === expectedEncoders[1]);
  if (hardwareRuns.every((run) => softwareEnvironmentIds.has(run.environmentId))) {
    fail('Hardware path did not produce a distinct deterministic environment identity');
  }
  const serverScopes = snapshot.serverAnalyticsScopes ?? [snapshot.serverAnalytics];
  const frontendScopes = snapshot.frontendAnalyticsScopes ?? [snapshot.frontendAnalytics];
  if (!snapshot.frontendPage?.ok || serverScopes.length === 0 || serverScopes.length !== frontendScopes.length
      || serverScopes.some((scope) => !scope?.ok) || frontendScopes.some((scope) => !scope?.ok)) {
    fail('The authoritative evidence did not reach both the analytics API and frontend surface');
  }
  for (let index = 0; index < serverScopes.length; index += 1) {
    if (serverScopes[index].sha256 !== frontendScopes[index].sha256) {
      fail('Frontend analytics proxy response differs from the authoritative server response');
    }
  }
  if (!(serverScopes.reduce((sum, scope) => sum + (scope.rowCount || 0), 0) > 0)) {
    fail('Analytics API returned no PL decision rows');
  }
  const surfacedEncoders = new Set(serverScopes.flatMap((scope) => scope.encoderNames || []));
  for (const encoder of expectedEncoders) {
    if (!surfacedEncoders.has(encoder)) {
      fail(`Analytics/frontend surface does not contain certified encoder ${encoder}`);
    }
  }
  return paths;
}

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith('--')) fail(`Unexpected argument ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) fail(`Missing value for ${key}`);
    args[key.slice(2)] = value;
    index += 1;
  }
  for (const required of ['since', 'software-encoder', 'hardware-encoder', 'server-url', 'frontend-url', 'output']) {
    if (!args[required]) fail(`--${required} is required`);
  }
  const since = new Date(args.since);
  if (Number.isNaN(since.getTime())) fail('--since must be an ISO-8601 timestamp');
  return { ...args, since };
}

async function fetchEvidence(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(20_000) });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* HTML is expected for the page probe. */ }
  return {
    ok: response.ok,
    status: response.status,
    contentType: response.headers.get('content-type'),
    sha256: crypto.createHash('sha256').update(text).digest('hex'),
    rowCount: Array.isArray(json?.rows) ? json.rows.length : null,
    encoderNames: Array.isArray(json?.rows)
      ? [...new Set(json.rows.map((row) => row?.encoderName).filter((value) => typeof value === 'string'))].sort()
      : [],
    recommendationRowId: json?.recommendation?.rowId ?? null,
    bodyBytes: Buffer.byteLength(text),
  };
}

async function main(argv) {
  const args = parseArgs(argv);
  const prisma = new PrismaClient();
  try {
    const runs = await prisma.benchmarkRun.findMany({
      where: {
        createdAt: { gte: args.since },
        recipe: { encoderImplementation: { in: [args['software-encoder'], args['hardware-encoder']] } },
      },
      include: {
        recipe: true,
        environment: true,
        benchmarkProtocol: true,
        testClip: true,
        artifacts: true,
        qualityAnalyses: true,
        derivedMembers: { include: { derivedResult: true } },
      },
      orderBy: { createdAt: 'asc' },
    });
    const environmentIds = [...new Set(runs.map((run) => run.environmentId))];
    const scopedPairs = await Promise.all(environmentIds.map(async (environmentId) => {
      const query = `?fitMode=balanced&minSamples=1&environmentId=${encodeURIComponent(environmentId)}`;
      return await Promise.all([
        fetchEvidence(`${args['server-url'].replace(/\/$/, '')}/analytics/leaderboards${query}`),
        fetchEvidence(`${args['frontend-url'].replace(/\/$/, '')}/api/analytics/leaderboards${query}`),
      ]);
    }));
    const frontendPage = await fetchEvidence(`${args['frontend-url'].replace(/\/$/, '')}/leaderboards`);
    const serverAnalyticsScopes = scopedPairs.map(([server]) => server);
    const frontendAnalyticsScopes = scopedPairs.map(([, frontend]) => frontend);
    const snapshot = {
      evidenceVersion: E2E_EVIDENCE_VERSION,
      capturedAt: new Date().toISOString(),
      since: args.since.toISOString(),
      serverAnalyticsScopes,
      frontendAnalyticsScopes,
      frontendPage,
      runs,
    };
    const paths = validateCertificationSnapshot(snapshot, [args['software-encoder'], args['hardware-encoder']]);
    const evidence = {
      ...snapshot,
      certification: {
        passed: true,
        paths,
        snapshotSha256: sha256Json(snapshot),
      },
    };
    await writeFile(args.output, `${JSON.stringify(evidence, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    process.stdout.write(`${JSON.stringify({ passed: true, output: args.output, paths })}\n`);
  } finally {
    await prisma.$disconnect();
  }
}

const invokedAsScript = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedAsScript) {
  main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`v7 E2E certification failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
