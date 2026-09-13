-- Retain the exact authoritative bitrate evidence used by PL-v7 aggregation.
ALTER TABLE "QualityAnalysis"
  ADD COLUMN "videoPayloadBytes" INTEGER,
  ADD COLUMN "videoPacketCount" INTEGER,
  ADD COLUMN "measuredDurationSeconds" DOUBLE PRECISION,
  ADD COLUMN "bitrateMethod" TEXT;

-- A derived result is reproducible only when membership identifies the exact
-- immutable analysis record, not merely the run that may have many analyses.
ALTER TABLE "DerivedResultMember"
  ADD COLUMN "qualityAnalysisId" TEXT;

UPDATE "DerivedResultMember" AS member
SET "qualityAnalysisId" = (
  SELECT analysis."id"
  FROM "QualityAnalysis" AS analysis
  WHERE analysis."benchmarkRunId" = member."benchmarkRunId"
  ORDER BY analysis."createdAt" DESC, analysis."id" DESC
  LIMIT 1
);

DELETE FROM "DerivedResultMember" WHERE "qualityAnalysisId" IS NULL;

ALTER TABLE "DerivedResultMember"
  ALTER COLUMN "qualityAnalysisId" SET NOT NULL,
  ADD CONSTRAINT "DerivedResultMember_qualityAnalysisId_fkey"
    FOREIGN KEY ("qualityAnalysisId") REFERENCES "QualityAnalysis"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE;

DROP INDEX IF EXISTS "DerivedResultMember_derivedResultId_benchmarkRunId_key";
CREATE UNIQUE INDEX "DerivedResultMember_derivedResultId_qualityAnalysisId_key"
  ON "DerivedResultMember"("derivedResultId", "qualityAnalysisId");
CREATE INDEX "DerivedResultMember_qualityAnalysisId_idx"
  ON "DerivedResultMember"("qualityAnalysisId");
