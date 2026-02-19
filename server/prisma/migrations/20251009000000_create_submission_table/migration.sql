-- Create Submission table (required by API + later migrations)
CREATE TABLE IF NOT EXISTS "Submission" (
    "id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    "cpuModel" TEXT NOT NULL,
    "gpuModel" TEXT,
    "ramGB" INTEGER NOT NULL,
    "os" TEXT NOT NULL,

    "codec" TEXT NOT NULL,
    "preset" TEXT NOT NULL,
    "crf" INTEGER,

    "fps" DOUBLE PRECISION NOT NULL,
    "vmaf" DOUBLE PRECISION,
    "fileSizeBytes" INTEGER NOT NULL,
    "notes" TEXT,

    "status" TEXT NOT NULL DEFAULT 'pending',
    "qualityScore" DOUBLE PRECISION,

    "ffmpegVersion" TEXT,
    "encoderName" TEXT,
    "clientVersion" TEXT,
    "inputHash" TEXT,
    "runMs" INTEGER,

    "payloadHash" TEXT,

    CONSTRAINT "Submission_pkey" PRIMARY KEY ("id")
);

-- Idempotency and basic query indexes
CREATE UNIQUE INDEX IF NOT EXISTS "Submission_payloadHash_key" ON "Submission"("payloadHash");
CREATE INDEX IF NOT EXISTS "Submission_createdAt_idx" ON "Submission"("createdAt");
CREATE INDEX IF NOT EXISTS "Submission_status_idx" ON "Submission"("status");
CREATE INDEX IF NOT EXISTS "Submission_codec_idx" ON "Submission"("codec");
