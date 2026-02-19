"use client";

import { useMemo } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import EChart from "./EChart";

export default function PsnrHistogram({ data, bins = 20 }: { data: Benchmark[]; bins?: number }) {
  const t = useChartTheme();

  const values = useMemo(() =>
    data
      .map((d) => (typeof d.psnr === "number" ? Math.max(0, Math.min(100, d.psnr)) : null))
      .filter((v): v is number => v != null),
    [data]);

  const { binData, lo, hi } = useMemo(() => {
    if (values.length === 0) return { binData: [], lo: 0, hi: 60 };
    let lo = values[0], hi = values[0];
    for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
    lo = Math.max(0, lo - 1);
    hi = Math.min(100, hi + 1);
    const step = (hi - lo) / bins;
    const counts = new Array(bins).fill(0) as number[];
    for (const v of values) {
      const idx = Math.min(bins - 1, Math.floor((v - lo) / step));
      counts[idx] += 1;
    }
    return {
      binData: counts.map((count, i) => [lo + (i + 0.5) * step, count] as [number, number]),
      lo,
      hi,
    };
  }, [values, bins]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg },
      formatter: (params: { value: [number, number] }[]) => {
        const [mid, count] = params[0].value;
        const step = (hi - lo) / bins;
        return `PSNR ${(mid - step / 2).toFixed(1)}–${(mid + step / 2).toFixed(1)} dB<br/><b>${count} run${count === 1 ? "" : "s"}</b>`;
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, height: 18, bottom: 4, borderColor: t.border, fillerColor: `${t.accent}33`, handleStyle: { color: t.accent }, showDetail: false },
    ],
    grid: { left: 40, right: 12, top: 8, bottom: 40, containLabel: false },
    xAxis: {
      type: "value",
      min: lo,
      max: hi,
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "Count",
      nameTextStyle: { color: t.muted, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
      minInterval: 1,
    },
    series: [
      {
        type: "bar",
        data: binData,
        barWidth: "95%",
        itemStyle: { color: "#d4a843", borderRadius: [3, 3, 0, 0] },
        emphasis: { itemStyle: { color: "#e8c06a" } },
      },
    ],
  }), [binData, lo, hi, bins, t]);

  if (values.length === 0) return null;

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 4, flex: "0 0 auto" }}>PSNR Distribution</div>
      <div className="subtle" style={{ fontSize: 11, marginBottom: 8, flex: "0 0 auto" }}>Scroll to zoom · drag to pan</div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
