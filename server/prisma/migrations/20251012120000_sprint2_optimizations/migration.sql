-- Sprint 2: S-08 composite index for the main query pattern
-- WHERE status='accepted' ORDER BY createdAt DESC

CREATE INDEX IF NOT EXISTS "Benchmark_status_createdAt_idx" ON "Benchmark"("status", "createdAt");
