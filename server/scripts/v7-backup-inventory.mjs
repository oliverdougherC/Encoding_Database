#!/usr/bin/env node

import crypto from 'node:crypto';
import path from 'node:path';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { PrismaClient } from '@prisma/client';

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) args[argv[index].replace(/^--/, '')] = argv[index + 1];
  if (!['export', 'verify'].includes(args.mode) || !args['artifact-root'] || !args.inventory) {
    throw new Error('usage: --mode export|verify --artifact-root PATH --inventory PATH [--output PATH]');
  }
  if (args.mode === 'export' && !args.output) throw new Error('--output is required in export mode');
  return args;
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

async function databaseInventory(prisma) {
  const artifacts = await prisma.artifact.findMany({
    where: { storageState: { in: ['RETAINED', 'VERIFIED'] } },
    select: { id: true, benchmarkRunId: true, sha256: true, byteSize: true, storageKey: true, storageState: true },
    orderBy: { id: 'asc' },
  });
  const derivedMembers = await prisma.derivedResultMember.findMany({
    select: { id: true, benchmarkRunId: true, qualityAnalysisId: true },
    orderBy: { id: 'asc' },
  });
  return { artifacts, derivedMembers };
}

async function validateObjects(root, inventory) {
  const resolvedRoot = path.resolve(root);
  for (const artifact of inventory.artifacts) {
    if (!artifact.storageKey || !artifact.sha256 || artifact.byteSize == null) throw new Error(`artifact ${artifact.id} lacks retained identity`);
    const objectPath = path.resolve(resolvedRoot, artifact.storageKey);
    if (!objectPath.startsWith(`${resolvedRoot}${path.sep}`)) throw new Error(`artifact ${artifact.id} escapes storage root`);
    const objectStat = await stat(objectPath);
    if (objectStat.size !== artifact.byteSize) throw new Error(`artifact ${artifact.id} byte size mismatch`);
    if (await sha256File(objectPath) !== artifact.sha256) throw new Error(`artifact ${artifact.id} sha256 mismatch`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const prisma = new PrismaClient();
  try {
    const current = await databaseInventory(prisma);
    await validateObjects(args['artifact-root'], current);
    if (args.mode === 'export') {
      const inventory = {
        evidenceVersion: 'encodingdb-v7-backup-inventory/v1',
        createdAt: new Date().toISOString(),
        artifactCount: current.artifacts.length,
        derivedMemberCount: current.derivedMembers.length,
        ...current,
      };
      await writeFile(args.output, `${JSON.stringify(inventory, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
      process.stdout.write(`${JSON.stringify({ ok: true, artifactCount: inventory.artifactCount, derivedMemberCount: inventory.derivedMemberCount })}\n`);
      return;
    }
    const expected = JSON.parse(await readFile(args.inventory, 'utf8'));
    if (expected.evidenceVersion !== 'encodingdb-v7-backup-inventory/v1') throw new Error('unsupported backup inventory version');
    if (JSON.stringify(current.artifacts) !== JSON.stringify(expected.artifacts)) throw new Error('restored Artifact inventory differs from backup');
    if (JSON.stringify(current.derivedMembers) !== JSON.stringify(expected.derivedMembers)) throw new Error('restored DerivedResultMember inventory differs from backup');
    process.stdout.write(`${JSON.stringify({ ok: true, artifactCount: current.artifacts.length, derivedMemberCount: current.derivedMembers.length })}\n`);
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((error) => {
  process.stderr.write(`v7 backup inventory failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
