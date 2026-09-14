// Isolated real-media regression; never submits rows or writes application database state.
import { mkdir, mkdtemp, readFile, rm, writeFile, stat } from 'node:fs/promises';
import os from 'node:os';
import crypto from 'node:crypto';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { FfmpegArtifactAnalyzer, DEFAULT_ANALYZER_VERSION } from '../dist/v7/artifacts.js';
import { loadAuthoritativeSuiteManifest, buildSuiteTestClipRecordInput } from '../dist/v7/suite.js';
import { runNativeProcess } from '../dist/v7/nativeProcess.js';

const manifest = loadAuthoritativeSuiteManifest();
const root = process.env.BACKEND_MEDIA_ARTIFACT_DIR || await mkdtemp(path.join(os.tmpdir(), 'encodingdb-seven-clip-check-'));
await mkdir(root, { recursive: true });
const report = { kind: 'isolated-worker-correctness-trial-not-calibration', host: os.hostname(), platform: os.platform(), architecture: os.arch(), startedAt: new Date().toISOString(), suiteVersion: manifest.suiteVersion, analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, ffmpegVersion: (await runNativeProcess('ffmpeg', ['-version'])).stdout.split('\n')[0], cases: [] };
const analyzer = new FfmpegArtifactAnalyzer(DEFAULT_ANALYZER_VERSION);
try {
  for (const clip of manifest.clips) {
    const source = buildSuiteTestClipRecordInput(manifest, clip);
    const sourcePath = new URL(`../resources/test_suite_v1/canonical/${source.sourceProvenance.fileName}`, import.meta.url).pathname;
    const output = path.join(root, `${clip.id}.mp4`);
    const encodeStart = performance.now();
    await runNativeProcess('ffmpeg', ['-v', 'error', '-i', sourcePath, '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv', output]);
    const encodeMs = performance.now() - encodeStart;
    const bundle = { run: { testClip: source, recipe: { codecFamily: 'h264', encoderImplementation: 'libx264', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', containerFormat: 'mp4' }, benchmarkProtocol: { metricWorkerVersion: DEFAULT_ANALYZER_VERSION } } };
    const analysisStart = performance.now();
    try {
      const result = await analyzer.analyze({ bundle, artifactPath: output, requestedAnalysisWorkerVersion: DEFAULT_ANALYZER_VERSION });
      await writeFile(path.join(root, `${clip.id}-analysis.json`), JSON.stringify(result, null, 2));
      report.cases.push({ artifactPath: output, artifactSha256: crypto.createHash('sha256').update(await readFile(output)).digest('hex'), analysisPath: path.join(root, `${clip.id}-analysis.json`), clip: clip.id, expectedFrames: source.exactFrameCount, metricFrames: result.vmafDistribution.frameCount, encodeMs, analysisMs: performance.now() - analysisStart, artifactBytes: (await stat(output)).size, vmafMean: result.vmafMean, vmafP5: result.vmafP5, xpsnr: result.xpsnr, ssim: result.ssim, psnr: result.psnr, status: result.analysisStatus, diagnosticFrames: result.analysisProvenance.diagnosticFrameCount });
      console.log(`${clip.id}: ${result.analysisStatus}, frames=${result.vmafDistribution.frameCount}, analysisMs=${Math.round(performance.now() - analysisStart)}`);
    } catch (error) { report.cases.push({ clip: clip.id, error: String(error) }); console.error(error); break; }
  }
} finally {
  report.completedAt = new Date().toISOString();
  await writeFile(process.env.BACKEND_MEDIA_REPORT || '/tmp/encodingdb-seven-clip-worker.json', JSON.stringify(report, null, 2));
  if (!process.env.BACKEND_MEDIA_ARTIFACT_DIR) await rm(root, { recursive: true, force: true });
}
if (report.cases.length !== 7 || report.cases.some(entry => entry.error || entry.metricFrames !== entry.expectedFrames || entry.diagnosticFrames !== entry.expectedFrames)) process.exitCode = 1;
