-- CreateEnum
CREATE TYPE "EvidenceReviewDecision" AS ENUM ('EXPECTED', 'REJECT', 'INVESTIGATE', 'REVOKE');

-- AlterTable
ALTER TABLE "Environment" ADD COLUMN     "executionArchitecture" TEXT,
ADD COLUMN     "runtimeIdentity" JSONB,
ADD COLUMN     "selectedDeviceEvidence" JSONB,
ADD COLUMN     "translationMode" TEXT;

-- AlterTable
ALTER TABLE "BenchmarkRun" ADD COLUMN     "encodeTimerBoundary" TEXT,
ADD COLUMN     "immutablePayloadHash" TEXT,
ADD COLUMN     "physicalSourceId" TEXT;

-- AlterTable
ALTER TABLE "Artifact" ADD COLUMN     "reservationExpiresAt" TIMESTAMP(3),
ADD COLUMN     "uploadLeaseExpiresAt" TIMESTAMP(3),
ADD COLUMN     "uploadLeaseToken" TEXT;

-- AlterTable
ALTER TABLE "QualityAnalysis" ADD COLUMN     "recomputeLastError" TEXT,
ADD COLUMN     "recomputePending" BOOLEAN NOT NULL DEFAULT false;

-- CreateTable
CREATE TABLE "EvidenceReview" (
    "id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "analysisId" TEXT NOT NULL,
    "benchmarkRunId" TEXT NOT NULL,
    "artifactId" TEXT NOT NULL,
    "artifactSha256" TEXT NOT NULL,
    "metricModelId" TEXT NOT NULL,
    "analysisWorkerVersion" TEXT NOT NULL,
    "reviewerId" TEXT NOT NULL,
    "rationale" TEXT NOT NULL,
    "evidenceLinks" JSONB NOT NULL,
    "decision" "EvidenceReviewDecision" NOT NULL,
    "supersedesId" TEXT,

    CONSTRAINT "EvidenceReview_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "EvidenceReview_supersedesId_key" ON "EvidenceReview"("supersedesId");

-- CreateIndex
CREATE INDEX "EvidenceReview_analysisId_createdAt_id_idx" ON "EvidenceReview"("analysisId", "createdAt", "id");

-- CreateIndex
CREATE INDEX "EvidenceReview_benchmarkRunId_createdAt_idx" ON "EvidenceReview"("benchmarkRunId", "createdAt");

-- CreateIndex
CREATE INDEX "Artifact_storageState_id_idx" ON "Artifact"("storageState", "id");

-- CreateIndex
CREATE INDEX "Artifact_storageState_reservationExpiresAt_idx" ON "Artifact"("storageState", "reservationExpiresAt");

-- CreateIndex
CREATE INDEX "Artifact_uploadLeaseExpiresAt_idx" ON "Artifact"("uploadLeaseExpiresAt");

-- CreateIndex
CREATE INDEX "QualityAnalysis_status_completedAt_idx" ON "QualityAnalysis"("status", "completedAt");

-- CreateIndex
CREATE INDEX "QualityAnalysis_recomputePending_idx" ON "QualityAnalysis"("recomputePending");

-- AddForeignKey
ALTER TABLE "EvidenceReview" ADD CONSTRAINT "EvidenceReview_analysisId_fkey" FOREIGN KEY ("analysisId") REFERENCES "QualityAnalysis"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EvidenceReview" ADD CONSTRAINT "EvidenceReview_benchmarkRunId_fkey" FOREIGN KEY ("benchmarkRunId") REFERENCES "BenchmarkRun"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EvidenceReview" ADD CONSTRAINT "EvidenceReview_artifactId_fkey" FOREIGN KEY ("artifactId") REFERENCES "Artifact"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EvidenceReview" ADD CONSTRAINT "EvidenceReview_supersedesId_fkey" FOREIGN KEY ("supersedesId") REFERENCES "EvidenceReview"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- Reviews are immutable evidence. Corrections append a superseding decision.
CREATE FUNCTION encodingdb_review_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'EvidenceReview is append-only; append a superseding decision';
END;
$$;
CREATE TRIGGER evidence_review_append_only
BEFORE UPDATE OR DELETE ON "EvidenceReview"
FOR EACH ROW EXECUTE FUNCTION encodingdb_review_append_only();
