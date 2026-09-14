import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, mkdir, readFile, writeFile, copyFile, access, rm } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import os from 'node:os';
import path from 'node:path';
import { verifyDeploymentVolumes } from '../../scripts/verify-deployment-volumes.mjs';
const exec = promisify(execFile);
const repo = path.resolve(import.meta.dirname, '../..');
const config = { name: 'encodingdb', services: { db: { volumes: [{ type: 'volume', source: 'db_data', target: '/var/lib/postgresql/data' }] }, server: { volumes: [{ type: 'volume', source: 'artifact_data', target: '/app/artifacts' }] } }, volumes: { db_data: { name: 'encodingdb_db_data' }, artifact_data: { name: 'encodingdb_prod_artifact_data' } } };
const container = (service, destination, name) => ({ Config: { Labels: { 'com.docker.compose.project': 'encodingdb', 'com.docker.compose.service': service } }, Mounts: [{ Type: 'volume', Destination: destination, Name: name }] });
const existing = [container('db', '/var/lib/postgresql/data', 'encodingdb_db_data'), container('server', '/app/artifacts', 'encodingdb_prod_artifact_data')];

test('existing database and artifact volume identities must both be preserved', () => {
  assert.equal(verifyDeploymentVolumes(config, existing).checked.length, 2);
  for (const [key, wrong] of [['db_data', 'encodingdb_prod_db_data'], ['artifact_data', 'new_artifact_data']]) {
    const changed = structuredClone(config); changed.volumes[key].name = wrong;
    assert.throws(() => verifyDeploymentVolumes(changed, existing), /Refusing rollout/);
  }
  assert.equal(verifyDeploymentVolumes(config, []).checked.length, 0);
});

test('existing named evidence mounts cannot be replaced with a bind or removed', () => {
  const changed = structuredClone(config); changed.services.server.volumes = [];
  assert.throws(() => verifyDeploymentVolumes(changed, existing), /must preserve/);
});

test('actual deploy entry point rejects mismatched data before build or rollout', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-volume-guard-'));
  try {
    await mkdir(path.join(root, 'scripts')); await mkdir(path.join(root, 'bin'));
    await copyFile(path.join(repo, 'deploy.sh'), path.join(root, 'deploy.sh'));
    await copyFile(path.join(repo, 'scripts/verify-deployment-volumes.mjs'), path.join(root, 'scripts/verify-deployment-volumes.mjs'));
    await writeFile(path.join(root, 'scripts/validate-production-env.mjs'), '');
    await writeFile(path.join(root, 'docker-compose.prod.yml'), 'services: {}\n');
    await writeFile(path.join(root, '.env'), 'INGEST_MODE=public\n');
    const changed = structuredClone(config); changed.volumes.db_data.name = 'encodingdb_prod_db_data';
    const mock = `#!${process.execPath}\nimport fs from 'node:fs';\nconst args=process.argv.slice(2);\nif(args.includes('version')) console.log('v2');\nelse if(args.includes('config')&&args.includes('--format')) console.log(${JSON.stringify(JSON.stringify(changed))});\nelse if(args[0]==='ps')console.log('existing');\nelse if(args[0]==='inspect')console.log(${JSON.stringify(JSON.stringify(existing))});\nelse if(args.includes('build')||args.includes('up'))fs.writeFileSync(${JSON.stringify(path.join(root, 'mutated'))},'bad');\n`;
    await writeFile(path.join(root, 'bin/docker'), mock, { mode: 0o755 });
    await writeFile(path.join(root, 'bin/package.json'), '{"type":"module"}');
    await writeFile(path.join(root, 'bin/git'), '#!/bin/sh\necho true\n', { mode: 0o755 });
    await assert.rejects(exec('bash', [path.join(root, 'deploy.sh'), '--skip-pull'], { cwd: root, env: { ...process.env, PATH: path.join(root, 'bin') + path.delimiter + process.env.PATH } }), (error) => error.code === 1 && /Refusing rollout/.test(error.stderr));
    await assert.rejects(access(path.join(root, 'mutated')));
  } finally { await rm(root, { recursive: true, force: true }); }
});
