"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import type { HardwareAnalyticsRow } from "../lib/types";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const CHART_COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];
const MAX_BARS = 8;

type EfficiencyDatum = Benchmark | HardwareAnalyticsRow;

export default function EfficiencyChart({ data, title }: { data: EfficiencyDatum[]; title?: string }) {
  const t = useChartTheme();

  const { bars, hasPowerData } = useMemo(() => {
    const isHardwareAnalytics = data.length > 0 && "avgFps" in data[0]!;
    if (isHardwareAnalytics) {
      const hardwareBars = (data as HardwareAnalyticsRow[])
        .filter((row) => row.fpsPerWatt != null && row.fpsPerWatt > 0)
        .sort((a, b) => (b.fpsPerWatt ?? 0) - (a.fpsPerWatt ?? 0))
        .slice(0, MAX_BARS)
        .map((row) => ({
          codec: `${row.encoderName} / ${row.preset}`,
          value: row.fpsPerWatt ?? 0,
        }));
      return { bars: hardwareBars, hasPowerData: true };
    }

    // Try power-based efficiency first
    const powerSums = new Map<string, { total: number; count: number }>();
    for (const row of data as Benchmark[]) {
      const power = row.gpuPowerAvgW;
      if (typeof power !== "number" || power <= 0 || row.fps <= 0) continue;
      const cur = powerSums.get(row.codec) || { total: 0, count: 0 };
      cur.total += row.fps / power;
      cur.count += 1;
      powerSums.set(row.codec, cur);
    }

    const powerBars = Array.from(powerSums.entries())
      .filter(([, agg]) => agg.count > 0)
      .map(([codec, agg]) => ({ codec, value: agg.total / agg.count }))
      .sort((a, b) => b.value - a.value)
      .slice(0, MAX_BARS);

    if (powerBars.length > 0) {
      return { bars: powerBars, hasPowerData: true };
    }

    // Fallback: Quality Efficiency = VMAF / (fileSize / medianFileSize)
    const validRows = (data as Benchmark[]).filter((d) => typeof d.vmaf === "number" && d.fileSizeBytes > 0);
    if (validRows.length === 0) return { bars: [], hasPowerData: false };

    const sizes = validRows.map((d) => d.fileSizeBytes).sort((a, b) => a - b);
    const medianSize = sizes[Math.floor(sizes.length / 2)];

    const qualitySums = new Map<string, { total: number; count: number }>();
    for (const row of validRows) {
      const sizeRatio = row.fileSizeBytes / medianSize;
      const efficiency = (row.vmaf as number) / Math.max(sizeRatio, 0.01);
      const cur = qualitySums.get(row.codec) || { total: 0, count: 0 };
      cur.total += efficiency;
      cur.count += 1;
      qualitySums.set(row.codec, cur);
    }

    const qualityBars = Array.from(qualitySums.entries())
      .filter(([, agg]) => agg.count > 0)
      .map(([codec, agg]) => ({ codec, value: agg.total / agg.count }))
      .sort((a, b) => b.value - a.value)
      .slice(0, MAX_BARS);

    return { bars: qualityBars, hasPowerData: false };
  }, [data]);

  const chartTitle = title ?? (hasPowerData ? "Encoding Efficiency (FPS/Watt) by Codec" : "Quality Efficiency (VMAF / Relative Size) by Codec");
  const yAxisLabel = hasPowerData ? "FPS/W" : "Quality Eff.";
  const tooltipUnit = hasPowerData ? "FPS/W" : "QE";

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" as const },
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (params: { name: string; value: number }[]) =>
        `${escapeHtml(params[0].name)}<br/><b>${params[0].value.toFixed(3)} ${tooltipUnit}</b>`,
    },
    grid: { left: 52, right: 12, top: 12, bottom: bars.length > 4 ? 72 : 48, containLabel: false },
    xAxis: {
      type: "category",
      data: bars.map((b) => b.codec),
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11, rotate: bars.length > 4 ? 35 : 0, interval: 0 },
    },
    yAxis: {
      type: "value",
      name: yAxisLabel,
      nameTextStyle: { color: t.muted, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
    },
    series: [
      {
        type: "bar",
        data: bars.map((b, i) => ({
          value: b.value,
          itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length], borderRadius: [3, 3, 0, 0] },
        })),
        barMaxWidth: 60,
      },
    ],
  }), [bars, t, yAxisLabel, tooltipUnit]);

  if (bars.length === 0) {
    return (
      <div className="chart-card">
        <div className="chart-title">{chartTitle}</div>
        <div className="chart-empty">
          No efficiency data available. Submit benchmarks with VMAF scores or from a system with an NVIDIA GPU.
        </div>
      </div>
    );
  }

  return (
    <div className="chart-card">
      <div className="chart-title">{chartTitle}</div>
      <div className="chart-body"><EChart option={option} /></div>
    </div>
  );
}
