-- CreateTable
CREATE TABLE "Benchmark" (
    "id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "cpuModel" TEXT NOT NULL,
    "gpuModel" TEXT,
    "ramGB" INTEGER NOT NULL,
    "os" TEXT NOT NULL,
    "codec" TEXT NOT NULL,
    "preset" TEXT NOT NULL,
    "fps" DOUBLE PRECISION NOT NULL,
    "vmaf" DOUBLE PRECISION,
    "fileSizeBytes" INTEGER NOT NULL,
    "notes" TEXT,

    CONSTRAINT "Benchmark_pkey" PRIMARY KEY ("id")
);
