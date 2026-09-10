#!/usr/bin/env node
import crypto from 'node:crypto';
import path from 'node:path';
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { PrismaClient } from '@prisma/client';

const hash = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
// Extracted from the assignment's starting commit, not from the final manifest.
export const LEGACY_SUITE_REFERENCE = Object.freeze({
  commit: '830e30375ec13d02ea00289c531e0e05e0d91b72',
  manifestPath: 'client/resources/test_suite_v1/manifest.json',
  manifestSha256: 'e6e6ac59af667bb027e621270618371a2ac8629a2e7ff678d85e7a607eb5013a',
  suiteId: 'encodingdb-test-suite', suiteVersion: 'encodingdb-test-suite-v1',
  clipKey: 'sports-action-960x540-24p',
  sha256: '8dff09e5120e42c478ef02501ff75d7ae7e94a509b651a2a9506c03ff512876a',
});
const requireValue = (ok, message) => { if (!ok) throw new Error(message); };
export function validateBetaSnapshot(snapshot, manifest) {
  requireValue(manifest.clips?.length === 7 && new Set(manifest.clips.map(c => c.contentClass)).size === 7, 'Seven distinct canonical classes required');
  requireValue(snapshot.plConfiguration?.testOnlyEnabled === false && snapshot.plConfiguration?.referenceBitrates === '' && snapshot.plConfiguration?.referenceVersion === '' && snapshot.plConfiguration?.referencePath === '', 'PL must be explicitly unavailable');
  const legacy = snapshot.legacyRejection;
  requireValue(legacy?.status === 404 && legacy?.response?.error === 'Canonical suite clip could not be resolved by clipKey or sha256' && legacy?.acceptedOldRunCount === 0 && legacy?.createdPayloadCount === 0 && legacy?.source?.commit === LEGACY_SUITE_REFERENCE.commit && legacy?.request?.testClip?.sha256 === LEGACY_SUITE_REFERENCE.sha256 && legacy?.request?.testClip?.clipKey === LEGACY_SUITE_REFERENCE.clipKey, 'Legacy submission lacks meaningful canonical rejection');
  const fault = snapshot.uploadInterruptionEvidence;
  const interrupted = fault?.uploadAttempts?.find(a => a.injected && a.status === 503);
  requireValue(fault?.injectedFailures === 1 && interrupted && snapshot.runs.some(r => r.id === interrupted.benchmarkRunId && r.status === 'ACCEPTED'), 'Interrupted upload did not recover the same run');
  requireValue(snapshot.reanalysis?.status === 202 && snapshot.reanalysis?.idempotent === true, 'Retained reanalysis/idempotence failed');
  for (const clip of manifest.clips) {
    requireValue(clip.acquisition.kind !== 'generated' && clip.source.reviewed && clip.source.redistributionApproved, `Nonfinal canonical source ${clip.id}`);
    const runs = snapshot.runs.filter(r => r.workloadId === clip.id);
    requireValue(runs.length >= 2 && new Set(runs.map(r => r.repetitionIndex)).size >= 2, `Repeated measurements missing: ${clip.id}`);
    for (const run of runs) {
      requireValue(run.status === 'ACCEPTED' && run.testClip.sha256 === clip.sha256 && run.inputHash === clip.sha256 && run.testClip.suiteVersion === manifest.suiteVersion && run.testClip.clipKey === clip.id, `Canonical identity/status mismatch: ${run.id}`);
      requireValue(run.derivedMembers.length === 0, `Unexpected PL aggregation: ${run.id}`);
      const artifact = run.artifacts.find(a => a.role === 'ENCODED');
      requireValue(artifact?.storageState === 'RETAINED' && artifact.diskVerification?.sha256 === artifact.sha256 && artifact.diskVerification?.byteSize === artifact.byteSize && artifact.byteSize > 0, `Retained bytes missing or corrupt: ${run.id}`);
      requireValue(run.qualityAnalyses.length > 0, `Analysis missing: ${run.id}`);
      for (const analysis of run.qualityAnalyses) {
        const provenance = analysis.analysisProvenance;
        requireValue(analysis.status === 'COMPLETE' && analysis.artifactId === artifact.id && provenance?.pipelineVersion === 'encodingdb-artifact-pipeline/v1' && /^[a-f0-9]{64}$/.test(provenance.modelSha256 || '') && provenance.contractVersion && provenance.referencePath && analysis.analysisWorkerVersion, `Authoritative analysis missing: ${run.id}`);
        requireValue(analysis.vmafDistribution?.frameCount === clip.media.frameCount && Number.isFinite(analysis.vmafMean) && Number.isFinite(analysis.vmafP5) && analysis.videoBitrateBps > 0, `Analysis distribution incomplete: ${run.id}`);
      }
      for (const [label, rows] of [['server', snapshot.serverRows], ['frontend', snapshot.frontendRows]]) {
        requireValue(rows.some(row => row.workloadId === clip.id && row.recipe?.id === run.recipeId && row.environment?.id === run.environmentId && row.versions?.benchmarkProtocolId === run.benchmarkProtocolId && row.sampleCounts?.accepted >= 2 && row.pl?.total === null && row.pl?.components === null && row.status?.scoring === 'UNSCORED_NO_PUBLIC_DERIVED_RESULT'), `${label} lacks matching unscored corpus: ${run.id}`);
      }
    }
  }
  const reanalyzed = snapshot.runs.find(r => r.id === snapshot.reanalysis.benchmarkRunId);
  requireValue(reanalyzed?.qualityAnalyses.some(a => a.id === snapshot.reanalysis.qualityAnalysisId && a.status === 'COMPLETE'), 'Reanalysis not retained');
  requireValue(snapshot.frontendPage?.ok && JSON.stringify(snapshot.serverRows) === JSON.stringify(snapshot.frontendRows), 'Frontend corpus differs from server');
  return true;
}

async function main(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    requireValue(argv[i]?.startsWith('--') && argv[i + 1], 'Arguments require --name value');
    args[argv[i].slice(2)] = argv[i + 1];
  }
  for (const key of ['since', 'server-url', 'frontend-url', 'manifest', 'fault-evidence', 'storage-root', 'output']) requireValue(args[key], `--${key} required`);
  const manifestBytes = await readFile(args.manifest);
  const manifest = JSON.parse(manifestBytes);
  const plConfiguration = {
    testOnlyEnabled: process.env.ALLOW_TEST_ONLY_REFERENCE_CONTEXTS === '1',
    referenceBitrates: process.env.PL_V7_REFERENCE_BITRATES_JSON || '',
    referenceVersion: process.env.PL_V7_REFERENCE_CONTEXT_VERSION || '',
    referencePath: process.env.PL_V7_REFERENCE_CONTEXT_PATH || '',
  };
  const prisma = new PrismaClient();
  const include = { benchmarkProtocol: true, environment: true, testClip: true, recipe: true, artifacts: true, qualityAnalyses: true, derivedMembers: true };
  try {
    const query = { where: { createdAt: { gte: new Date(args.since) }, workloadId: { in: manifest.clips.map(c => c.id) } }, include, orderBy: { createdAt: 'asc' } };
    async function waitForAnalyses() {
      const deadline = Date.now() + Number(process.env.BETA_ANALYSIS_TIMEOUT_MS || 900000);
      while (true) {
        const current = await prisma.benchmarkRun.findMany(query);
        if (current.length >= 14 && current.every(r => r.qualityAnalyses.length && r.qualityAnalyses.every(a => a.status === 'COMPLETE'))) return current;
        requireValue(!current.some(r => r.qualityAnalyses.some(a => ['FAILED', 'REJECTED', 'INVALID'].includes(a.status))), 'Authoritative analysis failed');
        requireValue(Date.now() < deadline, 'Timed out awaiting complete authoritative analyses');
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    }
    let runs = await waitForAnalyses();
    const first = runs.find(r => r.qualityAnalyses.some(a => a.status === 'COMPLETE'));
    requireValue(first, 'No completed analysis available');
    const legacyCampaignId = `beta-rejected-legacy-${crypto.randomUUID()}`;
    const legacyPayloadHash = hash(legacyCampaignId);
    const encoded = first.artifacts.find(a => a.role === 'ENCODED');
    const legacyRequest = {
      benchmarkProtocol: Object.fromEntries(['protocolVersion', 'sourceSuiteVersion', 'minimumClientVersion', 'canonicalRecipeRules', 'canonicalOutputRules', 'metricWorkerVersion'].map(key => [key, first.benchmarkProtocol[key]])),
      testClip: { suiteId: LEGACY_SUITE_REFERENCE.suiteId, suiteVersion: LEGACY_SUITE_REFERENCE.suiteVersion, clipKey: LEGACY_SUITE_REFERENCE.clipKey, sha256: LEGACY_SUITE_REFERENCE.sha256, workloadId: LEGACY_SUITE_REFERENCE.clipKey },
      recipe: { fingerprint: first.recipe.fingerprint, canonicalJson: first.recipe.canonicalJson, identity: first.recipe.canonicalJson },
      environment: { fingerprint: first.environment.fingerprint, canonicalJson: first.environment.canonicalJson, identity: first.environment.canonicalJson },
      payloadHash: legacyPayloadHash, inputHash: LEGACY_SUITE_REFERENCE.sha256,
      workloadId: LEGACY_SUITE_REFERENCE.clipKey, campaignId: legacyCampaignId,
      repetitionGroupId: legacyCampaignId, repetitionIndex: 0,
      encodeWallTimeMs: first.encodeWallTimeMs, encodeFps: first.encodeFps,
      sourceFps: 24, sourceFrameCount: 72, encodedFrameCount: first.encodedFrameCount,
      artifact: { role: 'ENCODED', sha256: encoded.sha256, byteSize: encoded.byteSize, mediaContainer: encoded.mediaContainer },
    };
    const legacyResponse = await fetch(`${args['server-url']}/v7/benchmark-runs`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(legacyRequest), signal: AbortSignal.timeout(20000) });
    const legacyRejection = {
      source: LEGACY_SUITE_REFERENCE, request: legacyRequest, status: legacyResponse.status,
      response: await legacyResponse.json(),
      acceptedOldRunCount: await prisma.benchmarkRun.count({ where: { createdAt: { gte: new Date(args.since) }, status: 'ACCEPTED', OR: [{ workloadId: LEGACY_SUITE_REFERENCE.clipKey }, { inputHash: LEGACY_SUITE_REFERENCE.sha256 }] } }),
      createdPayloadCount: await prisma.benchmarkRun.count({ where: { payloadHash: legacyPayloadHash } }),
    };
    const prior = first.qualityAnalyses.find(a => a.status === 'COMPLETE');
    const request = { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ analysisWorkerVersion: `${prior.analysisWorkerVersion}-beta-reanalysis`, metricModelId: prior.metricModelId }), signal: AbortSignal.timeout(180000) };
    const url = `${args['server-url']}/v7/benchmark-runs/${first.id}/artifacts/ENCODED/reanalyze`;
    const response = await fetch(url, request);
    const body = await response.json();
    const newAnalysis = body.analyses?.find(a => a.analysisWorkerVersion.endsWith('-beta-reanalysis'));
    requireValue(response.status === 202 && newAnalysis?.id && newAnalysis.id !== prior.id, 'Reanalysis was not queued with a new identity');
    await waitForAnalyses();
    const retry = await fetch(url, { ...request, signal: AbortSignal.timeout(180000) });
    const retryBody = await retry.json();
    const reanalysis = { status: response.status, benchmarkRunId: first.id, qualityAnalysisId: newAnalysis?.id, idempotent: Boolean(newAnalysis?.id) && retry.status === 202 && JSON.stringify((retryBody.analyses || []).map(a => a.id).sort()) === JSON.stringify((body.analyses || []).map(a => a.id).sort()) };
    runs = await waitForAnalyses();
    for (const run of runs) for (const artifact of run.artifacts.filter(a => a.role === 'ENCODED')) {
      requireValue(artifact.storageKey, `No retained storage key: ${artifact.id}`);
      const file = path.resolve(args['storage-root'], artifact.storageKey);
      requireValue(file.startsWith(`${path.resolve(args['storage-root'])}${path.sep}`), 'Storage key escapes root');
      const bytes = await readFile(file);
      artifact.diskVerification = { path: file, sha256: hash(bytes), byteSize: bytes.length };
    }
    async function rows(base, route) {
      const all = [];
      for (let skip = 0; ; skip += 100) {
        const response = await fetch(`${base}${route}?limit=100&skip=${skip}&sort=workloadId&dir=asc`, { signal: AbortSignal.timeout(20000) });
        requireValue(response.ok, `${route} returned ${response.status}`);
        const page = await response.json();
        requireValue(Array.isArray(page), `${route} did not return corpus rows`);
        all.push(...page);
        if (page.length < 100) return all;
      }
    }
    const [serverRows, frontendRows, page] = await Promise.all([rows(args['server-url'], '/corpus'), rows(args['frontend-url'], '/api/corpus'), fetch(`${args['frontend-url']}/`)]);
    const snapshot = { evidenceVersion: 'encodingdb-unscored-beta/v1', capturedAt: new Date().toISOString(), manifestSha256: hash(manifestBytes), plConfiguration, legacyRejection, runs, reanalysis, uploadInterruptionEvidence: JSON.parse(await readFile(args['fault-evidence'], 'utf8')), serverRows, frontendRows, frontendPage: { ok: page.ok, status: page.status } };
    validateBetaSnapshot(snapshot, manifest);
    await writeFile(args.output, JSON.stringify({ ...snapshot, passed: true }, null, 2) + '\n', { flag: 'wx' });
    console.log(`Unscored beta certification passed: ${args.output}`);
  } finally { await prisma.$disconnect(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main(process.argv.slice(2)).catch(e => { console.error(e); process.exitCode = 1; });
