#!/usr/bin/env node
// Real native analyzer capacity only: does not submit contribution rows or fit PL.
import { mkdir, readFile, writeFile, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import { performance } from 'node:perf_hooks';
import { FfmpegArtifactAnalyzer, DEFAULT_ANALYZER_VERSION } from '../dist/v7/artifacts.js';
import { loadAuthoritativeSuiteManifest, buildSuiteTestClipRecordInput } from '../dist/v7/suite.js';
import { runNativeProcess } from '../dist/v7/nativeProcess.js';

const mode = process.env.WORKER_CAPACITY_MODE;
const root = process.env.WORKER_CAPACITY_ROOT;
const concurrency = Number(process.env.WORKER_CAPACITY_CONCURRENCY || '1');
if (!['prepare', 'analyze'].includes(mode) || !root || !path.isAbsolute(root) || ![1, 2].includes(concurrency)) throw Error('Set WORKER_CAPACITY_MODE=prepare|analyze, absolute WORKER_CAPACITY_ROOT and concurrency 1|2');
const manifest = loadAuthoritativeSuiteManifest();
const preparedPath = path.join(root, 'prepared.json');
const artifactRoot = path.join(root, 'encoded');
await mkdir(artifactRoot, { recursive: true });
async function digest(file) { const hash = crypto.createHash('sha256'); for await (const chunk of createReadStream(file)) hash.update(chunk); return hash.digest('hex'); }
async function counter(file) { try { const value = Number((await readFile(file, 'utf8')).trim()); return Number.isFinite(value) ? value : null; } catch { return null; } }
const sourceFor = (clip) => buildSuiteTestClipRecordInput(manifest, clip);

if (mode === 'prepare') {
  const prepared = { kind: 'real-media-fixtures-not-client-timing', suiteVersion: manifest.suiteVersion, createdAt: new Date().toISOString(), artifacts: [] };
  for (const clip of manifest.clips) {
    const source = sourceFor(clip);
    const sourcePath = new URL(`../resources/test_suite_v1/canonical/${source.sourceProvenance.fileName}`, import.meta.url).pathname;
    const artifactPath = path.join(artifactRoot, `${clip.id}.mp4`);
    await runNativeProcess('ffmpeg', ['-v', 'error', '-n', '-threads', '1', '-i', sourcePath, '-an', '-c:v', 'libx264', '-threads', '2', '-filter_threads', '1', '-filter_complex_threads', '1', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv', artifactPath]);
    prepared.artifacts.push({ clip: clip.id, artifactPath, sha256: await digest(artifactPath), bytes: (await stat(artifactPath)).size });
    console.log(`Prepared ${clip.id}`);
  }
  await writeFile(preparedPath, JSON.stringify(prepared, null, 2) + '\n', { flag: 'wx' });
} else {
  const prepared = JSON.parse(await readFile(preparedPath, 'utf8'));
  if (prepared.suiteVersion !== manifest.suiteVersion || prepared.artifacts.length !== 7) throw Error('Complete matching seven-clip fixture preparation required');
  const output = path.join(root, `analysis-c${concurrency}`);
  await mkdir(output); // Never overwrite an earlier trial.
  const analyzer = new FfmpegArtifactAnalyzer(DEFAULT_ANALYZER_VERSION);
  const report = { kind: 'isolated-linux-native-analyzer-capacity-not-client-timing-or-calibration', startedAt: new Date().toISOString(), host: `${os.platform()}-${os.arch()}-evidence-host`, hostLabelIsAnonymous: true, platform: os.platform(), architecture: os.arch(), sourceCommit: process.env.WORKER_CAPACITY_SOURCE_COMMIT, imageId: process.env.WORKER_CAPACITY_IMAGE_ID, analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, concurrency, suiteVersion: manifest.suiteVersion, ffmpegVersion: (await runNativeProcess('ffmpeg', ['-version'])).stdout.split('\n')[0], cases: [], errors: [] };
  let sampledPeak = 0;
  const sample = async () => { const value = await counter('/sys/fs/cgroup/memory.current') ?? await counter('/sys/fs/cgroup/memory/memory.usage_in_bytes'); if (value != null) sampledPeak = Math.max(sampledPeak, value); };
  const timer = setInterval(() => { sample().catch(() => {}); }, 250);
  timer.unref();
  const started = performance.now();
  let next = 0;
  try {
    await Promise.all(Array.from({ length: concurrency }, async () => {
      while (next < manifest.clips.length) {
        const clip = manifest.clips[next++];
        const source = sourceFor(clip);
        const fixture = prepared.artifacts.find((item) => item.clip === clip.id);
        if (!fixture || await digest(fixture.artifactPath) !== fixture.sha256) throw Error(`Changed fixture ${clip.id}`);
        const began = performance.now();
        const bundle = { run: { testClip: source, recipe: { codecFamily: 'h264', encoderImplementation: 'libx264', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', containerFormat: 'mp4' }, benchmarkProtocol: { metricWorkerVersion: DEFAULT_ANALYZER_VERSION } } };
        try {
          const result = await analyzer.analyze({ bundle, artifactPath: fixture.artifactPath, requestedAnalysisWorkerVersion: DEFAULT_ANALYZER_VERSION });
          const analysisPath = path.join(output, `${clip.id}.json`);
          await writeFile(analysisPath, JSON.stringify(result, null, 2) + '\n');
          const entry = { clip: clip.id, artifactSha256: fixture.sha256, artifactBytes: fixture.bytes, expectedFrames: source.exactFrameCount, metricFrames: result.vmafDistribution.frameCount, diagnosticFrames: result.analysisProvenance.diagnosticFrameCount, analysisStatus: result.analysisStatus, startedAfterMs: began - started, analysisMs: performance.now() - began, analysisPath };
          report.cases.push(entry);
          if (entry.metricFrames !== entry.expectedFrames || entry.diagnosticFrames !== entry.expectedFrames) throw Error(`Incomplete coverage ${clip.id}`);
          console.log(`${clip.id}: ${entry.analysisStatus}, ${Math.round(entry.analysisMs)} ms`);
        } catch (error) { report.errors.push({ clip: clip.id, message: String(error) }); }
      }
    }));
  } finally {
    clearInterval(timer);
    await sample();
    report.elapsedMs = performance.now() - started;
    report.completedAt = new Date().toISOString();
    report.cgroupPeakMemoryBytes = await counter('/sys/fs/cgroup/memory.peak') ?? await counter('/sys/fs/cgroup/memory/memory.max_usage_in_bytes');
    report.cgroupMemoryLimitBytes = await counter('/sys/fs/cgroup/memory.max') ?? await counter('/sys/fs/cgroup/memory/memory.limit_in_bytes');
    report.sampledPeakCgroupMemoryBytes = sampledPeak;
    report.nodeMaxRssBytes = process.resourceUsage().maxRSS * 1024;
    report.status = report.cases.length === 7 && report.errors.length === 0 ? 'passed' : 'failed';
    await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  }
  if (report.status !== 'passed') process.exitCode = 1;
}
