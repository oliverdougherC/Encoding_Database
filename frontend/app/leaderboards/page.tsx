import type { Benchmark } from "../lib/types";
import { DEFAULT_PL_SCORE_WEIGHTS, createPlScoreContext, scorePlBenchmarkV6 } from "../lib/plScore";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import PageHeader from "../components/ui/PageHeader";
import StatusBanner from "../components/ui/StatusBanner";
import LeaderboardsWorkspace from "./LeaderboardsWorkspace";

export const revalidate = 60;

type GroupAgg = {
  key: string;
  codec: string;
  preset: string;
  count: number;
  fps: number;
  fpsN: number;
  vmaf: number;
  vmafN: number;
  sizeBytes: number;
  sizeN: number;
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
      sizeBytes: 0,
      sizeN: 0,
    };
    if (d.fps > 0) { g.fps += d.fps; g.fpsN++; }
    if (typeof d.vmaf === "number") { g.vmaf += d.vmaf; g.vmafN++; }
    if (d.fileSizeBytes > 0) { g.sizeBytes += d.fileSizeBytes; g.sizeN++; }
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
      <div className="page">
        <PageHeader title="Leaderboards" subtitle="Single-objective ranking view for fast comparison." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  const groups = groupByCodecPreset(data);

  const aggs = Array.from(groups.values()).map((g) => ({
    key: g.key,
    codec: g.codec,
    preset: g.preset,
    avgFps: g.fpsN > 0 ? g.fps / g.fpsN : 0,
    avgVmaf: g.vmafN > 0 ? g.vmaf / g.vmafN : null,
    avgSizeMB: g.sizeN > 0 ? (g.sizeBytes / g.sizeN) / (1024 * 1024) : 0,
    count: g.count,
  }));

  const nowIso = new Date().toISOString();
  const scoringRows: Benchmark[] = aggs.map((a, i) => ({
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
    ssim: null,
    psnr: null,
    fileSizeBytes: Math.max(1, Math.round(a.avgSizeMB * 1024 * 1024)),
    notes: null,
    status: "accepted",
    samples: a.count,
  }));

  const plContext = createPlScoreContext(scoringRows);

  const categories = [
    {
      id: "speed",
      label: "Fastest",
      valueLabel: "Avg FPS",
      description: "Ranks encoder/preset groups by average throughput.",
      entries: [...aggs]
        .sort((a, b) => b.avgFps - a.avgFps)
        .map((a) => ({ name: a.key, value: a.avgFps, formattedValue: `${a.avgFps.toFixed(1)} FPS` })),
    },
    {
      id: "quality",
      label: "Best Quality",
      valueLabel: "Avg VMAF",
      description: "Ranks by average VMAF where quality samples exist.",
      entries: [...aggs]
        .filter((a) => typeof a.avgVmaf === "number" && a.avgVmaf > 0)
        .sort((a, b) => (b.avgVmaf ?? 0) - (a.avgVmaf ?? 0))
        .map((a) => ({ name: a.key, value: a.avgVmaf ?? 0, formattedValue: (a.avgVmaf ?? 0).toFixed(1) })),
    },
    {
      id: "compression",
      label: "Best Compression",
      valueLabel: "Avg Size",
      description: "Ranks by lowest average output size.",
      entries: [...aggs]
        .filter((a) => a.avgSizeMB > 0)
        .sort((a, b) => a.avgSizeMB - b.avgSizeMB)
        .map((a) => ({ name: a.key, value: 1 / Math.max(0.01, a.avgSizeMB), formattedValue: `${a.avgSizeMB.toFixed(2)} MB` })),
    },
    {
      id: "pl",
      label: "Best PL Score",
      valueLabel: "Score",
      description: "Ranks by PL Score v6 using default weights.",
      entries: aggs
        .map((a, idx) => ({
          ...a,
          plScore: scorePlBenchmarkV6(scoringRows[idx]!, plContext, DEFAULT_PL_SCORE_WEIGHTS).total,
        }))
        .sort((a, b) => b.plScore - a.plScore)
        .map((a) => ({ name: a.key, value: a.plScore, formattedValue: a.plScore.toFixed(1) })),
    },
  ];

  return (
    <div className="page">
      <PageHeader title="Leaderboards" subtitle="Single-objective ranking workspace with contextual interpretation." />
      <LeaderboardsWorkspace categories={categories} />
    </div>
  );
}
