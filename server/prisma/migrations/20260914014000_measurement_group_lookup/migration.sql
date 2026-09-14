-- Keep complete-group eligibility lookups bounded when many physical sources
-- share a reproducible campaign seed and repetition-group identifier.
CREATE INDEX "BenchmarkRun_measurement_group_idx"
ON "BenchmarkRun" ("physicalSourceId", "campaignId", "repetitionGroupId");
