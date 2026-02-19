"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import EChart from "./EChart";

const MAX_BARS = 8;

function shortCodec(codec: string): string {
  if (codec.length <= 14) return codec;
  return `${codec.slice(0, 11)}...`;
}

export default function PassSpeedComparison({ data, title = "1-Pass vs 2-Pass Encoding Speed" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();

  const { visible, hasTwoPass } = useMemo(() => {
    const map = new Map<string, { fps1Sum: number; fps1N: number; fps2Sum: number; fps2N: number }>();
    for (const row of data) {
      if (!map.has(row.codec)) map.set(row.codec, { fps1Sum: 0, fps1N: 0, fps2Sum: 0, fps2N: 0 });
      const e = map.get(row.codec)!;
      if ((row.passes ?? 1) === 2) { e.fps2Sum += row.fps; e.fps2N += 1; }
      else { e.fps1Sum += row.fps; e.fps1N += 1; }
    }
    const all = Array.from(map.entries())
      .map(([codec, e]) => ({
        codec,
        fps1: e.fps1N > 0 ? e.fps1Sum / e.fps1N : 0,
        fps2: e.fps2N > 0 ? e.fps2Sum / e.fps2N : 0,
      }))
      .filter((d) => d.fps1 > 0 || d.fps2 > 0)
      .sort((a, b) => Math.max(b.fps1, b.fps2) - Math.max(a.fps1, a.fps2));
    return { visible: all.slice(0, MAX_BARS), hasTwoPass: all.some((d) => d.fps2 > 0) };
  }, [data]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" as const },
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (params: { seriesName: string; value: number }[]) =>
        params.filter((p) => p.value > 0).map((p) => `${p.seriesName}: <b>${p.value.toFixed(1)} FPS</b>`).join("<br/>"),
    },
    legend: {
      data: ["1-pass (CRF)", "2-pass (CBR/VBR)"],
      textStyle: { color: t.fg, fontSize: 11 },
      top: 4,
    },
    grid: { left: 52, right: 12, top: 32, bottom: 32, containLabel: false },
    xAxis: {
      type: "category",
      data: visible.map((d) => shortCodec(d.codec)),
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: "FPS",
      nameTextStyle: { color: t.muted, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
    },
    series: [
      {
        name: "1-pass (CRF)",
        type: "bar",
        data: visible.map((d) => d.fps1),
        itemStyle: { color: "#6C8FD5", borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 40,
      },
      {
        name: "2-pass (CBR/VBR)",
        type: "bar",
        data: visible.map((d) => d.fps2),
        itemStyle: { color: "#d4a843", borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 40,
      },
    ],
  }), [visible, t]);

  if (visible.length === 0 || !hasTwoPass) return null;

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>{title}</div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
