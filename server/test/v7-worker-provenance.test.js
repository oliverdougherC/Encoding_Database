import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { chmod, cp, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const exec = promisify(execFile);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

test('installed worker provenance binds executed tool bytes and compiled closure across process starts', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'installed-worker-provenance-'));
  try {
    await cp(fileURLToPath(new URL('../dist/', import.meta.url)), path.join(root, 'dist'), { recursive: true });
    await writeFile(path.join(root, 'package.json'), '{"type":"module"}');
    for (const name of ['ffmpeg', 'ffprobe']) {
      await writeFile(path.join(root, name), `#!${process.execPath}\nprocess.stdout.write('same version string\\n');\n`);
      await chmod(path.join(root, name), 0o755);
    }
    const moduleUrl = pathToFileURL(path.join(root, 'dist/v7/workerProvenance.js')).href;
    const nativeUrl = pathToFileURL(path.join(root, 'dist/v7/nativeProcess.js')).href;
    const snapshot = async () => JSON.parse((await exec(process.execPath, ['--input-type=module', '-e', `const p=await import(${JSON.stringify(moduleUrl)});const n=await import(${JSON.stringify(nativeUrl)});const identity=await p.installedWorkerProvenance();const output=await n.runNativeProcess('ffmpeg',['-version']);console.log(JSON.stringify({identity,version:output.stdout}))`], { env: { ...process.env, PATH: root } })).stdout);
    const first = await snapshot();
    assert.equal(first.identity.installedTools.ffmpeg.path, await realpath(path.join(root, 'ffmpeg')));
    assert.equal(first.identity.installedTools.ffmpeg.sha256, digest(await readFile(path.join(root, 'ffmpeg'))));
    for (const module of first.identity.workerModules) assert.equal(module.sha256, digest(await readFile(path.join(root, 'dist', module.module))));
    for (const name of ['v7/artifacts.js', 'v7/nativeProcess.js', 'qualityAnalysis.js', 'v7/suite.js']) assert.ok(first.identity.workerModules.some(module => module.module === name));
    assert.deepEqual(await snapshot(), first, 'restarts over the same installed bytes reproduce the fingerprint');
    await writeFile(path.join(root, 'ffmpeg'), `#!${process.execPath}\n// changed build, unchanged version\nprocess.stdout.write('same version string\\n');\n`);
    const changedTool = await snapshot();
    assert.equal(changedTool.version, first.version);
    assert.notEqual(changedTool.identity.installedTools.ffmpeg.sha256, first.identity.installedTools.ffmpeg.sha256);
    assert.notEqual(changedTool.identity.workerBuildFingerprint, first.identity.workerBuildFingerprint);
    const workerFile = path.join(root, 'dist/v7/artifacts.js');
    await writeFile(workerFile, `${await readFile(workerFile, 'utf8')}\n// changed installed worker\n`);
    const changedWorker = await snapshot();
    assert.notEqual(changedWorker.identity.workerModuleFingerprint, changedTool.identity.workerModuleFingerprint);
    assert.notEqual(changedWorker.identity.workerBuildFingerprint, changedTool.identity.workerBuildFingerprint);
    const runningCheck = await exec(process.execPath, ['--input-type=module', '-e', `const p=await import(${JSON.stringify(moduleUrl)});await p.installedWorkerProvenance();await (await import('node:fs/promises')).appendFile(${JSON.stringify(path.join(root, 'ffprobe'))},'// changed in place');try{await p.installedWorkerProvenance();process.exitCode=1}catch(e){console.log(e.message)}`], { env: { ...process.env, PATH: root } });
    assert.match(runningCheck.stdout, /changed; restart/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
