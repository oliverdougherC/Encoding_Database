// A real, explicitly synthetic writer used only to measure backup quiescence.
import { PrismaClient } from '@prisma/client';
import { writeFile, rm } from 'node:fs/promises';
import { setTimeout } from 'node:timers/promises';
if (process.env.BACKUP_SCALE_ALLOW !== 'isolated-fixture-only') throw Error('Isolated fixture acknowledgement required');
const db = new PrismaClient();
let stopped = false;
process.on('SIGTERM', () => { stopped = true; });
process.on('SIGINT', () => { stopped = true; });
try {
  await rm('/tmp/backup-scale-ready', { force: true });
  const current = await db.$queryRawUnsafe('SELECT current_database() AS name');
  if (current[0]?.name !== 'backup_scale') throw Error('Refusing any non-fixture database');
  while (!stopped) {
    await db.$executeRawUnsafe('UPDATE "BackupScaleHeartbeat" SET ticks=ticks+1,"updatedAt"=NOW() WHERE id=1');
    await writeFile('/tmp/backup-scale-ready', 'ready');
    await setTimeout(1000);
  }
} finally { await db.$disconnect(); }
