-- Sprint 4: Add indexes for text search filtering on cpuModel and gpuModel
CREATE INDEX IF NOT EXISTS "Benchmark_cpuModel_idx" ON "Benchmark"("cpuModel");
CREATE INDEX IF NOT EXISTS "Benchmark_gpuModel_idx" ON "Benchmark"("gpuModel");
