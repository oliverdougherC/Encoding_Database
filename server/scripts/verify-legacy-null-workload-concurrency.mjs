import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();
const marker = `ci-null-workload-${process.pid}-${Date.now()}`;
const identity = {
  cpuModel: marker,
  gpuModel: '',
  ramGB: 1,
  os: 'ci',
  codec: 'libx264',
  preset: 'medium',
  crf: 24,
  contentClass: 'mixed',
  resolution: '1080p',
  passes: 1,
  workloadId: null,
};

try {
  const attempts = await Promise.allSettled(
    Array.from({ length: 8 }, (_, index) => prisma.benchmark.create({
      data: {
        ...identity,
        fps: 1 + index,
        fileSizeBytes: 1_000 + index,
      },
    })),
  );
  const accepted = attempts.filter((attempt) => attempt.status === 'fulfilled');
  const rejected = attempts.filter((attempt) => (
    attempt.status === 'rejected'
    && attempt.reason?.code === 'P2002'
  ));
  const retained = await prisma.benchmark.count({ where: { cpuModel: marker } });
  if (accepted.length !== 1 || rejected.length !== 7 || retained !== 1) {
    throw new Error(
      `null-workload uniqueness failed: accepted=${accepted.length} P2002=${rejected.length} retained=${retained}`,
    );
  }
  process.stdout.write('Concurrent legacy null-workload identity retained exactly one row.\n');
} finally {
  await prisma.benchmark.deleteMany({ where: { cpuModel: marker } });
  await prisma.$disconnect();
}
