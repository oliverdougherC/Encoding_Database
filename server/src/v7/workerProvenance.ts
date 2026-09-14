import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFile, stat } from 'node:fs/promises';
import { installedMediaTool, sha256InstalledFile } from './nativeProcess.js';

let compiledBuild: Promise<{ workerModuleFingerprint: string; workerModules: Array<{ module: string; sha256: string }> }> | undefined;
async function compiledWorkerIdentity() {
  compiledBuild ??= (async () => {
    const distRoot = fileURLToPath(new URL('../', import.meta.url));
    const pending = ['v7/artifacts.js', 'v7/nativeProcess.js', 'qualityAnalysis.js', 'v7/suite.js', 'v7/workerProvenance.js'].map(name => path.join(distRoot, name));
    const files = new Map<string, string>();
    while (pending.length) {
      const filename = pending.pop()!;
      if (files.has(filename)) continue;
      if (!filename.startsWith(distRoot)) throw new Error('Worker import escaped the compiled distribution');
      if ((await stat(filename)).size > 2 * 1024 * 1024) throw new Error('Compiled worker module exceeds provenance scan budget');
      files.set(filename, await sha256InstalledFile(filename));
      const source = await readFile(filename, 'utf8');
      for (const match of source.matchAll(/(?:from\s*|import\s*\()\s*['"](\.{1,2}\/[^'"]+\.js)['"]/g)) pending.push(path.resolve(path.dirname(filename), match[1]!));
    }
    const workerModules = [...files].map(([filename, sha256]) => ({ module: path.relative(distRoot, filename).split(path.sep).join('/'), sha256 })).sort((a, b) => a.module.localeCompare(b.module));
    const workerModuleFingerprint = crypto.createHash('sha256').update(JSON.stringify({ contract: 'encodingdb-installed-worker/v1', nodeVersion: process.version, workerModules })).digest('hex');
    return { workerModuleFingerprint, workerModules };
  })();
  return compiledBuild;
}

/** Derived only from the server's installed files. Public requests cannot supply these fields. */
export async function installedWorkerProvenance() {
  const [worker, ffmpeg, ffprobe] = await Promise.all([compiledWorkerIdentity(), installedMediaTool('ffmpeg'), installedMediaTool('ffprobe')]);
  const workerBuildFingerprint = crypto.createHash('sha256').update(JSON.stringify({ workerModuleFingerprint: worker.workerModuleFingerprint, ffmpeg: ffmpeg.sha256, ffprobe: ffprobe.sha256, nodeVersion: process.version, platform: process.platform, architecture: process.arch })).digest('hex');
  return { ...worker, workerBuildFingerprint, installedTools: { ffmpeg, ffprobe }, nodeVersion: process.version, platform: process.platform, architecture: process.arch };
}
