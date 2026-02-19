"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "../components/BenchmarksTable";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "../components/EChart";
import styles from "./page.module.css";

const COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];

const AXES = ["Speed", "Quality", "Compression", "SSIM", "PSNR"] as const;

type EncoderStats = {
  codec: string;
  avgFps: number;
  avgVmaf: number;
  avgSsim: number;
  avgPsnr: number;
  avgSizeMB: number;
  count: number;
  color: string;
};

function computeEncoderStats(data: Benchmark[]): Map<string, EncoderStats> {
  const map = new Map<string, { fps: number; vmaf: number; ssim: number; psnr: number; size: number; vmafN: number; ssimN: number; psnrN: number; fpsN: number; sizeN: number }>();
  for (const d of data) {
    const agg = map.get(d.codec) || { fps: 0, vmaf: 0, ssim: 0, psnr: 0, size: 0, fpsN: 0, vmafN: 0, ssimN: 0, psnrN: 0, sizeN: 0 };
    if (d.fps > 0) { agg.fps += d.fps; agg.fpsN++; }
    if (typeof d.vmaf === "number") { agg.vmaf += d.vmaf; agg.vmafN++; }
    if (typeof d.ssim === "number") { agg.ssim += d.ssim; agg.ssimN++; }
    if (typeof d.psnr === "number") { agg.psnr += d.psnr; agg.psnrN++; }
    if (d.fileSizeBytes > 0) { agg.size += d.fileSizeBytes / (1024 * 1024); agg.sizeN++; }
    map.set(d.codec, agg);
  }
  const result = new Map<string, EncoderStats>();
  for (const [codec, agg] of map.entries()) {
    result.set(codec, {
      codec,
      avgFps: agg.fpsN > 0 ? agg.fps / agg.fpsN : 0,
      avgVmaf: agg.vmafN > 0 ? agg.vmaf / agg.vmafN : 0,
      avgSsim: agg.ssimN > 0 ? agg.ssim / agg.ssimN : 0,
      avgPsnr: agg.psnrN > 0 ? agg.psnr / agg.psnrN : 0,
      avgSizeMB: agg.sizeN > 0 ? agg.size / agg.sizeN : 0,
      count: agg.fpsN,
      color: CODEC_COLORS[codecColorKey(codec)] || CODEC_COLORS.other,
    });
  }
  return result;
}

export default function EncoderDashboardClient({ data }: { data: Benchmark[] }) {
  const t = useChartTheme();
  const allStats = useMemo(() => computeEncoderStats(data), [data]);
  const codecs = useMemo(() => Array.from(allStats.keys()).sort(), [allStats]);
  const [selected, setSelected] = useState<string[]>([]);

  const toggleCodec = (codec: string) => {
    setSelected((prev) => {
      if (prev.includes(codec)) return prev.filter((c) => c !== codec);
      if (prev.length >= 4) return prev;
      return [...prev, codec];
    });
  };

  const selectedStats = selected.map((c) => allStats.get(c)).filter(Boolean) as EncoderStats[];

  const radarOption = useMemo(() => {
    if (selectedStats.length < 2) return null;
    let maxFps = 1, maxSize = 1;
    const maxVmaf = 100, maxSsim = 1, maxPsnr = 50;
    for (const s of selectedStats) {
      if (s.avgFps > maxFps) maxFps = s.avgFps;
      if (s.avgSizeMB > maxSize) maxSize = s.avgSizeMB;
    }
    const normalize = (s: EncoderStats): number[] => [
      Math.min(100, (s.avgFps / maxFps) * 100),
      Math.min(100, (s.avgVmaf / maxVmaf) * 100),
      s.avgSizeMB > 0 ? Math.min(100, ((maxSize - s.avgSizeMB) / maxSize) * 100 + 10) : 0,
      Math.min(100, (s.avgSsim / maxSsim) * 100),
      s.avgPsnr >= 20 ? Math.min(100, ((s.avgPsnr - 20) / (maxPsnr - 20)) * 100) : 0,
    ];
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: t.surface,
        borderColor: t.border,
        textStyle: { color: t.fg, fontSize: 12 },
        formatter: (params: { name: string; value: number[] }) => {
          const lines = AXES.map((ax, i) => `${ax}: <b>${(params.value[i] || 0).toFixed(1)}</b>`).join("<br/>");
          return `<b>${escapeHtml(params.name)}</b><br/>${lines}`;
        },
      },
      legend: {
        data: selectedStats.map((s) => s.codec),
        textStyle: { color: t.fg, fontSize: 12 },
        top: 4,
        type: "scroll" as const,
      },
      radar: {
        indicator: AXES.map((name) => ({ name, max: 100 })),
        splitLine: { lineStyle: { color: t.border } },
        axisLine: { lineStyle: { color: t.border } },
        splitArea: { show: false },
        axisName: { color: t.fg, fontSize: 12 },
        center: ["50%", "54%"],
        radius: "60%",
      },
      series: [
        {
          type: "radar",
          data: selectedStats.map((s, i) => ({
            name: s.codec,
            value: normalize(s),
            lineStyle: { color: COLORS[i % COLORS.length], width: 2 },
            areaStyle: { color: COLORS[i % COLORS.length], opacity: 0.12 + i * 0.04 },
            itemStyle: { color: COLORS[i % COLORS.length] },
            symbol: "circle",
            symbolSize: 5,
          })),
        },
      ],
    };
  }, [selectedStats, t]);

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Encoder Comparison</h1>
      <p className="subtle" style={{ marginBottom: 16 }}>Select up to 4 encoders to compare across performance axes.</p>

      <div className={styles.codecGrid}>
        {codecs.map((codec) => {
          const isSelected = selected.includes(codec);
          const stats = allStats.get(codec)!;
          return (
            <button
              key={codec}
              type="button"
              className={`btn ${styles.codecBtn}${isSelected ? ` ${styles.codecBtnActive}` : ""}`}
              onClick={() => toggleCodec(codec)}
              disabled={!isSelected && selected.length >= 4}
              style={isSelected ? { borderColor: stats.color, background: `color-mix(in srgb, ${stats.color} 12%, var(--surface))` } : undefined}
            >
              <span className={styles.codecDot} style={{ background: stats.color }} />
              {codec}
              <span className="subtle" style={{ fontSize: 11 }}>({stats.count})</span>
            </button>
          );
        })}
      </div>

      {radarOption && (
        <>
          <div className={styles.radarWrapper}>
            <EChart option={radarOption} height={400} />
          </div>

          <div className={styles.summaryTableWrapper}>
            <table className={styles.summaryTable}>
              <thead>
                <tr>
                  <th>Metric</th>
                  {selectedStats.map((s) => (
                    <th key={s.codec} style={{ color: s.color }}>{s.codec}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td>Avg FPS</td>{selectedStats.map((s) => <td key={s.codec}>{s.avgFps.toFixed(1)}</td>)}</tr>
                <tr><td>Avg VMAF</td>{selectedStats.map((s) => <td key={s.codec}>{s.avgVmaf.toFixed(1)}</td>)}</tr>
                <tr><td>Avg SSIM</td>{selectedStats.map((s) => <td key={s.codec}>{s.avgSsim.toFixed(4)}</td>)}</tr>
                <tr><td>Avg PSNR (dB)</td>{selectedStats.map((s) => <td key={s.codec}>{s.avgPsnr.toFixed(2)}</td>)}</tr>
                <tr><td>Avg Size (MB)</td>{selectedStats.map((s) => <td key={s.codec}>{s.avgSizeMB.toFixed(2)}</td>)}</tr>
                <tr><td>Samples</td>{selectedStats.map((s) => <td key={s.codec}>{s.count}</td>)}</tr>
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected.length === 1 && (
        <div className="subtle" style={{ textAlign: "center", padding: 32 }}>
          Select at least 2 encoders to see the comparison.
        </div>
      )}

      {selected.length === 0 && (
        <div className="subtle" style={{ textAlign: "center", padding: 32 }}>
          Select encoders above to begin comparing.
        </div>
      )}
    </div>
  );
}
