/** Bounded diagnosis of the retained synthetic fixture. No fixture writes or mutation calls. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
const serverRoot = process.env.PROJECTION_SCALE_SERVER_ROOT
  ? pathToFileURL(`${resolve(process.env.PROJECTION_SCALE_SERVER_ROOT)}/`)
  : new URL('../../server/', import.meta.url);
const require = createRequire(new URL('package.json', serverRoot));
const { PrismaClient, Prisma } = require('@prisma/client');
const { buildPublicCorpusPageSql } = await import(new URL('dist/v7/corpusQuery.js', serverRoot));
const { measurementGroupStateHashSql } = await import(new URL('dist/v7/measurementGroup.js', serverRoot));
const database = new URL(process.env.PROJECTION_SCALE_DATABASE_URL);
assert.equal(database.hostname, '127.0.0.1');
assert.equal(database.pathname, '/encodingdb_projection_synthetic');
const sourceSha = process.env.PROJECTION_SCALE_SOURCE_SHA;
assert.match(sourceSha, /^[a-f0-9]{40}$/);
const output = process.env.PROJECTION_DIAGNOSTIC_OUTPUT;
assert.ok(output, 'Use a new diagnostic evidence directory');
await mkdir(output, { recursive: false });
const client = new PrismaClient({ datasources: { db: { url: database.toString() } } });
const id = 'SYNTHETIC-PROJECTION-ONLY';
const env = index => `${id}-env-${String(index).padStart(4, '0')}`;
const publicId = index => `${id}::${id}::${id}::${env(index)}::${id}-model`;
const base = `http://127.0.0.1:${Number(process.env.PROJECTION_SCALE_PORT ?? 55442)}`;
const routes = [
  { name: 'fps-desc', query: { sort: 'fps', dir: 'desc' }, skip: 0, take: 25, measuredWorkload: true },
  { name: 'vmaf-asc-page', query: { sort: 'vmaf', dir: 'asc' }, skip: 100, take: 25, measuredWorkload: true },
  { name: 'fps-asc-page', query: { sort: 'fps', dir: 'asc' }, skip: 500, take: 25, measuredWorkload: true },
  { name: 'filtered-fps', query: { search: 'SYNTHETIC CPU 00', sort: 'fps', dir: 'desc' }, skip: 0, take: 25, measuredWorkload: true },
  { name: 'hot-detail', query: {}, id: publicId(0), skip: 0, take: 25, measuredWorkload: true },
  { name: 'created-desc', query: { sort: 'createdAt', dir: 'desc' }, skip: 0, take: 25, measuredWorkload: false },
  { name: 'cpu-asc', query: { sort: 'cpuModel', dir: 'asc' }, skip: 0, take: 25, measuredWorkload: false },
];
const timings = [], errors = [], equivalence = [];
const started = new Date();
const deadline = performance.now() + 240000;
function remainingMs() {
  const remaining = Math.floor(deadline - performance.now());
  assert.ok(remaining > 0, 'Four-minute diagnostic deadline reached');
  return Math.min(15000, remaining);
}
async function readOnly(operation) {
  remainingMs();
  return client.$transaction(async tx => {
    await tx.$executeRawUnsafe('SET TRANSACTION READ ONLY');
    await tx.$executeRawUnsafe("SELECT set_config('statement_timeout','15000',true), set_config('jit','off',true), set_config('max_parallel_workers_per_gather','0',true)");
    return operation(tx);
  }, { timeout: 20000, maxWait: 5000 });
}
async function fetchRoute(route, phase, iteration) {
  const parameters = new URLSearchParams({ ...route.query, skip: String(route.skip), take: String(route.take), ...(route.id ? { id: route.id } : {}) });
  const begin = performance.now();
  try {
    const response = await fetch(`${base}/corpus?${parameters}`, { signal: AbortSignal.timeout(remainingMs()) });
    const body = await response.json();
    assert.equal(response.status, 200, JSON.stringify(body));
    assert.ok(body.rows.length > 0 && body.rows.length <= route.take);
    timings.push({ route: route.name, phase, iteration, ms: performance.now() - begin, rowIds: body.rows.map(row => row.id), totalCount: body.totalCount });
  } catch (error) { errors.push({ route: route.name, phase, iteration, ms: performance.now() - begin, error: String(error) }); }
}
try {
  const ready = await (await fetch(`${base}/memory`, { signal: AbortSignal.timeout(15000) })).json();
  assert.equal(ready.sourceSha, sourceSha);
  const [counts] = await readOnly(tx => tx.$queryRawUnsafe('SELECT (SELECT count(*) FROM "BenchmarkRun")::int AS runs, (SELECT count(*) FROM "DerivedResultMember")::int AS members, (SELECT count(*) FROM "PublicCorpusDirtyGroup")::int AS dirty'));
  assert.deepEqual(counts, { runs: 100020, members: 80020, dirty: 0 });
  for (const route of routes) for (let iteration = 0; iteration < 10; iteration++) await fetchRoute(route, 'serial', iteration);
  const measuredRoutes = routes.filter(route => route.measuredWorkload);
  for (let round = 0; round < 3; round++) {
    await Promise.all(Array.from({ length: 25 }, (_, index) => fetchRoute(measuredRoutes[index % measuredRoutes.length], 'concurrent-25', round * 25 + index)));
  }
  for (const route of routes) {
    const plan = await readOnly(tx => tx.$queryRaw(Prisma.sql`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ${buildPublicCorpusPageSql(route.query, route.take, route.skip, [id], route.id)}`));
    await writeFile(`${output}/plan-${route.name}.json`, JSON.stringify(plan, null, 2));
  }
  for (const index of [0, 1, 500, 980]) {
    const rows = await readOnly(tx => tx.$queryRaw(Prisma.sql`SELECT id FROM "DerivedResult" WHERE "environmentId" = ${env(index)}`));
    assert.equal(rows.length, 1);
    const derivedId = Prisma.sql`${rows[0].id}::text`;
    const originalScope = Prisma.sql`EXISTS (SELECT 1 FROM "DerivedResultMember" member JOIN "BenchmarkRun" counted ON counted.id = member."benchmarkRunId" WHERE member."derivedResultId" = ${derivedId} AND counted."physicalSourceId" = r."physicalSourceId" AND counted."campaignId" = r."campaignId" AND counted."repetitionGroupId" = r."repetitionGroupId")`;
    const dependencyScope = Prisma.sql`EXISTS (SELECT 1 FROM "DerivedResultGroupDependency" dependency WHERE dependency."derivedResultId" = ${derivedId} AND dependency."physicalSourceId" = r."physicalSourceId" AND dependency."campaignId" = r."campaignId" AND dependency."repetitionGroupId" = r."repetitionGroupId")`;
    const comparisonSql = Prisma.sql`WITH old_rows AS (SELECT r.id FROM "BenchmarkRun" r WHERE ${originalScope}), proposed_rows AS (SELECT r.id FROM "BenchmarkRun" r WHERE ${dependencyScope})
      SELECT (SELECT count(*)::int FROM old_rows) AS "oldCount", (SELECT count(*)::int FROM proposed_rows) AS "proposedCount",
      (SELECT count(*)::int FROM (SELECT * FROM old_rows EXCEPT SELECT * FROM proposed_rows) missing) AS missing,
      (SELECT count(*)::int FROM (SELECT * FROM proposed_rows EXCEPT SELECT * FROM old_rows) extra) AS extra,
      ${measurementGroupStateHashSql(originalScope)} AS "oldHash", ${measurementGroupStateHashSql(dependencyScope)} AS "proposedHash"`;
    const [comparison] = await readOnly(tx => tx.$queryRaw(comparisonSql));
    assert.equal(comparison.missing, 0); assert.equal(comparison.extra, 0); assert.equal(comparison.oldHash, comparison.proposedHash);
    equivalence.push({ environment: env(index), ...comparison });
    for (const [name, scope] of [['original', originalScope], ['dependency', dependencyScope]]) {
      const plan = await readOnly(tx => tx.$queryRaw(Prisma.sql`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ${measurementGroupStateHashSql(scope)}`));
      await writeFile(`${output}/certificate-${index}-${name}.json`, JSON.stringify(plan, null, 2));
    }
  }
} catch (error) { errors.push({ phase: 'diagnostic', error: String(error) }); process.exitCode = 1; }
finally {
  await writeFile(`${output}/diagnostic.json`, JSON.stringify({ sourceSha, started, completed: new Date(), purpose: 'Bounded bottleneck diagnosis, not a capacity pass or threshold change', timings, errors, equivalence }, null, 2));
  await client.$disconnect();
}
