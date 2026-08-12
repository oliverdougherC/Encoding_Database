import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { streamPacketEvidence } from '../dist/v7/artifacts.js';

const execFileAsync = promisify(execFile);
const repositoryRoot = resolve(process.cwd(), '..');

test('packaged client and authoritative server agree exactly on real artifact packet bytes', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'encodingdb-packet-agreement-'));
  t.after(async () => rm(directory, { recursive: true, force: true }));
  const artifact = join(directory, 'artifact.mkv');
  await execFileAsync('ffmpeg', [
    '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
    '-t', '1', '-an', '-c:v', 'mpeg4', '-q:v', '5', artifact,
  ]);

  const serverEvidence = await streamPacketEvidence(artifact);
  const { stdout } = await execFileAsync('python3', [
    '-c',
    'import json,sys; from client.media_evidence import probe_video_packet_evidence; print(json.dumps(probe_video_packet_evidence(sys.argv[1])))',
    artifact,
  ], { cwd: repositoryRoot });
  const clientEvidence = JSON.parse(stdout);

  assert.equal(clientEvidence.videoPayloadBytes, serverEvidence.bytes, 'packet-byte tolerance is exactly 0 bytes');
  assert.equal(clientEvidence.videoPacketCount, serverEvidence.packetCount);
  assert.ok(serverEvidence.bytes > 0);
  assert.ok(serverEvidence.packetCount > 0);
});
