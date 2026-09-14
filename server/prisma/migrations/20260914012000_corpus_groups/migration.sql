-- Rebuildable public summaries. Immutable source evidence remains authoritative.
CREATE TABLE "PublicCorpusGroup" (
  id TEXT PRIMARY KEY, "baseKey" TEXT NOT NULL, "createdAt" TIMESTAMP(3) NOT NULL,
  "cpuModel" TEXT NOT NULL, "gpuModel" TEXT, "encoderName" TEXT NOT NULL, preset TEXT,
  "benchmarkProtocolId" TEXT NOT NULL, "workloadId" TEXT NOT NULL, "recipeId" TEXT NOT NULL,
  "environmentId" TEXT NOT NULL, "metricModelId" TEXT NOT NULL,
  "runId" TEXT NOT NULL, "artifactId" TEXT NOT NULL, "analysisId" TEXT NOT NULL,
  accepted INTEGER NOT NULL, suspect INTEGER NOT NULL, repetitions INTEGER NOT NULL,
  "independentSources" INTEGER NOT NULL, machines INTEGER NOT NULL, "artifactState" TEXT NOT NULL,
  fps DOUBLE PRECISION, "sourceFps" DOUBLE PRECISION, vmaf DOUBLE PRECISION, "vmafP5" DOUBLE PRECISION,
  "videoBitrateBps" DOUBLE PRECISION, "fileSizeBytes" DOUBLE PRECISION, "acceptedMembershipHash" TEXT NOT NULL
);
CREATE INDEX "PublicCorpusGroup_baseKey_idx" ON "PublicCorpusGroup"("baseKey");
CREATE INDEX "PublicCorpusGroup_createdAt_idx" ON "PublicCorpusGroup"("createdAt" DESC, id);
CREATE INDEX "PublicCorpusGroup_fps_idx" ON "PublicCorpusGroup"(fps DESC NULLS LAST, id);
CREATE INDEX "PublicCorpusGroup_vmaf_idx" ON "PublicCorpusGroup"(vmaf DESC NULLS LAST, id);
CREATE TABLE "PublicCorpusDirtyGroup" (
  "baseKey" TEXT PRIMARY KEY, "benchmarkProtocolId" TEXT NOT NULL, "workloadId" TEXT NOT NULL,
  "recipeId" TEXT NOT NULL, "environmentId" TEXT NOT NULL, "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE FUNCTION "queuePublicCorpusIdentity"(protocol TEXT, workload TEXT, recipe TEXT, environment TEXT) RETURNS VOID
LANGUAGE SQL AS $$
  INSERT INTO "PublicCorpusDirtyGroup" ("baseKey", "benchmarkProtocolId", "workloadId", "recipeId", "environmentId")
  VALUES (concat_ws('::', protocol, workload, recipe, environment), protocol, workload, recipe, environment)
  ON CONFLICT ("baseKey") DO UPDATE SET "updatedAt" = clock_timestamp();
$$;
CREATE FUNCTION "dirtyPublicCorpusRun"() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    PERFORM "queuePublicCorpusIdentity"(OLD."benchmarkProtocolId", OLD."workloadId", OLD."recipeId", OLD."environmentId");
  END IF;
  IF TG_OP <> 'DELETE' THEN
    PERFORM "queuePublicCorpusIdentity"(NEW."benchmarkProtocolId", NEW."workloadId", NEW."recipeId", NEW."environmentId");
  END IF;
  RETURN NULL;
END; $$;
CREATE TRIGGER "corpus_run_insert_delete" AFTER INSERT OR DELETE ON "BenchmarkRun" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusRun"();
CREATE TRIGGER "corpus_run_update" AFTER UPDATE OF status, "encodeFps", "sourceFps", "physicalSourceId", "repetitionGroupId", "benchmarkProtocolId", "workloadId", "recipeId", "environmentId" ON "BenchmarkRun" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusRun"();
CREATE FUNCTION "dirtyPublicCorpusEvidence"() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT "benchmarkProtocolId", "workloadId", "recipeId", "environmentId" FROM "BenchmarkRun"
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD."benchmarkRunId" ELSE NEW."benchmarkRunId" END
  LOOP PERFORM "queuePublicCorpusIdentity"(r."benchmarkProtocolId", r."workloadId", r."recipeId", r."environmentId"); END LOOP;
  RETURN NULL;
END; $$;
CREATE TRIGGER "corpus_artifact_change" AFTER INSERT OR DELETE OR UPDATE OF "storageState", "byteSize", sha256 ON "Artifact" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusEvidence"();
CREATE TRIGGER "corpus_analysis_change" AFTER INSERT OR DELETE OR UPDATE OF status, "artifactId", "metricModelId", "analysisWorkerVersion", "vmafMean", "vmafP5", "videoBitrateBps", "fileSizeBytes" ON "QualityAnalysis" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusEvidence"();
CREATE TRIGGER "corpus_review_change" AFTER INSERT ON "EvidenceReview" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusEvidence"();
CREATE FUNCTION "dirtyPublicCorpusDimension"() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT DISTINCT "benchmarkProtocolId", "workloadId", "recipeId", "environmentId" FROM "BenchmarkRun"
    WHERE (TG_TABLE_NAME = 'BenchmarkProtocol' AND "benchmarkProtocolId" = NEW.id)
      OR (TG_TABLE_NAME = 'Recipe' AND "recipeId" = NEW.id)
      OR (TG_TABLE_NAME = 'Environment' AND "environmentId" = NEW.id)
  LOOP PERFORM "queuePublicCorpusIdentity"(r."benchmarkProtocolId", r."workloadId", r."recipeId", r."environmentId"); END LOOP;
  RETURN NULL;
END; $$;
CREATE TRIGGER "corpus_protocol_change" AFTER UPDATE OF state, "metricWorkerVersion" ON "BenchmarkProtocol" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusDimension"();
CREATE TRIGGER "corpus_recipe_change" AFTER UPDATE ON "Recipe" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusDimension"();
CREATE TRIGGER "corpus_environment_change" AFTER UPDATE ON "Environment" FOR EACH ROW EXECUTE FUNCTION "dirtyPublicCorpusDimension"();
INSERT INTO "PublicCorpusDirtyGroup" ("baseKey", "benchmarkProtocolId", "workloadId", "recipeId", "environmentId")
SELECT DISTINCT concat_ws('::', "benchmarkProtocolId", "workloadId", "recipeId", "environmentId"), "benchmarkProtocolId", "workloadId", "recipeId", "environmentId" FROM "BenchmarkRun";
