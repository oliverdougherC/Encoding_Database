BEGIN;
-- Mutable projection dependencies are separate from immutable historical scores.
CREATE TABLE "DerivedResultGroupDependency" (
  "derivedResultId" TEXT NOT NULL REFERENCES "DerivedResult"(id) ON DELETE CASCADE,
  "physicalSourceId" TEXT NOT NULL,
  "campaignId" TEXT NOT NULL,
  "repetitionGroupId" TEXT NOT NULL,
  "invalidatedAt" TIMESTAMP(3),
  PRIMARY KEY ("derivedResultId", "physicalSourceId", "campaignId", "repetitionGroupId")
);
CREATE INDEX "DerivedResultGroupDependency_group_idx" ON "DerivedResultGroupDependency" ("physicalSourceId", "campaignId", "repetitionGroupId");
CREATE INDEX "DerivedResultGroupDependency_invalid_idx" ON "DerivedResultGroupDependency" ("derivedResultId") WHERE "invalidatedAt" IS NOT NULL;

CREATE FUNCTION encodingdb_lock_measurement_groups(groups JSONB) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE lock_key INTEGER;
BEGIN
  FOR lock_key IN SELECT DISTINCT hashtext(value::text) FROM jsonb_array_elements(coalesce(groups, '[]'::jsonb)) WHERE value->>0 IS NOT NULL AND value->>1 IS NOT NULL AND value->>2 IS NOT NULL ORDER BY 1
  LOOP PERFORM pg_advisory_xact_lock(714557, lock_key); END LOOP;
END $$;

CREATE FUNCTION encodingdb_invalidate_measurement_groups(groups JSONB) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE group_key JSONB;
BEGIN
  PERFORM encodingdb_lock_measurement_groups(groups);
  -- Equality probes retain the group index; a correlated JSON semijoin can scan
  -- every dependency on each arriving run even when only one group changed.
  FOR group_key IN SELECT DISTINCT value FROM jsonb_array_elements(coalesce(groups, '[]'::jsonb)) WHERE value->>0 IS NOT NULL AND value->>1 IS NOT NULL AND value->>2 IS NOT NULL
  LOOP
    UPDATE "DerivedResultGroupDependency" d SET "invalidatedAt" = coalesce(d."invalidatedAt", clock_timestamp() AT TIME ZONE 'UTC')
    WHERE d."physicalSourceId" = group_key->>0 AND d."campaignId" = group_key->>1 AND d."repetitionGroupId" = group_key->>2 AND d."invalidatedAt" IS NULL;
  END LOOP;
END $$;

CREATE FUNCTION encodingdb_groups_for_runs(ids TEXT[]) RETURNS JSONB LANGUAGE sql STABLE AS $$
  SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array("physicalSourceId", "campaignId", "repetitionGroupId")), '[]'::jsonb)
  FROM "BenchmarkRun" WHERE id = ANY(ids) AND "physicalSourceId" IS NOT NULL AND "campaignId" IS NOT NULL AND "repetitionGroupId" IS NOT NULL
$$;

CREATE FUNCTION encodingdb_invalidate_group_projection() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE before_row JSONB; after_row JSONB; groups JSONB; ignored TEXT[];
BEGIN
  IF TG_OP <> 'INSERT' THEN before_row = to_jsonb(OLD); END IF;
  IF TG_OP <> 'DELETE' THEN after_row = to_jsonb(NEW); END IF;
  CASE TG_TABLE_NAME
    WHEN 'BenchmarkRun' THEN
      ignored = ARRAY['createdAt','updatedAt','payloadHash','immutablePayloadHash','telemetry','telemetrySources','telemetryMissing','energyDomains','decodeBenchmark','ffmpegProgressTelemetry','clientQualityDebug','statusReason','decidedAt'];
      IF TG_OP = 'UPDATE' AND before_row - ignored IS NOT DISTINCT FROM after_row - ignored THEN RETURN NULL; END IF;
      groups = jsonb_build_array(jsonb_build_array(before_row->>'physicalSourceId',before_row->>'campaignId',before_row->>'repetitionGroupId'), jsonb_build_array(after_row->>'physicalSourceId',after_row->>'campaignId',after_row->>'repetitionGroupId'));
    WHEN 'QualityAnalysis' THEN
      ignored = ARRAY['updatedAt','leaseToken','leaseExpiresAt','attemptCount','maxAttempts','nextRetryAt','startedAt','completedAt','lastError','lastErrorAt','recomputePending','recomputeLastError'];
      IF TG_OP = 'UPDATE' AND before_row - ignored IS NOT DISTINCT FROM after_row - ignored THEN RETURN NULL; END IF;
      groups = encodingdb_groups_for_runs(ARRAY[before_row->>'benchmarkRunId', after_row->>'benchmarkRunId']);
    WHEN 'Artifact' THEN
      ignored = ARRAY['createdAt','updatedAt','stateReason','stateDetails','uploadedAt','verifiedAt','retainedAt','deletedAt'];
      IF TG_OP = 'UPDATE' AND before_row - ignored IS NOT DISTINCT FROM after_row - ignored THEN RETURN NULL; END IF;
      groups = encodingdb_groups_for_runs(ARRAY[before_row->>'benchmarkRunId', after_row->>'benchmarkRunId']);
    WHEN 'EvidenceReview' THEN
      groups = encodingdb_groups_for_runs(ARRAY[before_row->>'benchmarkRunId', after_row->>'benchmarkRunId']);
    WHEN 'BenchmarkProtocol' THEN
      IF before_row->'protocolVersion' IS NOT DISTINCT FROM after_row->'protocolVersion' AND before_row->'canonicalRecipeRules' IS NOT DISTINCT FROM after_row->'canonicalRecipeRules' THEN RETURN NULL; END IF;
      SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array("physicalSourceId","campaignId","repetitionGroupId")), '[]'::jsonb) INTO groups FROM "BenchmarkRun" WHERE "benchmarkProtocolId" = ANY(ARRAY[before_row->>'id',after_row->>'id']);
    WHEN 'TestClip' THEN
      IF (before_row->'sha256',before_row->'exactFrameCount',before_row->'exactDurationSeconds',before_row->'frameRateNumerator',before_row->'frameRateDenominator') IS NOT DISTINCT FROM (after_row->'sha256',after_row->'exactFrameCount',after_row->'exactDurationSeconds',after_row->'frameRateNumerator',after_row->'frameRateDenominator') THEN RETURN NULL; END IF;
      SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array("physicalSourceId","campaignId","repetitionGroupId")), '[]'::jsonb) INTO groups FROM "BenchmarkRun" WHERE "testClipId" = ANY(ARRAY[before_row->>'id',after_row->>'id']);
  END CASE;
  PERFORM encodingdb_invalidate_measurement_groups(groups);
  RETURN NULL;
END $$;
CREATE TRIGGER "BenchmarkRun_group_projection" AFTER INSERT OR UPDATE OR DELETE ON "BenchmarkRun" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();
CREATE TRIGGER "QualityAnalysis_group_projection" AFTER INSERT OR UPDATE OR DELETE ON "QualityAnalysis" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();
CREATE TRIGGER "Artifact_group_projection" AFTER INSERT OR UPDATE OR DELETE ON "Artifact" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();
CREATE TRIGGER "EvidenceReview_group_projection" AFTER INSERT ON "EvidenceReview" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();
CREATE TRIGGER "BenchmarkProtocol_group_projection" AFTER UPDATE ON "BenchmarkProtocol" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();
CREATE TRIGGER "TestClip_group_projection" AFTER UPDATE ON "TestClip" FOR EACH ROW EXECUTE FUNCTION encodingdb_invalidate_group_projection();

-- Existing certificates require one revalidated refresh. Original results stay intact.
INSERT INTO "DerivedResultGroupDependency" ("derivedResultId","physicalSourceId","campaignId","repetitionGroupId","invalidatedAt")
SELECT DISTINCT d.id, r."physicalSourceId", r."campaignId", r."repetitionGroupId", statement_timestamp() AT TIME ZONE 'UTC'
FROM "DerivedResult" d JOIN "DerivedResultMember" m ON m."derivedResultId" = d.id JOIN "BenchmarkRun" r ON r.id = m."benchmarkRunId"
WHERE d."evidenceSummary" ? 'measurementGroupSnapshot' AND r."physicalSourceId" IS NOT NULL AND r."campaignId" IS NOT NULL AND r."repetitionGroupId" IS NOT NULL;

COMMIT;
