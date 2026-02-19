import type { Benchmark } from "../lib/types";
import { DEFAULT_PL_SCORE_WEIGHTS, createPlScoreContext, scorePlBenchmarkV6 } from "../lib/plScore";
import LeaderboardTable from "../components/LeaderboardTable";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

type GroupAgg = {
  key: string;
  codec: string;
  preset: string;
  count: number;
  fps: number;
  fpsN: number;
  vmaf: number;
  vmafN: number;
  ssim: number;
  ssimN: number;
  psnr: number;
  psnrN: number;
  sizeBytes: number;
  sizeN: number;
  fpsPerWatt: number;
  fpsPerWattN: number;
  qualityPerWatt: number;
  qualityPerWattN: number;
  gpuPowerAvgW: number;
  gpuPowerN: number;
  cpuSpread: number;
  cpuSpreadN: number;
  peakMemoryMB: number;
  peakMemoryN: number;
  thermalThrottleHits: number;
};

function groupByCodecPreset(data: Benchmark[]): Map<string, GroupAgg> {
  const map = new Map<string, GroupAgg>();
  for (const d of data) {
    const key = `${d.codec} / ${d.preset}`;
    const g = map.get(key) || {
      key,
      codec: d.codec,
      preset: d.preset,
      count: 0,
      fps: 0,
      fpsN: 0,
      vmaf: 0,
      vmafN: 0,
      ssim: 0,
      ssimN: 0,
      psnr: 0,
      psnrN: 0,
      sizeBytes: 0,
      sizeN: 0,
      fpsPerWatt: 0,
      fpsPerWattN: 0,
      qualityPerWatt: 0,
      qualityPerWattN: 0,
      gpuPowerAvgW: 0,
      gpuPowerN: 0,
      cpuSpread: 0,
      cpuSpreadN: 0,
      peakMemoryMB: 0,
      peakMemoryN: 0,
      thermalThrottleHits: 0,
    };
    if (d.fps > 0) { g.fps += d.fps; g.fpsN++; }
    if (typeof d.vmaf === "number") { g.vmaf += d.vmaf; g.vmafN++; }
    if (typeof d.ssim === "number") { g.ssim += d.ssim; g.ssimN++; }
    if (typeof d.psnr === "number") { g.psnr += d.psnr; g.psnrN++; }
    if (d.fileSizeBytes > 0) { g.sizeBytes += d.fileSizeBytes; g.sizeN++; }
    if (typeof d.fpsPerWatt === "number" && d.fpsPerWatt > 0) {
      g.fpsPerWatt += d.fpsPerWatt;
      g.fpsPerWattN++;
    } else if (d.fps > 0 && typeof d.gpuPowerAvgW === "number" && d.gpuPowerAvgW > 0) {
      g.fpsPerWatt += d.fps / d.gpuPowerAvgW;
      g.fpsPerWattN++;
    }
    if (typeof d.qualityPerWatt === "number" && d.qualityPerWatt > 0) {
      g.qualityPerWatt += d.qualityPerWatt;
      g.qualityPerWattN++;
    } else if (typeof d.vmaf === "number" && typeof d.gpuPowerAvgW === "number" && d.gpuPowerAvgW > 0) {
      g.qualityPerWatt += d.vmaf / d.gpuPowerAvgW;
      g.qualityPerWattN++;
    }
    if (typeof d.gpuPowerAvgW === "number" && d.gpuPowerAvgW > 0) {
      g.gpuPowerAvgW += d.gpuPowerAvgW;
      g.gpuPowerN++;
    }
    if (typeof d.cpuUtilAvg === "number" && typeof d.cpuUtilMax === "number") {
      g.cpuSpread += Math.max(0, d.cpuUtilMax - d.cpuUtilAvg);
      g.cpuSpreadN++;
    }
    if (typeof d.peakMemoryMB === "number" && d.peakMemoryMB > 0) {
      g.peakMemoryMB += d.peakMemoryMB;
      g.peakMemoryN++;
    }
    if (d.thermalThrottle === true) g.thermalThrottleHits++;
    g.count++;
    map.set(key, g);
  }
  return map;
}

export default async function LeaderboardsPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className={styles.container}>
        <h1 className={styles.heading}>Leaderboards</h1>
        <div style={{ background: "var(--error-bg)", color: "var(--error-fg)", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      </div>
    );
  }

  const groups = groupByCodecPreset(data);

  // Compute averages
  const aggs = Array.from(groups.values()).map((g) => ({
    key: g.key,
    codec: g.codec,
    preset: g.preset,
    avgFps: g.fpsN > 0 ? g.fps / g.fpsN : 0,
    avgVmaf: g.vmafN > 0 ? g.vmaf / g.vmafN : null,
    avgSsim: g.ssimN > 0 ? g.ssim / g.ssimN : null,
    avgPsnr: g.psnrN > 0 ? g.psnr / g.psnrN : null,
    avgSizeBytes: g.sizeN > 0 ? g.sizeBytes / g.sizeN : 0,
    avgSizeMB: g.sizeN > 0 ? (g.sizeBytes / g.sizeN) / (1024 * 1024) : 0,
    avgFpsPerWatt: g.fpsPerWattN > 0 ? g.fpsPerWatt / g.fpsPerWattN : null,
    avgQualityPerWatt: g.qualityPerWattN > 0 ? g.qualityPerWatt / g.qualityPerWattN : null,
    avgGpuPower: g.gpuPowerN > 0 ? g.gpuPowerAvgW / g.gpuPowerN : null,
    avgCpuSpread: g.cpuSpreadN > 0 ? g.cpuSpread / g.cpuSpreadN : null,
    avgPeakMemory: g.peakMemoryN > 0 ? g.peakMemoryMB / g.peakMemoryN : null,
    thermalThrottleRate: g.count > 0 ? g.thermalThrottleHits / g.count : 0,
    count: g.count,
  }));

  const nowIso = new Date().toISOString();
  const scoringRows: Benchmark[] = aggs.map((a, i) => {
    const cpuAvgSynthetic = a.avgCpuSpread != null ? 72 : null;
    const cpuMaxSynthetic = a.avgCpuSpread != null ? 72 + a.avgCpuSpread : null;
    return {
      id: `leaderboard-${i}`,
      createdAt: nowIso,
      cpuModel: a.key,
      gpuModel: null,
      ramGB: 0,
      os: "aggregated",
      codec: a.codec,
      preset: a.preset,
      crf: null,
      fps: a.avgFps,
      vmaf: a.avgVmaf,
      ssim: a.avgSsim,
      psnr: a.avgPsnr,
      fileSizeBytes: Math.max(1, Math.round(a.avgSizeBytes)),
      notes: null,
      fpsPerWatt: a.avgFpsPerWatt,
      qualityPerWatt: a.avgQualityPerWatt,
      gpuPowerAvgW: a.avgGpuPower,
      cpuUtilAvg: cpuAvgSynthetic,
      cpuUtilMax: cpuMaxSynthetic,
      peakMemoryMB: a.avgPeakMemory,
      thermalThrottle: a.thermalThrottleRate >= 0.25,
      status: "accepted",
      samples: a.count,
    };
  });
  const plContext = createPlScoreContext(scoringRows);

  const fastest = [...aggs].sort((a, b) => b.avgFps - a.avgFps).map((a) => ({ name: a.key, value: a.avgFps, formattedValue: `${a.avgFps.toFixed(1)} FPS` }));
  const bestQuality = [...aggs].filter((a) => typeof a.avgVmaf === "number" && a.avgVmaf > 0).sort((a, b) => (b.avgVmaf ?? 0) - (a.avgVmaf ?? 0)).map((a) => ({ name: a.key, value: a.avgVmaf ?? 0, formattedValue: (a.avgVmaf ?? 0).toFixed(1) }));
  const bestCompression = [...aggs].filter((a) => a.avgSizeMB > 0).sort((a, b) => a.avgSizeMB - b.avgSizeMB).map((a) => ({ name: a.key, value: 1 / Math.max(0.01, a.avgSizeMB), formattedValue: `${a.avgSizeMB.toFixed(2)} MB` }));
  const bestPlScore = aggs
    .map((a, idx) => {
      const score = scorePlBenchmarkV6(scoringRows[idx]!, plContext, DEFAULT_PL_SCORE_WEIGHTS).total;
      return { ...a, plScore: score };
    })
    .sort((a, b) => b.plScore - a.plScore)
    .map((a) => ({ name: a.key, value: a.plScore, formattedValue: a.plScore.toFixed(1) }));

  // By CPU model
  const cpuCounts = new Map<string, number>();
  for (const d of data) {
    cpuCounts.set(d.cpuModel, (cpuCounts.get(d.cpuModel) || 0) + 1);
  }
  const mostTestedCpus = Array.from(cpuCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, value: count, formattedValue: String(count) }));

  // By codec
  const codecCounts = new Map<string, number>();
  for (const d of data) {
    codecCounts.set(d.codec, (codecCounts.get(d.codec) || 0) + 1);
  }
  const mostTestedCodecs = Array.from(codecCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, value: count, formattedValue: String(count) }));

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Leaderboards</h1>
      <p className="subtle" style={{ marginBottom: 24 }}>Top-performing encoders ranked across key metrics. Based on community-submitted benchmarks.</p>
      <div className={styles.grid}>
        <LeaderboardTable title="Fastest Encoders" entries={fastest} valueLabel="Avg FPS" />
        <LeaderboardTable title="Best Quality" entries={bestQuality} valueLabel="Avg VMAF" />
        <LeaderboardTable title="Best Compression" entries={bestCompression} valueLabel="Avg Size" />
        <LeaderboardTable title="Best PL Score v6" entries={bestPlScore} valueLabel="Score" />
        <LeaderboardTable title="Most Tested CPUs" entries={mostTestedCpus} valueLabel="Submissions" />
        <LeaderboardTable title="Most Tested Codecs" entries={mostTestedCodecs} valueLabel="Submissions" />
      </div>
    </div>
  );
}
