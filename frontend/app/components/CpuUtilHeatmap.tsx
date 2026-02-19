"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const HEATMAP_KEY_SEP = "\u241F";
const MAX_CODECS = 8;
const MAX_PRESETS = 8;

type Cell = { codec: string; preset: string; value: number; count: number };

function computeHeatmapData(rows: Benchmark[]): { cells: Cell[]; codecs: string[]; presets: string[] } {
  const sums = new Map<string, { total: number; count: number }>();
  const codecCounts = new Map<string, number>();
  const presetCounts = new Map<string, number>();
  for (const row of rows) {
    if (typeof row.cpuUtilAvg !== "number") continue;
    const key = [row.codec, row.preset].join(HEATMAP_KEY_SEP);
    const cur = sums.get(key) || { total: 0, count: 0 };
    cur.total += row.cpuUtilAvg;
    cur.count += 1;
    sums.set(key, cur);
    codecCounts.set(row.codec, (codecCounts.get(row.codec) || 0) + 1);
    presetCounts.set(row.preset, (presetCounts.get(row.preset) || 0) + 1);
  }
  const codecs = Array.from(codecCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, MAX_CODECS).map(([c]) => c);
  const presets = Array.from(presetCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, MAX_PRESETS).map(([p]) => p);
  const allowed = { codecs: new Set(codecs), presets: new Set(presets) };
  const cells: Cell[] = [];
  for (const [key, agg] of sums.entries()) {
    const [codec, preset] = key.split(HEATMAP_KEY_SEP);
    if (!allowed.codecs.has(codec) || !allowed.presets.has(preset)) continue;
    cells.push({ codec, preset, value: agg.total / agg.count, count: agg.count });
  }
  return { cells, codecs, presets };
}

export default function CpuUtilHeatmap({ data, title = "CPU Utilization by Encoder & Preset" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();
  const { cells, codecs, presets } = useMemo(() => computeHeatmapData(data), [data]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg, fontSize: 12 },
      formatter: (params: { value: [number, number, number, number] }) => {
        const [pi, ci, util, count] = params.value;
        const codec = escapeHtml(codecs[ci] ?? "-");
        const preset = escapeHtml(presets[pi] ?? "-");
        return `<b>${codec} / ${preset}</b><br/>CPU: <b>${util.toFixed(1)}%</b><br/>${count} run${count === 1 ? "" : "s"}`;
      },
    },
    grid: { left: 100, right: 100, top: 12, bottom: 40, containLabel: false },
    xAxis: {
      type: "category",
      data: presets,
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11, rotate: presets.length > 5 ? 30 : 0 },
      splitArea: { show: true, areaStyle: { color: ["transparent"] } },
    },
    yAxis: {
      type: "category",
      data: codecs,
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { show: false },
      axisLabel: { color: t.fg, fontSize: 11, width: 90, overflow: "truncate" as const },
      splitArea: { show: true, areaStyle: { color: ["transparent"] } },
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: "vertical" as const,
      right: 4,
      top: "middle",
      itemHeight: 120,
      inRange: { color: ["#52b788", "#f0a54a", "#ea5455"] },
      text: ["100%", "0%"],
      textStyle: { color: t.fg, fontSize: 10 },
    },
    series: [
      {
        type: "heatmap",
        data: cells.map((c) => [
          presets.indexOf(c.preset),
          codecs.indexOf(c.codec),
          c.value,
          c.count,
        ]),
        label: {
          show: true,
          formatter: (params: { value: [number, number, number] }) => `${params.value[2].toFixed(0)}%`,
          fontSize: 11,
          fontWeight: 600,
        },
        itemStyle: {
          borderColor: t.surface,
          borderWidth: 2,
          borderRadius: 4,
        },
        emphasis: {
          itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.3)" },
          label: { show: true },
        },
      },
    ],
  }), [cells, codecs, presets, t]);

  if (cells.length === 0) {
    return (
      <div className="card" style={{ padding: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>{title}</div>
        <div style={{ color: "var(--muted)", padding: "24px 0", textAlign: "center" }}>
          No CPU utilization data available yet.
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>{title}</div>
      <EChart option={option} height={Math.max(240, codecs.length * 44 + 100)} />
    </div>
  );
}
