#!/usr/bin/env node
import { readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const args = new Map(); for (let i = 2; i < process.argv.length; i += 2) args.set(process.argv[i], process.argv[i + 1]);
if (!args.get('--media-root') || !args.get('--output')) throw new Error('--media-root and --output are required');
const root = path.resolve(args.get('--media-root'));
const server = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../server');
const { canonicalJsonString, sha256Hex } = await import(path.join(server, 'dist/v7/persistence.js'));
const { VALIDATION_SOURCE_SUITE } = await import(path.join(server, 'dist/v7/validationSources.js'));
const sources = [];
for (const directory of (await readdir(root, { withFileTypes: true })).filter(entry => entry.isDirectory())) {
  const reportPath = path.join(root, directory.name, 'evidence.json');
  let report; try { report = JSON.parse(await readFile(reportPath, 'utf8')); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
  const input = report.planEntry; const media = path.join(root, directory.name, 'reference.mkv');
  const digest = createHash('sha256'); for await (const chunk of createReadStream(media)) digest.update(chunk);
  if (report.validationOnly !== true || report.status !== 'TECHNICALLY_VALIDATED_REVIEW_PENDING' || report.exitCodes.some(code => code !== 0)
    || report.sha256 !== digest.digest('hex') || report.byteSize !== (await stat(media)).size) throw new Error(`Unverified validation media ${directory.name}`);
  sources.push({ sourceSuiteVersion: VALIDATION_SOURCE_SUITE, workloadId: `validation-${input.id}`, sourceSha256: report.sha256,
    sourceGroupId: input.sourceGroupId, sceneGroupId: input.sceneGroupId, firstSourceFrame: input.firstSourceFrame,
    endSourceFrameExclusive: input.endSourceFrameExclusive, sourceFrameRate: input.sourceFrameRate, contentClass: input.contentClassCandidate,
    frameCount: Number(report.probe.streams[0].nb_read_frames), durationSeconds: Number(report.probe.format.duration), byteSize: report.byteSize,
    width: 1920, height: 1080, pixelFormat: 'yuv420p', frameRate: '24/1', normalization: input.normalization,
    sourceEvidenceHash: sha256Hex(canonicalJsonString(report)),
  });
}
if (!sources.length) throw new Error('No completed validation-only scenes were found');
sources.sort((a, b) => a.workloadId.localeCompare(b.workloadId));
const registry = { schemaVersion: 'encodingdb-validation-source-registry/v1', sources };
registry.registryHash = sha256Hex(canonicalJsonString(registry));
await writeFile(path.resolve(args.get('--output')), `${JSON.stringify(registry, null, 2)}\n`, { flag: 'wx' });
console.log(JSON.stringify({ sourceCount: sources.length, registryHash: registry.registryHash, output: path.resolve(args.get('--output')) }));
