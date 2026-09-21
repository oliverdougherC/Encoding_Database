-- Preserve historical integer values exactly while accepting the corrected
-- client's monotonic sub-millisecond process interval in protocol 7.1.
ALTER TABLE "BenchmarkRun" ALTER COLUMN "encodeWallTimeMs" TYPE DOUBLE PRECISION;
