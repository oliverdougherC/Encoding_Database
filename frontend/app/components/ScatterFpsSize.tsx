"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";
import styles from "./ScatterFpsSize.module.css";

export default function ScatterFpsSize({ data }: { data: Benchmark[] }) {
  const t = useChartTheme();
  const [codecFilter, setCodecFilter] = useState("");

  const series = useMemo(() => {
    const filtered = data.filter(
      (d) => !codecFilter || d.codec.toLowerCase().includes(codecFilter.toLowerCase()),
    );
    const map = new Map<string, { value: [number, number]; label: string }[]>();
    for (const d of filtered) {
      const key = codecColorKey(d.codec);
      const arr = map.get(key) || [];
      arr.push({
        value: [Math.max(0.001, d.fileSizeBytes / (1024 * 1024)), Math.max(0, d.fps)],
        label: `${d.codec} • ${d.preset}${d.crf != null ? ` • CRF ${d.crf}` : ""}`,
      });
      map.set(key, arr);
    }
    return Array.from(map.entries()).map(([key, points]) => ({
      name: key,
      type: "scatter" as const,
      data: points,
      symbolSize: 6,
      itemStyle: { color: CODEC_COLORS[key] || CODEC_COLORS.other, opacity: 0.8 },
      emphasis: { itemStyle: { opacity: 1 }, scale: 1.4 },
    }));
  }, [data, codecFilter]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg, fontSize: 12 },
      formatter: (params: { seriesName: string; value: [number, number]; data: { label: string } }) =>
        `<b>${escapeHtml(params.data.label)}</b><br/>Size: ${params.value[0].toFixed(2)} MB<br/>FPS: ${params.value[1].toFixed(1)}`,
    },
    legend: {
      data: series.map((s) => s.name),
      textStyle: { color: t.fg, fontSize: 11 },
      top: 4,
      type: "scroll" as const,
    },
    dataZoom: [
      { type: "inside" },
      { type: "slider", xAxisIndex: 0, height: 16, bottom: 4, borderColor: t.border, fillerColor: `${t.accent}33`, handleStyle: { color: t.accent }, showDetail: false },
    ],
    grid: { left: 52, right: 12, top: 32, bottom: 40, containLabel: false },
    xAxis: {
      type: "value",
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11, formatter: (v: number) => `${v.toFixed(0)} MB` },
      splitLine: { lineStyle: { color: t.border } },
    },
    yAxis: {
      type: "value",
      nameTextStyle: { color: t.muted, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
    },
    series,
  }), [series, t]);

  return (
    <div className={`card ${styles.chartCard}`}>
      <div className={styles.headerRow}>
        <div className={styles.chartTitle}>FPS vs File Size</div>
        <input
          className={`input ${styles.codecInput}`}
          placeholder="Filter by codec (e.g. av1, h264)"
          value={codecFilter}
          onChange={(e) => setCodecFilter(e.target.value)}
        />
      </div>
      <div className={styles.chartBody}><EChart option={option} /></div>
    </div>
  );
}
