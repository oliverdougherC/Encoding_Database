"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const CHART_COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];
const MAX_VISIBLE_CODECS = 6;

function shortCodecName(codec: string): string {
  if (codec.length <= 16) return codec;
  return `${codec.slice(0, 13)}...`;
}

export default function GroupedSizeByPreset({ data }: { data: Benchmark[] }) {
  const t = useChartTheme();

  const { presets, codecs, seriesData, totalCodecs } = useMemo(() => {
    const map = new Map<string, { sum: number; count: number; preset: string; codec: string }>();
    const codecCounts = new Map<string, number>();
    for (const r of data) {
      const key = `${r.preset}|${r.codec}`;
      const g = map.get(key) || { sum: 0, count: 0, preset: r.preset, codec: r.codec };
      g.sum += r.fileSizeBytes;
      g.count += 1;
      map.set(key, g);
      codecCounts.set(r.codec, (codecCounts.get(r.codec) || 0) + 1);
    }
    const presets = Array.from(new Set(Array.from(map.values()).map((g) => g.preset))).sort();
    const rankedCodecs = Array.from(codecCounts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([c]) => c);
    const codecs = rankedCodecs.slice(0, MAX_VISIBLE_CODECS);
    const seriesData = codecs.map((codec) =>
      presets.map((preset) => {
        const g = map.get(`${preset}|${codec}`);
        return g ? (g.sum / Math.max(1, g.count)) / (1024 * 1024) : 0;
      }),
    );
    return { presets, codecs, seriesData, totalCodecs: rankedCodecs.length };
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
        params
          .filter((p) => p.value > 0)
          .map((p) => `${escapeHtml(p.seriesName)}: <b>${p.value.toFixed(2)} MB</b>`)
          .join("<br/>"),
    },
    legend: {
      data: codecs.map(shortCodecName),
      textStyle: { color: t.fg, fontSize: 11 },
      top: 4,
      type: "scroll" as const,
    },
    grid: { left: 48, right: 12, top: 32, bottom: presets.length > 6 ? 64 : 36, containLabel: false },
    xAxis: {
      type: "category",
      data: presets,
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11, rotate: presets.length > 6 ? 30 : 0, interval: 0 },
    },
    yAxis: {
      type: "value",
      name: "MB",
      nameTextStyle: { color: t.muted, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
    },
    series: codecs.map((codec, i) => ({
      name: shortCodecName(codec),
      type: "bar",
      data: seriesData[i],
      itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length], borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 40,
    })),
  }), [presets, codecs, seriesData, t]);

  if (presets.length === 0) return null;

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>Average File Size by Preset and Codec</div>
      {totalCodecs > codecs.length && (
        <div className="subtle" style={{ marginBottom: 8, fontSize: 12, flex: "0 0 auto" }}>
          Showing top {codecs.length} codecs by sample count (of {totalCodecs}).
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
