"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import EChart from "./EChart";

const FALLBACK_COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];

export default function FpsByCodecChart({ data, title = "Average FPS by Codec" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();

  const bars = useMemo(() => {
    const sums = new Map<string, { total: number; count: number }>();
    for (const row of data) {
      const cur = sums.get(row.codec) || { total: 0, count: 0 };
      cur.total += Number(row.fps) || 0;
      cur.count += 1;
      sums.set(row.codec, cur);
    }
    const result: { codec: string; avgFps: number; color: string }[] = [];
    for (const [codec, agg] of sums.entries()) {
      if (agg.count > 0) {
        result.push({
          codec,
          avgFps: agg.total / agg.count,
          color: CODEC_COLORS[codecColorKey(codec)] || FALLBACK_COLORS[result.length % FALLBACK_COLORS.length],
        });
      }
    }
    return result.sort((a, b) => a.codec.localeCompare(b.codec));
  }, [data]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (params: { name: string; value: number }[]) =>
        `${params[0].name}<br/><b>${params[0].value.toFixed(1)} FPS</b>`,
    },
    grid: { left: 48, right: 12, top: 12, bottom: bars.length > 5 ? 72 : 48, containLabel: false },
    xAxis: {
      type: "category",
      data: bars.map((b) => b.codec),
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: {
        color: t.fg,
        fontSize: 11,
        rotate: bars.length > 5 ? 35 : 0,
        interval: 0,
      },
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
        type: "bar",
        data: bars.map((b) => ({
          value: b.avgFps,
          itemStyle: { color: b.color, borderRadius: [3, 3, 0, 0] },
        })),
        barMaxWidth: 60,
      },
    ],
  }), [bars, t]);

  if (bars.length === 0) return null;

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>{title}</div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
