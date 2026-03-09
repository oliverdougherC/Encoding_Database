"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "../components/BenchmarksTable";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "../components/EChart";
import PageHeader from "../components/ui/PageHeader";
import SectionCard from "../components/ui/SectionCard";
import Button from "../components/ui/Button";
import EmptyState from "../components/ui/EmptyState";
import styles from "./page.module.css";

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

function bestIndex(values: Array<number | null>, higherIsBetter: boolean): number | null {
  const usable = values.filter((v): v is number => typeof v === "number");
  if (usable.length < 2) return null;
  if (usable.every((v) => v === usable[0])) return null;

  let best: number | null = null;
  let bestVal: number | null = null;
  values.forEach((v, i) => {
    if (v == null) return;
    if (bestVal == null || (higherIsBetter ? v > bestVal : v < bestVal)) {
      bestVal = v;
      best = i;
    }
  });
  return best;
}

export default function EncoderDashboardClient({ data }: { data: Benchmark[] }) {
  const t = useChartTheme();
  const allStats = useMemo(() => computeEncoderStats(data), [data]);
  const codecs = useMemo(() => Array.from(allStats.keys()).sort(), [allStats]);

  const [codecQuery, setCodecQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  const visibleCodecs = useMemo(() => {
    const q = codecQuery.trim().toLowerCase();
    if (!q) return codecs;
    return codecs.filter((c) => c.toLowerCase().includes(q));
  }, [codecs, codecQuery]);

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
    let maxFps = 1;
    let maxSize = 1;
    const maxVmaf = 100;
    const maxSsim = 1;
    const maxPsnr = 50;

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
        textStyle: { color: t.fg, fontSize: 11 },
        top: 0,
        type: "scroll" as const,
      },
      radar: {
        indicator: AXES.map((name) => ({ name, max: 100 })),
        splitLine: { lineStyle: { color: t.border } },
        axisLine: { lineStyle: { color: t.border } },
        splitArea: { show: false },
        axisName: { color: t.fg, fontSize: 11 },
        center: ["50%", "56%"],
        radius: "62%",
      },
      series: [
        {
          type: "radar",
          data: selectedStats.map((s) => ({
            name: s.codec,
            value: normalize(s),
            lineStyle: { color: s.color, width: 2 },
            areaStyle: { color: s.color, opacity: 0.15 },
            itemStyle: { color: s.color },
            symbol: "circle",
            symbolSize: 5,
          })),
        },
      ],
    };
  }, [selectedStats, t]);

  const metricRows = useMemo(() => {
    const rows = [
      { label: "Avg FPS", values: selectedStats.map((s) => s.avgFps), higherIsBetter: true, digits: 1 },
      { label: "Avg VMAF", values: selectedStats.map((s) => s.avgVmaf), higherIsBetter: true, digits: 1 },
      { label: "Avg SSIM", values: selectedStats.map((s) => s.avgSsim), higherIsBetter: true, digits: 4 },
      { label: "Avg PSNR", values: selectedStats.map((s) => s.avgPsnr), higherIsBetter: true, digits: 2 },
      { label: "Avg Size (MB)", values: selectedStats.map((s) => s.avgSizeMB), higherIsBetter: false, digits: 2 },
      { label: "Samples", values: selectedStats.map((s) => s.count), higherIsBetter: true, digits: 0 },
    ];

    return rows.map((row) => ({ ...row, best: bestIndex(row.values, row.higherIsBetter) }));
  }, [selectedStats]);

  return (
    <div className={`page ${styles.workspace}`}>
      <PageHeader
        title="Compare Workspace"
        subtitle="Select 2-4 encoders to compare performance profiles."
        actions={
          <Button variant="secondary" onClick={() => setSelected([])}>Clear</Button>
        }
      />

      <div className={styles.grid}>
        <SectionCard title="Encoder Selector" subtitle="Choose up to 4 encoders." className={styles.selectorPanel}>
          <input
            className="input"
            placeholder="Filter encoders"
            value={codecQuery}
            onChange={(e) => setCodecQuery(e.target.value)}
            aria-label="Filter encoders"
          />
          <div className={styles.selectionCount}>{selected.length} of 4 selected</div>
          <div className={styles.codecList}>
            {visibleCodecs.map((codec) => {
              const isSelected = selected.includes(codec);
              const stats = allStats.get(codec)!;
              return (
                <button
                  key={codec}
                  type="button"
                  className={`${styles.codecBtn} ${isSelected ? styles.codecBtnActive : ""}`.trim()}
                  onClick={() => toggleCodec(codec)}
                  disabled={!isSelected && selected.length >= 4}
                >
                  <span className={styles.codecTag} style={{ background: stats.color }} />
                  <span>{codec}</span>
                  <span className={styles.codecCount}>{stats.count}</span>
                </button>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard title="Performance Profile" subtitle="Selection visualized across core axes." className={styles.chartPanel}>
          {radarOption ? <EChart option={radarOption} height={380} /> : <EmptyState title="Select at least two encoders" description="The radar chart appears once two or more encoders are selected." />}
        </SectionCard>

        <SectionCard title="Decision Matrix" subtitle="Best-in-row values are highlighted." className={styles.matrixPanel}>
          {selectedStats.length === 0 ? (
            <EmptyState title="No encoders selected" description="Pick encoders from the selector to populate the matrix." />
          ) : (
            <div className={styles.matrixWrap}>
              <table className={styles.matrixTable}>
                <thead>
                  <tr>
                    <th>Metric</th>
                    {selectedStats.map((s) => (
                      <th key={s.codec}>{s.codec}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metricRows.map((row) => (
                    <tr key={row.label}>
                      <td className={styles.metricLabel}>{row.label}</td>
                      {row.values.map((v, i) => (
                        <td key={`${row.label}-${selectedStats[i]?.codec}`} className={row.best === i ? styles.bestCell : ""}>
                          {typeof v === "number" ? v.toFixed(row.digits) : "-"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
