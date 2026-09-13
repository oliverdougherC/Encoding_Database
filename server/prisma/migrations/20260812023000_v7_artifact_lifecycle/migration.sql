ALTER TYPE "ArtifactStorageState" RENAME VALUE 'FAILED' TO 'REJECTED';

ALTER TABLE "BenchmarkRun"
  ADD COLUMN "clientQualityDebug" JSONB;

ALTER TABLE "Artifact"
  ADD COLUMN "stateReason" TEXT,
  ADD COLUMN "stateDetails" JSONB,
  ADD COLUMN "uploadedAt" TIMESTAMP(3),
  ADD COLUMN "verifiedAt" TIMESTAMP(3),
  ADD COLUMN "retainedAt" TIMESTAMP(3),
  ADD COLUMN "deletedAt" TIMESTAMP(3);
