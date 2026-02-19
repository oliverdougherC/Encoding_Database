"use client";

import { useEffect, useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const RESOLUTION_ORDER = ["480p", "720p", "1080p", "1440p", "4k"];
const COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];
const MAX_SELECTED = 4;
const MAX_SELECTOR = 12;

type ResolutionFps = { codec: string; fpsPerRes: Record<string, number>; avgFps: number; samples: number };

function computeResolutionFps(data: Benchmark[]): ResolutionFps[] {
  const byCodecAndRes = new Map<string, Map<string, { fpsSum: number; count: number }>>();
  for (const row of data) {
    const res = row.resolution ?? "1080p";
    if (!byCodecAndRes.has(row.codec)) byCodecAndRes.set(row.codec, new Map());
    const resMap = byCodecAndRes.get(row.codec)!;
    if (!resMap.has(res)) resMap.set(res, { fpsSum: 0, count: 0 });
    const e = resMap.get(res)!;
    e.fpsSum += row.fps;
    e.count += 1;
  }
  return Array.from(byCodecAndRes.entries())
    .map(([codec, resMap]) => {
      const fpsPerRes: Record<string, number> = {};
      let totalFps = 0, totalN = 0;
      for (const res of RESOLUTION_ORDER) {
        const e = resMap.get(res);
        const avg = e && e.count > 0 ? e.fpsSum / e.count : 0;
        fpsPerRes[res] = avg;
        if (e && e.count > 0) { totalFps += e.fpsSum; totalN += e.count; }
      }
      return { codec, fpsPerRes, avgFps: totalN > 0 ? totalFps / totalN : 0, samples: totalN };
    })
    .sort((a, b) => b.avgFps - a.avgFps || a.codec.localeCompare(b.codec));
}

export default function ResolutionComparisonChart({ data, title = "FPS by Resolution per Codec" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();
  const allCodecs = useMemo(() => computeResolutionFps(data), [data]);
  const selectorOptions = useMemo(() => allCodecs.slice(0, Math.max(MAX_SELECTOR, MAX_SELECTED)), [allCodecs]);
  const [selectedCodecs, setSelectedCodecs] = useState<Set<string>>(new Set());
  const codecColorMap = useMemo(
    () => new Map(selectorOptions.map((entry, i) => [entry.codec, COLORS[i % COLORS.length]])),
    [selectorOptions],
  );

  const activeResolutions = useMemo(() => {
    const seen = new Set(data.map((r) => r.resolution ?? "1080p"));
    return RESOLUTION_ORDER.filter((r) => seen.has(r));
  }, [data]);

  useEffect(() => {
    if (selectorOptions.length === 0) return;
    setSelectedCodecs((prev) => {
      const names = selectorOptions.map((d) => d.codec);
      const next = new Set(Array.from(prev).filter((c) => names.includes(c)));
      return next.size > 0 ? next : new Set(names.slice(0, MAX_SELECTED));
    });
  }, [selectorOptions]);

  const shown = selectorOptions.filter((d) => selectedCodecs.has(d.codec));
  const forChart = shown.length > 0 ? shown : selectorOptions.slice(0, 1);

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
          .map((p) => `${escapeHtml(p.seriesName)}: <b>${p.value.toFixed(1)} FPS</b>`)
          .join("<br/>"),
    },
    grid: { left: 52, right: 12, top: 8, bottom: 32, containLabel: false },
    xAxis: {
      type: "category",
      data: activeResolutions,
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
    series: forChart.map((entry) => ({
      name: entry.codec,
      type: "bar",
      data: activeResolutions.map((res) => entry.fpsPerRes[res] || 0),
      itemStyle: { color: codecColorMap.get(entry.codec) ?? COLORS[0], borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 40,
    })),
  }), [activeResolutions, codecColorMap, forChart, t]);

  if (allCodecs.length === 0 || activeResolutions.length < 2) return null;

  const toggle = (codec: string) => {
    setSelectedCodecs((prev) => {
      const next = new Set(prev);
      if (next.has(codec)) next.delete(codec);
      else if (next.size < MAX_SELECTED) next.add(codec);
      return next;
    });
  };

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 8, flex: "0 0 auto" }}>
        {selectorOptions.map((entry) => {
          const isOn = selectedCodecs.has(entry.codec);
          const disabled = !isOn && selectedCodecs.size >= MAX_SELECTED;
          const color = codecColorMap.get(entry.codec) ?? COLORS[0];
          return (
            <button
              key={entry.codec}
              type="button"
              title={`${entry.codec} (${entry.samples} samples)`}
              onClick={() => !disabled && toggle(entry.codec)}
              style={{
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 11,
                border: `1.5px solid ${isOn ? color : "var(--border)"}`,
                background: isOn ? `color-mix(in srgb, ${color} 18%, var(--surface))` : "transparent",
                color: "var(--foreground)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.4 : 1,
              }}
            >
              {entry.codec}
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
