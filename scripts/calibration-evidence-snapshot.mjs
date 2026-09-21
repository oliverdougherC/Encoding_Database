#!/usr/bin/env node
// Sealed, explicit-run evidence transfer. Imports only into isolated calibration databases.
import { readFile, mkdir, copyFile, rename, stat, writeFile, realpath } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const serverRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../server');
const { PrismaClient, Prisma } = await import(path.join(serverRoot, 'node_modules/@prisma/client/default.js'));
const { canonicalJsonString, sha256Hex } = await import(path.join(serverRoot, 'dist/v7/persistence.js'));
const models = { protocols: 'benchmarkProtocol', clips: 'testClip', recipes: 'recipe', environments: 'environment', runs: 'benchmarkRun', artifacts: 'artifact', analyses: 'qualityAnalysis', reviews: 'evidenceReview' };
const modelNames = Object.fromEntries(Object.entries(models).map(([key, model]) => [key, model[0].toUpperCase() + model.slice(1)]));
const json = value => JSON.parse(JSON.stringify(value, (_key, item) => typeof item === 'bigint' ? item.toString() : item));
const hash = value => sha256Hex(canonicalJsonString(json(value)));
async function fileHash(file) { const digest = createHash('sha256'); for await (const chunk of createReadStream(file)) digest.update(chunk); return digest.digest('hex'); }
const unique = values => [...new Set(values)];

export async function exportCalibrationSnapshot(client, { runIds, sourceRoot, output, maxBytes = 10 * 1024 ** 3 }) {
  if (!Array.isArray(runIds) || !runIds.length || runIds.length > 20000 || unique(runIds).length !== runIds.length) throw new Error('An explicit unique list of 1–20000 run IDs is required');
  const root = await realpath(sourceRoot); const destination = path.resolve(output);
  await mkdir(destination); await mkdir(path.join(destination, 'objects'));
  const tables = await client.$transaction(async tx => {
    await tx.$executeRawUnsafe('SET TRANSACTION READ ONLY');
    const runs = await tx.benchmarkRun.findMany({ where: { id: { in: runIds } }, orderBy: { id: 'asc' } });
    if (runs.length !== runIds.length) throw new Error('Selected run identity is missing');
    const artifacts = await tx.artifact.findMany({ where: { benchmarkRunId: { in: runIds } }, orderBy: { id: 'asc' } });
    const analyses = await tx.qualityAnalysis.findMany({ where: { benchmarkRunId: { in: runIds } }, orderBy: [{ createdAt: 'asc' }, { id: 'asc' }] });
    if (artifacts.some(row => !['VERIFIED', 'RETAINED'].includes(row.storageState)) || analyses.some(row => row.leaseToken || row.status === 'PENDING')) throw new Error('Export requires settled evidence; no pending uploads or running analyses');
    return {
      protocols: await tx.benchmarkProtocol.findMany({ where: { id: { in: unique(runs.map(row => row.benchmarkProtocolId)) } }, orderBy: { id: 'asc' } }),
      clips: await tx.testClip.findMany({ where: { id: { in: unique(runs.map(row => row.testClipId)) } }, orderBy: { id: 'asc' } }),
      recipes: await tx.recipe.findMany({ where: { id: { in: unique(runs.map(row => row.recipeId)) } }, orderBy: { id: 'asc' } }),
      environments: await tx.environment.findMany({ where: { id: { in: unique(runs.map(row => row.environmentId)) } }, orderBy: { id: 'asc' } }),
      runs, artifacts, analyses,
      reviews: await tx.evidenceReview.findMany({ where: { benchmarkRunId: { in: runIds } }, orderBy: [{ createdAt: 'asc' }, { id: 'asc' }] }),
    };
  }, { isolationLevel: 'RepeatableRead', timeout: 120000 });
  const retainedBytes = [...new Map(tables.artifacts.map(row => [row.sha256, row.byteSize ?? 0])).values()].reduce((sum, bytes) => sum + bytes, 0);
  if (!Number.isFinite(maxBytes) || maxBytes <= 0 || retainedBytes > maxBytes) throw new Error('Explicit snapshot byte budget exceeded');
  const objects = [];
  for (const artifact of tables.artifacts) {
    if (!artifact.sha256 || artifact.storageProvider !== 'localfs' || !artifact.storageKey) throw new Error('Missing retained local object identity');
    const source = await realpath(path.resolve(root, artifact.storageKey));
    if (!source.startsWith(`${root}${path.sep}`) || (await stat(source)).size !== artifact.byteSize || await fileHash(source) !== artifact.sha256) throw new Error('Source object identity or hash mismatch');
    if (objects.some(row => row.sha256 === artifact.sha256)) continue;
    const file = path.join(destination, 'objects', artifact.sha256); await copyFile(source, file);
    if (await fileHash(file) !== artifact.sha256) throw new Error('Snapshot object copy differs');
    objects.push({ sha256: artifact.sha256, byteSize: artifact.byteSize });
  }
  const snapshot = { schemaVersion: 'encodingdb-calibration-evidence-snapshot/v1', capturedAt: new Date().toISOString(), runIds: [...runIds].sort(), tables: json(tables), objects };
  snapshot.snapshotHash = hash(snapshot);
  await writeFile(path.join(destination, 'snapshot.json'), `${JSON.stringify(snapshot, null, 2)}\n`, { flag: 'wx' });
  return { snapshotHash: snapshot.snapshotHash, runIds: snapshot.runIds, objectCount: objects.length };
}

function restoreData(key, row) {
  const model = Prisma.dmmf.datamodel.models.find(entry => entry.name === modelNames[key]);
  return Object.fromEntries(Object.entries(row).map(([name, value]) => {
    const field = model.fields.find(entry => entry.name === name);
    if (!field || field.kind === 'object') throw new Error(`Snapshot contains unsupported field ${key}.${name}`);
    if (field.type === 'DateTime' && value != null) return [name, new Date(value)];
    if (field.type === 'BigInt' && value != null) return [name, BigInt(value)];
    if (field.type === 'Json' && value == null) return [name, field.isRequired ? Prisma.JsonNull : Prisma.DbNull];
    return [name, value];
  }));
}
function dimensionCore(key, row) {
  const value = json(row); delete value.id; delete value.createdAt; delete value.updatedAt;
  if (key === 'protocols') { delete value.activatedAt; delete value.retiredAt; }
  return value;
}
export async function importCalibrationSnapshot(client, { snapshotDirectory, storageRoot }) {
  const database = await client.$queryRawUnsafe('SELECT current_database() AS name');
  if (!/^encodingdb_calibration_[a-z0-9_]+$/.test(database[0].name)) throw new Error('Import target must be a separate encodingdb_calibration_* database');
  const snapshot = JSON.parse(await readFile(path.join(snapshotDirectory, 'snapshot.json'), 'utf8'));
  const { snapshotHash, ...payload } = snapshot;
  if (snapshot.schemaVersion !== 'encodingdb-calibration-evidence-snapshot/v1' || hash(payload) !== snapshotHash) throw new Error('Snapshot metadata hash mismatch');
  const root = path.resolve(storageRoot); await mkdir(root, { recursive: true });
  for (const object of snapshot.objects) {
    if (!/^[a-f0-9]{64}$/.test(object.sha256)) throw new Error('Invalid object digest');
    const file = path.join(snapshotDirectory, 'objects', object.sha256);
    if ((await stat(file)).size !== object.byteSize || await fileHash(file) !== object.sha256) throw new Error('Snapshot object hash or size mismatch');
    const destination = path.join(root, 'objects', object.sha256.slice(0, 2), object.sha256); await mkdir(path.dirname(destination), { recursive: true });
    const temporary = `${destination}.${process.pid}.partial`; await copyFile(file, temporary); await rename(temporary, destination);
  }
  const aliases = { protocols: {}, clips: {}, recipes: {}, environments: {} };
  await client.$transaction(async tx => {
    await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(714555)');
    for (const key of Object.keys(aliases)) {
      for (const row of snapshot.tables[key]) {
        const model = models[key];
        const where = key === 'protocols' ? { protocolVersion_sourceSuiteVersion_metricWorkerVersion: { protocolVersion: row.protocolVersion, sourceSuiteVersion: row.sourceSuiteVersion, metricWorkerVersion: row.metricWorkerVersion } }
          : key === 'clips' ? { sha256: row.sha256 } : { fingerprint: row.fingerprint };
        const byId = await tx[model].findUnique({ where: { id: row.id } });
        const existing = byId ?? await tx[model].findUnique({ where });
        if (existing) {
          if (hash(dimensionCore(key, existing)) !== hash(dimensionCore(key, row))) throw new Error(`Conflicting ${key} identity; refusing semantic relabeling`);
          aliases[key][row.id] = existing.id;
        } else {
          await tx[model].create({ data: restoreData(key, row) }); aliases[key][row.id] = row.id;
        }
      }
    }
    for (const key of ['runs', 'artifacts', 'analyses', 'reviews']) {
      for (const original of snapshot.tables[key]) {
        const row = { ...original };
        if (key === 'runs') {
          row.benchmarkProtocolId = aliases.protocols[row.benchmarkProtocolId]; row.testClipId = aliases.clips[row.testClipId];
          row.recipeId = aliases.recipes[row.recipeId]; row.environmentId = aliases.environments[row.environmentId];
        }
        if (key === 'artifacts') {
          row.storageKey = path.join('objects', row.sha256.slice(0, 2), row.sha256); row.storageUrl = path.join(root, row.storageKey); row.storageProvider = 'localfs';
        }
        const existing = await tx[models[key]].findUnique({ where: { id: row.id } });
        if (existing) {
          if (hash(existing) !== hash(row)) throw new Error(`Existing ${key} differs from sealed source snapshot`);
        } else await tx[models[key]].create({ data: restoreData(key, row) });
      }
    }
  }, { timeout: 120000 });
  const result = { snapshotHash, preservedRunIds: snapshot.tables.runs.map(row => row.id), preservedArtifactIds: snapshot.tables.artifacts.map(row => row.id), preservedAnalysisIds: snapshot.tables.analyses.map(row => row.id), dimensionAliases: aliases };
  await writeFile(path.join(root, `import-${snapshotHash}.json`), `${JSON.stringify(result, null, 2)}\n`);
  return result;
}

async function main() {
  const mode = process.argv[2]; const flags = new Map(); for (let i = 3; i < process.argv.length; i += 2) flags.set(process.argv[i], process.argv[i + 1]);
  const url = mode === 'export' ? process.env.CALIBRATION_SOURCE_DATABASE_URL : process.env.CALIBRATION_COMBINED_DATABASE_URL;
  if (!url || !['export', 'import'].includes(mode)) throw new Error('Use export/import with explicit CALIBRATION_SOURCE_DATABASE_URL or CALIBRATION_COMBINED_DATABASE_URL');
  const client = new PrismaClient({ datasources: { db: { url } } });
  try {
    const result = mode === 'export' ? await exportCalibrationSnapshot(client, { runIds: JSON.parse(await readFile(flags.get('--run-ids'), 'utf8')), sourceRoot: flags.get('--source-root'), output: flags.get('--output'), maxBytes: flags.has('--max-bytes') ? Number(flags.get('--max-bytes')) : undefined })
      : await importCalibrationSnapshot(client, { snapshotDirectory: flags.get('--snapshot'), storageRoot: flags.get('--storage-root') });
    console.log(JSON.stringify(result, null, 2));
  } finally { await client.$disconnect(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => { console.error(error.message); process.exitCode = 1; });
