-- Reliable client telemetry: coverage counts, raw diagnostics, and spool-safe fallback notes

-- Submission: raw per-run telemetry coverage and diagnostics
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "cpuSampleCount" INTEGER;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "gpuSampleCount" INTEGER;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegSampleCount" INTEGER;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "batterySampleCount" INTEGER;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "telemetrySources" TEXT;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "telemetryMissing" TEXT;

-- Benchmark: aggregated queryable coverage counts
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuSampleCount" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "gpuSampleCount" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegSampleCount" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batterySampleCount" DOUBLE PRECISION;

-- Benchmark aggregation helpers
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuSampleCountSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuSampleCountSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "gpuSampleCountSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "gpuSampleCountSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegSampleCountSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegSampleCountSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batterySampleCountSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batterySampleCountSum" DOUBLE PRECISION NOT NULL DEFAULT 0;

-- Compatibility backfill for raw submissions from note fallbacks.
CREATE OR REPLACE FUNCTION "_try_parse_jsonb"("input" TEXT)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN "input"::jsonb;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$;

WITH parsed AS (
  SELECT
    "id",
    "_try_parse_jsonb"(substring("notes" FROM 'telemetry=(\{.*?\})')) AS tele,
    "_try_parse_jsonb"(substring("notes" FROM 'telemetry_meta=(\{.*?\})')) AS tele_meta
  FROM "Submission"
  WHERE "notes" IS NOT NULL
    AND ("notes" LIKE '%telemetry={%' OR "notes" LIKE '%telemetry_meta={%')
)
UPDATE "Submission" s
SET
  "cpuSampleCount" = COALESCE(s."cpuSampleCount", CASE WHEN jsonb_typeof(p.tele->'cpuSampleCount') = 'number' THEN ROUND((p.tele->>'cpuSampleCount')::DOUBLE PRECISION)::INTEGER END),
  "gpuSampleCount" = COALESCE(s."gpuSampleCount", CASE WHEN jsonb_typeof(p.tele->'gpuSampleCount') = 'number' THEN ROUND((p.tele->>'gpuSampleCount')::DOUBLE PRECISION)::INTEGER END),
  "ffmpegSampleCount" = COALESCE(s."ffmpegSampleCount", CASE WHEN jsonb_typeof(p.tele->'ffmpegSampleCount') = 'number' THEN ROUND((p.tele->>'ffmpegSampleCount')::DOUBLE PRECISION)::INTEGER END),
  "batterySampleCount" = COALESCE(s."batterySampleCount", CASE WHEN jsonb_typeof(p.tele->'batterySampleCount') = 'number' THEN ROUND((p.tele->>'batterySampleCount')::DOUBLE PRECISION)::INTEGER END),
  "telemetrySources" = COALESCE(s."telemetrySources", CASE WHEN jsonb_typeof(p.tele_meta->'telemetrySources') = 'string' THEN LEFT(p.tele_meta->>'telemetrySources', 400) END),
  "telemetryMissing" = COALESCE(s."telemetryMissing", CASE WHEN jsonb_typeof(p.tele_meta->'telemetryMissing') = 'string' THEN LEFT(p.tele_meta->>'telemetryMissing', 400) END)
FROM parsed p
WHERE s."id" = p."id";
