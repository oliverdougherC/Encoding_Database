"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const CHART_COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];
const MAX_BARS = 8;

export default function EfficiencyChart({ data, title = "Encoding Efficiency (FPS/Watt) by Codec" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();

  const bars = useMemo(() => {
    const sums = new Map<string, { total: number; count: number }>();
    for (const row of data) {
      const power = row.gpuPowerAvgW;
      if (typeof power !== "number" || power <= 0 || row.fps <= 0) continue;
      const cur = sums.get(row.codec) || { total: 0, count: 0 };
      cur.total += row.fps / power;
      cur.count += 1;
      sums.set(row.codec, cur);
    }
    return Array.from(sums.entries())
      .filter(([, agg]) => agg.count > 0)
      .map(([codec, agg]) => ({ codec, value: agg.total / agg.count }))
      .sort((a, b) => b.value - a.value)
      .slice(0, MAX_BARS);
  }, [data]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" as const },
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (params: { name: string; value: number }[]) =>
        `${escapeHtml(params[0].name)}<br/><b>${params[0].value.toFixed(3)} FPS/W</b>`,
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
      name: "FPS/W",
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
  }), [bars, t]);

  if (bars.length === 0) {
    return (
      <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>{title}</div>
        <div style={{ color: "var(--muted)", flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          No power data yet. Submit benchmarks from a system with an NVIDIA GPU.
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>{title}</div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
