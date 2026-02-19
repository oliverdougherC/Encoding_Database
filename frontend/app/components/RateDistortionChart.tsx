"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import EChart from "./EChart";

type QualityMetric = "vmaf" | "ssim" | "psnr";

const METRIC_LABELS: Record<QualityMetric, string> = {
  vmaf: "VMAF",
  ssim: "SSIM",
  psnr: "PSNR (dB)",
};

const MAX_VISIBLE_LINES = 8;

function shortName(name: string): string {
  if (name.length <= 22) return name;
  return `${name.slice(0, 19)}...`;
}

export default function RateDistortionChart({ data }: { data: Benchmark[] }) {
  const t = useChartTheme();
  const [metric, setMetric] = useState<QualityMetric>("vmaf");
  const [codecFilter, setCodecFilter] = useState("");
  const [showAll, setShowAll] = useState(false);

  const lines = useMemo(() => {
    const filtered = data.filter(
      (d) => d.crf != null && (!codecFilter || d.codec.toLowerCase().includes(codecFilter.toLowerCase())),
    );
    const groups = new Map<string, Benchmark[]>();
    for (const d of filtered) {
      const key = `${d.codec} / ${d.preset}`;
      const arr = groups.get(key) || [];
      arr.push(d);
      groups.set(key, arr);
    }
    const result: { name: string; color: string; data: [number, number][] }[] = [];
    for (const [name, rows] of groups.entries()) {
      const points = rows
        .filter((r) => typeof r[metric] === "number")
        .map((r) => [r.fileSizeBytes / (1024 * 1024), r[metric] as number] as [number, number])
        .sort((a, b) => a[0] - b[0]);
      if (points.length < 2) continue;
      result.push({ name, color: CODEC_COLORS[codecColorKey(rows[0].codec)] || CODEC_COLORS.other, data: points });
    }
    return result.sort((a, b) => b.data.length - a.data.length || a.name.localeCompare(b.name));
  }, [data, metric, codecFilter]);

  const visible = useMemo(() => (showAll ? lines : lines.slice(0, MAX_VISIBLE_LINES)), [lines, showAll]);

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg, fontSize: 12 },
      axisPointer: { type: "cross" as const, lineStyle: { color: t.border } },
      formatter: (params: { seriesName: string; value: [number, number] }[]) =>
        params
          .filter((p) => p.value[1] != null)
          .map((p) => `${shortName(p.seriesName)}: <b>${metric === "ssim" ? p.value[1].toFixed(4) : p.value[1].toFixed(2)}</b>`)
          .join("<br/>") + `<br/><span style="color:${t.muted};font-size:10px">${params[0]?.value[0]?.toFixed(2)} MB</span>`,
    },
    grid: { left: 52, right: 12, top: 12, bottom: 32, containLabel: false },
    xAxis: {
      type: "value",
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { lineStyle: { color: t.border } },
      axisLabel: { color: t.fg, fontSize: 11, formatter: (v: number) => `${v.toFixed(0)} MB` },
      splitLine: { lineStyle: { color: t.border } },
    },
    yAxis: {
      type: "value",
      name: METRIC_LABELS[metric],
      nameTextStyle: { color: t.muted, fontSize: 11 },
      min: metric === "ssim" ? 0.7 : "dataMin",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.border } },
    },
    series: visible.map((line) => ({
      name: line.name,
      type: "line",
      data: line.data,
      smooth: false,
      symbol: "circle",
      symbolSize: 5,
      showSymbol: false,
      lineStyle: { color: line.color, width: 2 },
      itemStyle: { color: line.color },
      emphasis: { showSymbol: true },
    })),
  }), [visible, metric, t]);

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8, flex: "0 0 auto" }}>
        <div style={{ fontWeight: 600 }}>Rate-Distortion Curves</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select className="input" value={metric} onChange={(e) => setMetric(e.target.value as QualityMetric)} style={{ padding: "4px 8px" }}>
            <option value="vmaf">VMAF</option>
            <option value="ssim">SSIM</option>
            <option value="psnr">PSNR</option>
          </select>
          <input className="input" placeholder="Filter codec" value={codecFilter} onChange={(e) => setCodecFilter(e.target.value)} style={{ maxWidth: 160 }} />
        </div>
      </div>
      {lines.length === 0 ? (
        <div className="subtle" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          No rate-distortion data (need encoder groups with 2+ CRF values)
        </div>
      ) : (
        <>
          <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 68, overflowY: "auto", flex: "0 0 auto" }}>
            {visible.map((line) => (
              <div key={line.name} title={line.name} style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", border: "1px solid var(--border)", borderRadius: 999, fontSize: 11 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: line.color, display: "inline-block" }} />
                {shortName(line.name)}
              </div>
            ))}
          </div>
          {lines.length > MAX_VISIBLE_LINES && (
            <div style={{ marginTop: 6, flex: "0 0 auto" }}>
              <button className="btn" onClick={() => setShowAll((v) => !v)} style={{ padding: "4px 10px", fontSize: 12 }}>
                {showAll ? `Show top ${MAX_VISIBLE_LINES}` : `Show all (${lines.length})`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
