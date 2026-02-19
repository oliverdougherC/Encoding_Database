-- Sprint 7: Extended telemetry columns (queryable)

-- Submission: raw per-run telemetry
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "gpuTempMaxC" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "cpuFreqAvgMHz" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "cpuTempMaxC" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilAvg" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilMax" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegReadMB" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegWriteMB" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "ffmpegCpuTimeS" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "batteryPercentStart" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "batteryPercentEnd" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "batteryPercentDrop" DOUBLE PRECISION;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "powerSource" TEXT;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "sampleCount" INTEGER;
ALTER TABLE "Submission" ADD COLUMN IF NOT EXISTS "monitorDurationMs" INTEGER;

-- Benchmark: aggregated/derived telemetry view
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "gpuTempMaxC" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuFreqAvgMHz" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuTempMaxC" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilAvg" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilMax" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegReadMB" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegWriteMB" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuTimeS" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryPercentStart" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryPercentEnd" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryPercentDrop" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "powerSource" TEXT;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "sampleCount" DOUBLE PRECISION;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "monitorDurationMs" DOUBLE PRECISION;

-- Benchmark aggregation helpers
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuFreqSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "cpuFreqSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuUtilSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegReadSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegReadSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegWriteSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegWriteSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuTimeSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "ffmpegCpuTimeSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryStartSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryStartSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryEndSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryEndSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryDropSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "batteryDropSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "sampleCountSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "sampleCountSum" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "monitorDurationSamples" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Benchmark" ADD COLUMN IF NOT EXISTS "monitorDurationSum" DOUBLE PRECISION NOT NULL DEFAULT 0;

-- Compatibility backfill: promote telemetry JSON from notes into first-class columns.
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

WITH parsed_submission AS (
  SELECT
    "id",
    "_try_parse_jsonb"(substring("notes" FROM 'telemetry=(\{.*\})')) AS tele
  FROM "Submission"
  WHERE "notes" IS NOT NULL
    AND "notes" LIKE '%telemetry={%'
)
UPDATE "Submission" s
SET
  "gpuUtilAvg" = COALESCE(s."gpuUtilAvg", CASE WHEN jsonb_typeof(ps.tele->'gpuUtilAvg') = 'number' THEN (ps.tele->>'gpuUtilAvg')::DOUBLE PRECISION END),
  "gpuPowerAvgW" = COALESCE(s."gpuPowerAvgW", CASE WHEN jsonb_typeof(ps.tele->'gpuPowerAvgW') = 'number' THEN (ps.tele->>'gpuPowerAvgW')::DOUBLE PRECISION END),
  "gpuMemPeakMB" = COALESCE(s."gpuMemPeakMB", CASE WHEN jsonb_typeof(ps.tele->'gpuMemPeakMB') = 'number' THEN (ps.tele->>'gpuMemPeakMB')::DOUBLE PRECISION END),
  "cpuUtilAvg" = COALESCE(s."cpuUtilAvg", CASE WHEN jsonb_typeof(ps.tele->'cpuUtilAvg') = 'number' THEN (ps.tele->>'cpuUtilAvg')::DOUBLE PRECISION END),
  "cpuUtilMax" = COALESCE(s."cpuUtilMax", CASE WHEN jsonb_typeof(ps.tele->'cpuUtilMax') = 'number' THEN (ps.tele->>'cpuUtilMax')::DOUBLE PRECISION END),
  "peakMemoryMB" = COALESCE(s."peakMemoryMB", CASE WHEN jsonb_typeof(ps.tele->'peakMemoryMB') = 'number' THEN (ps.tele->>'peakMemoryMB')::DOUBLE PRECISION END),
  "thermalThrottle" = COALESCE(s."thermalThrottle", CASE WHEN jsonb_typeof(ps.tele->'thermalThrottle') = 'boolean' THEN (ps.tele->>'thermalThrottle')::BOOLEAN END),
  "gpuTempMaxC" = COALESCE(s."gpuTempMaxC", CASE WHEN jsonb_typeof(ps.tele->'gpuTempMaxC') = 'number' THEN (ps.tele->>'gpuTempMaxC')::DOUBLE PRECISION END),
  "cpuFreqAvgMHz" = COALESCE(s."cpuFreqAvgMHz", CASE WHEN jsonb_typeof(ps.tele->'cpuFreqAvgMHz') = 'number' THEN (ps.tele->>'cpuFreqAvgMHz')::DOUBLE PRECISION END),
  "cpuTempMaxC" = COALESCE(s."cpuTempMaxC", CASE WHEN jsonb_typeof(ps.tele->'cpuTempMaxC') = 'number' THEN (ps.tele->>'cpuTempMaxC')::DOUBLE PRECISION END),
  "ffmpegCpuUtilAvg" = COALESCE(s."ffmpegCpuUtilAvg", CASE WHEN jsonb_typeof(ps.tele->'ffmpegCpuUtilAvg') = 'number' THEN (ps.tele->>'ffmpegCpuUtilAvg')::DOUBLE PRECISION END),
  "ffmpegCpuUtilMax" = COALESCE(s."ffmpegCpuUtilMax", CASE WHEN jsonb_typeof(ps.tele->'ffmpegCpuUtilMax') = 'number' THEN (ps.tele->>'ffmpegCpuUtilMax')::DOUBLE PRECISION END),
  "ffmpegReadMB" = COALESCE(s."ffmpegReadMB", CASE WHEN jsonb_typeof(ps.tele->'ffmpegReadMB') = 'number' THEN (ps.tele->>'ffmpegReadMB')::DOUBLE PRECISION END),
  "ffmpegWriteMB" = COALESCE(s."ffmpegWriteMB", CASE WHEN jsonb_typeof(ps.tele->'ffmpegWriteMB') = 'number' THEN (ps.tele->>'ffmpegWriteMB')::DOUBLE PRECISION END),
  "ffmpegCpuTimeS" = COALESCE(s."ffmpegCpuTimeS", CASE WHEN jsonb_typeof(ps.tele->'ffmpegCpuTimeS') = 'number' THEN (ps.tele->>'ffmpegCpuTimeS')::DOUBLE PRECISION END),
  "batteryPercentStart" = COALESCE(s."batteryPercentStart", CASE WHEN jsonb_typeof(ps.tele->'batteryPercentStart') = 'number' THEN (ps.tele->>'batteryPercentStart')::DOUBLE PRECISION END),
  "batteryPercentEnd" = COALESCE(s."batteryPercentEnd", CASE WHEN jsonb_typeof(ps.tele->'batteryPercentEnd') = 'number' THEN (ps.tele->>'batteryPercentEnd')::DOUBLE PRECISION END),
  "batteryPercentDrop" = COALESCE(s."batteryPercentDrop", CASE WHEN jsonb_typeof(ps.tele->'batteryPercentDrop') = 'number' THEN (ps.tele->>'batteryPercentDrop')::DOUBLE PRECISION END),
  "powerSource" = COALESCE(s."powerSource", CASE WHEN (ps.tele->>'powerSource') IN ('ac', 'battery') THEN ps.tele->>'powerSource' END),
  "sampleCount" = COALESCE(s."sampleCount", CASE WHEN jsonb_typeof(ps.tele->'sampleCount') = 'number' THEN ROUND((ps.tele->>'sampleCount')::DOUBLE PRECISION)::INTEGER END),
  "monitorDurationMs" = COALESCE(s."monitorDurationMs", CASE WHEN jsonb_typeof(ps.tele->'monitorDurationMs') = 'number' THEN ROUND((ps.tele->>'monitorDurationMs')::DOUBLE PRECISION)::INTEGER END)
FROM parsed_submission ps
WHERE s."id" = ps."id"
  AND ps.tele IS NOT NULL;

WITH parsed_benchmark AS (
  SELECT
    "id",
    "_try_parse_jsonb"(substring("notes" FROM 'telemetry=(\{.*\})')) AS tele
  FROM "Benchmark"
  WHERE "notes" IS NOT NULL
    AND "notes" LIKE '%telemetry={%'
)
UPDATE "Benchmark" b
SET
  "gpuUtilAvg" = COALESCE(b."gpuUtilAvg", CASE WHEN jsonb_typeof(pb.tele->'gpuUtilAvg') = 'number' THEN (pb.tele->>'gpuUtilAvg')::DOUBLE PRECISION END),
  "gpuPowerAvgW" = COALESCE(b."gpuPowerAvgW", CASE WHEN jsonb_typeof(pb.tele->'gpuPowerAvgW') = 'number' THEN (pb.tele->>'gpuPowerAvgW')::DOUBLE PRECISION END),
  "gpuMemPeakMB" = COALESCE(b."gpuMemPeakMB", CASE WHEN jsonb_typeof(pb.tele->'gpuMemPeakMB') = 'number' THEN (pb.tele->>'gpuMemPeakMB')::DOUBLE PRECISION END),
  "cpuUtilAvg" = COALESCE(b."cpuUtilAvg", CASE WHEN jsonb_typeof(pb.tele->'cpuUtilAvg') = 'number' THEN (pb.tele->>'cpuUtilAvg')::DOUBLE PRECISION END),
  "cpuUtilMax" = COALESCE(b."cpuUtilMax", CASE WHEN jsonb_typeof(pb.tele->'cpuUtilMax') = 'number' THEN (pb.tele->>'cpuUtilMax')::DOUBLE PRECISION END),
  "peakMemoryMB" = COALESCE(b."peakMemoryMB", CASE WHEN jsonb_typeof(pb.tele->'peakMemoryMB') = 'number' THEN (pb.tele->>'peakMemoryMB')::DOUBLE PRECISION END),
  "thermalThrottle" = COALESCE(b."thermalThrottle", CASE WHEN jsonb_typeof(pb.tele->'thermalThrottle') = 'boolean' THEN (pb.tele->>'thermalThrottle')::BOOLEAN END),
  "gpuTempMaxC" = COALESCE(b."gpuTempMaxC", CASE WHEN jsonb_typeof(pb.tele->'gpuTempMaxC') = 'number' THEN (pb.tele->>'gpuTempMaxC')::DOUBLE PRECISION END),
  "cpuFreqAvgMHz" = COALESCE(b."cpuFreqAvgMHz", CASE WHEN jsonb_typeof(pb.tele->'cpuFreqAvgMHz') = 'number' THEN (pb.tele->>'cpuFreqAvgMHz')::DOUBLE PRECISION END),
  "cpuTempMaxC" = COALESCE(b."cpuTempMaxC", CASE WHEN jsonb_typeof(pb.tele->'cpuTempMaxC') = 'number' THEN (pb.tele->>'cpuTempMaxC')::DOUBLE PRECISION END),
  "ffmpegCpuUtilAvg" = COALESCE(b."ffmpegCpuUtilAvg", CASE WHEN jsonb_typeof(pb.tele->'ffmpegCpuUtilAvg') = 'number' THEN (pb.tele->>'ffmpegCpuUtilAvg')::DOUBLE PRECISION END),
  "ffmpegCpuUtilMax" = COALESCE(b."ffmpegCpuUtilMax", CASE WHEN jsonb_typeof(pb.tele->'ffmpegCpuUtilMax') = 'number' THEN (pb.tele->>'ffmpegCpuUtilMax')::DOUBLE PRECISION END),
  "ffmpegReadMB" = COALESCE(b."ffmpegReadMB", CASE WHEN jsonb_typeof(pb.tele->'ffmpegReadMB') = 'number' THEN (pb.tele->>'ffmpegReadMB')::DOUBLE PRECISION END),
  "ffmpegWriteMB" = COALESCE(b."ffmpegWriteMB", CASE WHEN jsonb_typeof(pb.tele->'ffmpegWriteMB') = 'number' THEN (pb.tele->>'ffmpegWriteMB')::DOUBLE PRECISION END),
  "ffmpegCpuTimeS" = COALESCE(b."ffmpegCpuTimeS", CASE WHEN jsonb_typeof(pb.tele->'ffmpegCpuTimeS') = 'number' THEN (pb.tele->>'ffmpegCpuTimeS')::DOUBLE PRECISION END),
  "batteryPercentStart" = COALESCE(b."batteryPercentStart", CASE WHEN jsonb_typeof(pb.tele->'batteryPercentStart') = 'number' THEN (pb.tele->>'batteryPercentStart')::DOUBLE PRECISION END),
  "batteryPercentEnd" = COALESCE(b."batteryPercentEnd", CASE WHEN jsonb_typeof(pb.tele->'batteryPercentEnd') = 'number' THEN (pb.tele->>'batteryPercentEnd')::DOUBLE PRECISION END),
  "batteryPercentDrop" = COALESCE(b."batteryPercentDrop", CASE WHEN jsonb_typeof(pb.tele->'batteryPercentDrop') = 'number' THEN (pb.tele->>'batteryPercentDrop')::DOUBLE PRECISION END),
  "powerSource" = COALESCE(b."powerSource", CASE WHEN (pb.tele->>'powerSource') IN ('ac', 'battery') THEN pb.tele->>'powerSource' END),
  "sampleCount" = COALESCE(b."sampleCount", CASE WHEN jsonb_typeof(pb.tele->'sampleCount') = 'number' THEN (pb.tele->>'sampleCount')::DOUBLE PRECISION END),
  "monitorDurationMs" = COALESCE(b."monitorDurationMs", CASE WHEN jsonb_typeof(pb.tele->'monitorDurationMs') = 'number' THEN (pb.tele->>'monitorDurationMs')::DOUBLE PRECISION END)
FROM parsed_benchmark pb
WHERE b."id" = pb."id"
  AND pb.tele IS NOT NULL;

-- Refresh benchmark aggregate helper columns from accepted submissions.
WITH agg AS (
  SELECT
    "cpuModel",
    "gpuModel",
    "ramGB",
    "os",
    "codec",
    "preset",
    "crf",
    "contentClass",
    "resolution",
    "passes",
    COUNT(*)::INTEGER AS samples,
    COALESCE(SUM("fps"), 0)::DOUBLE PRECISION AS fps_sum,
    COALESCE(SUM("fileSizeBytes"::DOUBLE PRECISION), 0)::DOUBLE PRECISION AS file_size_sum,
    COUNT("vmaf")::INTEGER AS vmaf_samples,
    COALESCE(SUM("vmaf"), 0)::DOUBLE PRECISION AS vmaf_sum,
    COUNT("ssim")::INTEGER AS ssim_samples,
    COALESCE(SUM("ssim"), 0)::DOUBLE PRECISION AS ssim_sum,
    COUNT("psnr")::INTEGER AS psnr_samples,
    COALESCE(SUM("psnr"), 0)::DOUBLE PRECISION AS psnr_sum,
    COUNT("gpuUtilAvg")::INTEGER AS gpu_util_samples,
    COALESCE(SUM("gpuUtilAvg"), 0)::DOUBLE PRECISION AS gpu_util_sum,
    COUNT("gpuPowerAvgW")::INTEGER AS gpu_power_samples,
    COALESCE(SUM("gpuPowerAvgW"), 0)::DOUBLE PRECISION AS gpu_power_sum,
    COUNT("cpuUtilAvg")::INTEGER AS cpu_util_samples,
    COALESCE(SUM("cpuUtilAvg"), 0)::DOUBLE PRECISION AS cpu_util_sum,
    MAX("peakMemoryMB")::DOUBLE PRECISION AS peak_memory_max,
    BOOL_OR(COALESCE("thermalThrottle", FALSE)) AS thermal_throttle_any,
    MAX("gpuTempMaxC")::DOUBLE PRECISION AS gpu_temp_max,
    COUNT("cpuFreqAvgMHz")::INTEGER AS cpu_freq_samples,
    COALESCE(SUM("cpuFreqAvgMHz"), 0)::DOUBLE PRECISION AS cpu_freq_sum,
    MAX("cpuTempMaxC")::DOUBLE PRECISION AS cpu_temp_max,
    COUNT("ffmpegCpuUtilAvg")::INTEGER AS ffmpeg_cpu_avg_samples,
    COALESCE(SUM("ffmpegCpuUtilAvg"), 0)::DOUBLE PRECISION AS ffmpeg_cpu_avg_sum,
    MAX("ffmpegCpuUtilMax")::DOUBLE PRECISION AS ffmpeg_cpu_max,
    COUNT("ffmpegReadMB")::INTEGER AS ffmpeg_read_samples,
    COALESCE(SUM("ffmpegReadMB"), 0)::DOUBLE PRECISION AS ffmpeg_read_sum,
    COUNT("ffmpegWriteMB")::INTEGER AS ffmpeg_write_samples,
    COALESCE(SUM("ffmpegWriteMB"), 0)::DOUBLE PRECISION AS ffmpeg_write_sum,
    COUNT("ffmpegCpuTimeS")::INTEGER AS ffmpeg_cpu_time_samples,
    COALESCE(SUM("ffmpegCpuTimeS"), 0)::DOUBLE PRECISION AS ffmpeg_cpu_time_sum,
    COUNT("batteryPercentStart")::INTEGER AS battery_start_samples,
    COALESCE(SUM("batteryPercentStart"), 0)::DOUBLE PRECISION AS battery_start_sum,
    COUNT("batteryPercentEnd")::INTEGER AS battery_end_samples,
    COALESCE(SUM("batteryPercentEnd"), 0)::DOUBLE PRECISION AS battery_end_sum,
    COUNT("batteryPercentDrop")::INTEGER AS battery_drop_samples,
    COALESCE(SUM("batteryPercentDrop"), 0)::DOUBLE PRECISION AS battery_drop_sum,
    COUNT("sampleCount")::INTEGER AS sample_count_samples,
    COALESCE(SUM("sampleCount"::DOUBLE PRECISION), 0)::DOUBLE PRECISION AS sample_count_sum,
    COUNT("monitorDurationMs")::INTEGER AS monitor_duration_samples,
    COALESCE(SUM("monitorDurationMs"::DOUBLE PRECISION), 0)::DOUBLE PRECISION AS monitor_duration_sum,
    (array_agg("powerSource" ORDER BY "createdAt" DESC) FILTER (WHERE "powerSource" IS NOT NULL))[1] AS latest_power_source
  FROM "Submission"
  WHERE "status" = 'accepted'
  GROUP BY
    "cpuModel",
    "gpuModel",
    "ramGB",
    "os",
    "codec",
    "preset",
    "crf",
    "contentClass",
    "resolution",
    "passes"
)
UPDATE "Benchmark" b
SET
  "samples" = agg.samples,
  "fpsSum" = agg.fps_sum,
  "fileSizeSum" = agg.file_size_sum,
  "vmafSamples" = agg.vmaf_samples,
  "vmafSum" = agg.vmaf_sum,
  "ssimSamples" = agg.ssim_samples,
  "ssimSum" = agg.ssim_sum,
  "psnrSamples" = agg.psnr_samples,
  "psnrSum" = agg.psnr_sum,
  "gpuUtilSamples" = agg.gpu_util_samples,
  "gpuUtilSum" = agg.gpu_util_sum,
  "gpuPowerSamples" = agg.gpu_power_samples,
  "gpuPowerSum" = agg.gpu_power_sum,
  "cpuUtilSamples" = agg.cpu_util_samples,
  "cpuUtilSum" = agg.cpu_util_sum,
  "peakMemoryMax" = agg.peak_memory_max,
  "cpuFreqSamples" = agg.cpu_freq_samples,
  "cpuFreqSum" = agg.cpu_freq_sum,
  "ffmpegCpuUtilSamples" = agg.ffmpeg_cpu_avg_samples,
  "ffmpegCpuUtilSum" = agg.ffmpeg_cpu_avg_sum,
  "ffmpegReadSamples" = agg.ffmpeg_read_samples,
  "ffmpegReadSum" = agg.ffmpeg_read_sum,
  "ffmpegWriteSamples" = agg.ffmpeg_write_samples,
  "ffmpegWriteSum" = agg.ffmpeg_write_sum,
  "ffmpegCpuTimeSamples" = agg.ffmpeg_cpu_time_samples,
  "ffmpegCpuTimeSum" = agg.ffmpeg_cpu_time_sum,
  "batteryStartSamples" = agg.battery_start_samples,
  "batteryStartSum" = agg.battery_start_sum,
  "batteryEndSamples" = agg.battery_end_samples,
  "batteryEndSum" = agg.battery_end_sum,
  "batteryDropSamples" = agg.battery_drop_samples,
  "batteryDropSum" = agg.battery_drop_sum,
  "sampleCountSamples" = agg.sample_count_samples,
  "sampleCountSum" = agg.sample_count_sum,
  "monitorDurationSamples" = agg.monitor_duration_samples,
  "monitorDurationSum" = agg.monitor_duration_sum,
  "fps" = CASE WHEN agg.samples > 0 THEN agg.fps_sum / agg.samples ELSE b."fps" END,
  "fileSizeBytes" = CASE WHEN agg.samples > 0 THEN ROUND(agg.file_size_sum / agg.samples)::BIGINT ELSE b."fileSizeBytes" END,
  "vmaf" = CASE WHEN agg.vmaf_samples > 0 THEN agg.vmaf_sum / agg.vmaf_samples ELSE b."vmaf" END,
  "ssim" = CASE WHEN agg.ssim_samples > 0 THEN agg.ssim_sum / agg.ssim_samples ELSE b."ssim" END,
  "psnr" = CASE WHEN agg.psnr_samples > 0 THEN agg.psnr_sum / agg.psnr_samples ELSE b."psnr" END,
  "gpuUtilAvg" = CASE WHEN agg.gpu_util_samples > 0 THEN agg.gpu_util_sum / agg.gpu_util_samples ELSE b."gpuUtilAvg" END,
  "gpuPowerAvgW" = CASE WHEN agg.gpu_power_samples > 0 THEN agg.gpu_power_sum / agg.gpu_power_samples ELSE b."gpuPowerAvgW" END,
  "cpuUtilAvg" = CASE WHEN agg.cpu_util_samples > 0 THEN agg.cpu_util_sum / agg.cpu_util_samples ELSE b."cpuUtilAvg" END,
  "peakMemoryMB" = COALESCE(agg.peak_memory_max, b."peakMemoryMB"),
  "thermalThrottle" = COALESCE(agg.thermal_throttle_any, b."thermalThrottle"),
  "gpuTempMaxC" = COALESCE(agg.gpu_temp_max, b."gpuTempMaxC"),
  "cpuFreqAvgMHz" = CASE WHEN agg.cpu_freq_samples > 0 THEN agg.cpu_freq_sum / agg.cpu_freq_samples ELSE b."cpuFreqAvgMHz" END,
  "cpuTempMaxC" = COALESCE(agg.cpu_temp_max, b."cpuTempMaxC"),
  "ffmpegCpuUtilAvg" = CASE WHEN agg.ffmpeg_cpu_avg_samples > 0 THEN agg.ffmpeg_cpu_avg_sum / agg.ffmpeg_cpu_avg_samples ELSE b."ffmpegCpuUtilAvg" END,
  "ffmpegCpuUtilMax" = COALESCE(agg.ffmpeg_cpu_max, b."ffmpegCpuUtilMax"),
  "ffmpegReadMB" = CASE WHEN agg.ffmpeg_read_samples > 0 THEN agg.ffmpeg_read_sum / agg.ffmpeg_read_samples ELSE b."ffmpegReadMB" END,
  "ffmpegWriteMB" = CASE WHEN agg.ffmpeg_write_samples > 0 THEN agg.ffmpeg_write_sum / agg.ffmpeg_write_samples ELSE b."ffmpegWriteMB" END,
  "ffmpegCpuTimeS" = CASE WHEN agg.ffmpeg_cpu_time_samples > 0 THEN agg.ffmpeg_cpu_time_sum / agg.ffmpeg_cpu_time_samples ELSE b."ffmpegCpuTimeS" END,
  "batteryPercentStart" = CASE WHEN agg.battery_start_samples > 0 THEN agg.battery_start_sum / agg.battery_start_samples ELSE b."batteryPercentStart" END,
  "batteryPercentEnd" = CASE WHEN agg.battery_end_samples > 0 THEN agg.battery_end_sum / agg.battery_end_samples ELSE b."batteryPercentEnd" END,
  "batteryPercentDrop" = CASE WHEN agg.battery_drop_samples > 0 THEN agg.battery_drop_sum / agg.battery_drop_samples ELSE b."batteryPercentDrop" END,
  "powerSource" = COALESCE(agg.latest_power_source, b."powerSource"),
  "sampleCount" = CASE WHEN agg.sample_count_samples > 0 THEN agg.sample_count_sum / agg.sample_count_samples ELSE b."sampleCount" END,
  "monitorDurationMs" = CASE WHEN agg.monitor_duration_samples > 0 THEN agg.monitor_duration_sum / agg.monitor_duration_samples ELSE b."monitorDurationMs" END,
  "status" = 'accepted',
  "updatedAt" = NOW()
FROM agg
WHERE b."cpuModel" = agg."cpuModel"
  AND b."gpuModel" = agg."gpuModel"
  AND b."ramGB" = agg."ramGB"
  AND b."os" = agg."os"
  AND b."codec" = agg."codec"
  AND b."preset" = agg."preset"
  AND b."crf" = agg."crf"
  AND b."contentClass" = agg."contentClass"
  AND b."resolution" = agg."resolution"
  AND b."passes" = agg."passes";

DROP FUNCTION IF EXISTS "_try_parse_jsonb"(TEXT);

-- Optional indexes for new telemetry filters/sorting
CREATE INDEX IF NOT EXISTS "Benchmark_gpuTempMaxC_idx" ON "Benchmark"("gpuTempMaxC");
CREATE INDEX IF NOT EXISTS "Benchmark_cpuTempMaxC_idx" ON "Benchmark"("cpuTempMaxC");
CREATE INDEX IF NOT EXISTS "Benchmark_ffmpegCpuUtilAvg_idx" ON "Benchmark"("ffmpegCpuUtilAvg");
