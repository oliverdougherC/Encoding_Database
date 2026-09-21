#!/usr/bin/env node
import { PrismaClient } from '../server/node_modules/@prisma/client/default.js';
import {
  SERVER_CANONICAL_PROTOCOL_VERSION, SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
  SERVER_CANONICAL_RECIPE_RULES, SERVER_CANONICAL_OUTPUT_RULES, DEFAULT_ANALYZER_VERSION,
} from '../server/dist/v7/artifacts.js';
import { SUITE_V1_VERSION, loadAuthoritativeSuiteManifest } from '../server/dist/v7/suite.js';
import { canonicalJsonString } from '../server/dist/v7/persistence.js';

const args = process.argv.slice(2);
const apply = args.includes('--apply');
const expectedIndex = args.indexOf('--expected-active-id');
const expectedActiveId = expectedIndex >= 0 ? args[expectedIndex + 1] : null;
if (args.some((arg, index) => arg !== '--apply' && arg !== '--expected-active-id' && !(expectedIndex >= 0 && index === expectedIndex + 1))) {
  throw new Error('Usage: activate-collection-protocol.mjs [--apply --expected-active-id ID|none]');
}
if (apply && !expectedActiveId) throw new Error('--apply requires an explicit --expected-active-id ID or none');
const manifest = loadAuthoritativeSuiteManifest();
if (manifest.clips.length !== 7) throw new Error('Expected the frozen seven-clip suite');
const desired = {
  protocolVersion: SERVER_CANONICAL_PROTOCOL_VERSION,
  sourceSuiteVersion: SUITE_V1_VERSION,
  minimumClientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION,
  canonicalRecipeRules: SERVER_CANONICAL_RECIPE_RULES,
  canonicalOutputRules: SERVER_CANONICAL_OUTPUT_RULES,
  metricWorkerVersion: DEFAULT_ANALYZER_VERSION,
};
if (desired.protocolVersion !== '7.1' || desired.minimumClientVersion !== 'client/0.3.0') throw new Error('Build the corrected server before activating collection');
const db = new PrismaClient();
try {
  const receipt = await db.$transaction(async tx => {
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(714555)`;
    const active = await tx.benchmarkProtocol.findMany({ where: { state: 'ACTIVE' }, orderBy: { id: 'asc' } });
    const compatible = await tx.benchmarkProtocol.findUnique({ where: { protocolVersion_sourceSuiteVersion_metricWorkerVersion: {
      protocolVersion: desired.protocolVersion, sourceSuiteVersion: desired.sourceSuiteVersion, metricWorkerVersion: desired.metricWorkerVersion,
    } } });
    if (compatible && Object.entries(desired).some(([key, value]) => canonicalJsonString(compatible[key]) !== canonicalJsonString(value))) {
      throw new Error('Existing protocol has incompatible immutable rules');
    }
    const alreadyActive = active.length === 1 && active[0].id === compatible?.id;
    if (apply && !alreadyActive && (active.length > 1 || (active[0]?.id ?? 'none') !== expectedActiveId)) {
      throw new Error('Active protocol changed; inspect dry-run before retrying');
    }
    const inventory = await tx.benchmarkRun.groupBy({ by: ['benchmarkProtocolId', 'encodeTimerBoundary', 'status'], _count: true });
    let protocol = compatible;
    if (apply && !alreadyActive) {
      await tx.benchmarkProtocol.updateMany({ where: { state: 'ACTIVE' }, data: { state: 'RETIRED', retiredAt: new Date() } });
      protocol = compatible
        ? await tx.benchmarkProtocol.update({ where: { id: compatible.id }, data: { state: 'ACTIVE', activatedAt: new Date(), retiredAt: null } })
        : await tx.benchmarkProtocol.create({ data: { ...desired, state: 'ACTIVE', activatedAt: new Date() } });
    }
    return {
      schemaVersion: 1, applied: apply, alreadyActive, previousActiveProtocolIds: active.map(row => row.id),
      protocolId: protocol?.id ?? null, desired, historicalTimingInventory: inventory,
      oldEvidenceRewritten: false, timingRecovery: 'Not possible from encoded bytes alone; legacy timing remains in its original protocol.',
      collectionEpoch: 'NOT_DECLARED: packaged multi-system seven-clip acceptance still required',
      plActivation: 'UNCHANGED: genuine calibrated review and separate activation required',
    };
  });
  console.log(JSON.stringify(receipt, null, 2));
} finally { await db.$disconnect(); }
