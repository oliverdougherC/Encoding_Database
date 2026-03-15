"use client";

import { useMemo, useState } from "react";
import type { AnalyticsFilters, EncoderAnalyticsRow } from "../lib/types";
import { CODEC_COLORS, codecColorKey } from "../lib/chartColors";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "../components/EChart";
import PageHeader from "../components/ui/PageHeader";
import SectionCard from "../components/ui/SectionCard";
import Button from "../components/ui/Button";
import EmptyState from "../components/ui/EmptyState";
import AnalyticsFilterBar from "../components/AnalyticsFilterBar";
import styles from "./page.module.css";

const AXES = ["Speed", "Quality", "Compression", "SSIM", "PSNR"] as const;

type EncoderStats = EncoderAnalyticsRow & {
  label: string;
  color: string;
};

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

export default function EncoderDashboardClient({
  data,
  filters,
}: {
  data: EncoderAnalyticsRow[];
  filters: AnalyticsFilters;
}) {
  const t = useChartTheme();
  const profiles = useMemo(() => data.map((row) => ({
    ...row,
    label: `${row.encoderName} / ${row.preset}`,
    color: CODEC_COLORS[codecColorKey(row.codecFamily)] || CODEC_COLORS.other,
  })), [data]);

  const [codecQuery, setCodecQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  const visibleProfiles = useMemo(() => {
    const q = codecQuery.trim().toLowerCase();
    if (!q) return profiles;
    return profiles.filter((profile) => profile.label.toLowerCase().includes(q));
  }, [profiles, codecQuery]);

  const toggleCodec = (label: string) => {
    setSelected((prev) => {
      if (prev.includes(label)) return prev.filter((entry) => entry !== label);
      if (prev.length >= 4) return prev;
      return [...prev, label];
    });
  };

  const selectedStats = selected.map((label) => profiles.find((profile) => profile.label === label)).filter(Boolean) as EncoderStats[];

  const radarOption = useMemo(() => {
    if (selectedStats.length < 2) return null;
    let maxFps = 1;
    let maxSize = 1;
    const maxVmaf = 100;
    const maxSsim = 1;
    const maxPsnr = 50;

    for (const stat of selectedStats) {
      if (stat.avgFps > maxFps) maxFps = stat.avgFps;
      if (stat.avgSizeBytes > maxSize) maxSize = stat.avgSizeBytes;
    }

    const normalize = (stat: EncoderStats): number[] => [
      Math.min(100, (stat.avgFps / maxFps) * 100),
      Math.min(100, ((stat.avgVmaf ?? 0) / maxVmaf) * 100),
      stat.avgSizeBytes > 0 ? Math.min(100, ((maxSize - stat.avgSizeBytes) / maxSize) * 100 + 10) : 0,
      Math.min(100, ((stat.avgSsim ?? 0) / maxSsim) * 100),
      (stat.avgPsnr ?? 0) >= 20 ? Math.min(100, (((stat.avgPsnr ?? 0) - 20) / (maxPsnr - 20)) * 100) : 0,
    ];

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: t.surface,
        borderColor: t.border,
        textStyle: { color: t.fg, fontSize: 12 },
        formatter: (params: { name: string; value: number[] }) => {
          const lines = AXES.map((axis, i) => `${axis}: <b>${(params.value[i] || 0).toFixed(1)}</b>`).join("<br/>");
          return `<b>${escapeHtml(params.name)}</b><br/>${lines}`;
        },
      },
      legend: {
        data: selectedStats.map((stat) => stat.label),
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
          data: selectedStats.map((stat) => ({
            name: stat.label,
            value: normalize(stat),
            lineStyle: { color: stat.color, width: 2 },
            areaStyle: { color: stat.color, opacity: 0.15 },
            itemStyle: { color: stat.color },
            symbol: "circle",
            symbolSize: 5,
          })),
        },
      ],
    };
  }, [selectedStats, t]);

  const metricRows = useMemo(() => {
    const rows = [
      { label: "Avg FPS", values: selectedStats.map((stat) => stat.avgFps), higherIsBetter: true, digits: 1 },
      { label: "Avg VMAF", values: selectedStats.map((stat) => stat.avgVmaf), higherIsBetter: true, digits: 1 },
      { label: "Avg SSIM", values: selectedStats.map((stat) => stat.avgSsim), higherIsBetter: true, digits: 4 },
      { label: "Avg PSNR", values: selectedStats.map((stat) => stat.avgPsnr), higherIsBetter: true, digits: 2 },
      { label: "Avg Size (MB)", values: selectedStats.map((stat) => stat.avgSizeBytes / (1024 * 1024)), higherIsBetter: false, digits: 2 },
      { label: "Samples", values: selectedStats.map((stat) => stat.sampleCount), higherIsBetter: true, digits: 0 },
    ];
    return rows.map((row) => ({ ...row, best: bestIndex(row.values, row.higherIsBetter) }));
  }, [selectedStats]);

  return (
    <div className={`page ${styles.workspace}`}>
      <PageHeader
        title="Compare Workspace"
        subtitle="Select 2-4 encoder profiles to compare side by side within a fixed workload slice."
        actions={
          <Button variant="secondary" onClick={() => setSelected([])}>Clear</Button>
        }
      />

      <SectionCard title="Benchmark Slice" subtitle="All comparisons below stay inside this workload slice.">
        <AnalyticsFilterBar filters={filters} />
      </SectionCard>

      <div className={styles.grid}>
        <SectionCard title="Encoder Selector" subtitle="Choose up to 4 encoder/preset profiles." className={styles.selectorPanel}>
          <input
            className="input"
            placeholder="Filter profiles"
            value={codecQuery}
            onChange={(e) => setCodecQuery(e.target.value)}
            aria-label="Filter profiles"
          />
          <div className={styles.selectionCount}>{selected.length} of 4 selected</div>
          <div className={styles.codecList}>
            {visibleProfiles.map((profile) => {
              const isSelected = selected.includes(profile.label);
              return (
                <button
                  key={profile.label}
                  type="button"
                  className={`${styles.codecBtn} ${isSelected ? styles.codecBtnActive : ""}`.trim()}
                  onClick={() => toggleCodec(profile.label)}
                  disabled={!isSelected && selected.length >= 4}
                >
                  <span className={styles.codecTag} style={{ background: profile.color }} />
                  <span>{profile.label}</span>
                  <span className={styles.codecCount}>{profile.sampleCount}</span>
                </button>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard title="Performance Profile" subtitle="Selection visualized across the active slice." className={styles.chartPanel}>
          {radarOption ? <EChart option={radarOption} height={380} /> : <EmptyState title="Select at least two profiles" description="The radar chart appears once two or more encoder profiles are selected." />}
        </SectionCard>

        <SectionCard title="Decision Matrix" subtitle="Best-in-row values are highlighted." className={styles.matrixPanel}>
          {selectedStats.length === 0 ? (
            <EmptyState title="No profiles selected" description="Pick encoder profiles from the selector to populate the matrix." />
          ) : (
            <div className={styles.matrixWrap}>
              <table className={styles.matrixTable}>
                <thead>
                  <tr>
                    <th>Metric</th>
                    {selectedStats.map((stat) => (
                      <th key={stat.label}>{stat.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metricRows.map((row) => (
                    <tr key={row.label}>
                      <td className={styles.metricLabel}>{row.label}</td>
                      {row.values.map((value, index) => (
                        <td key={`${row.label}-${selectedStats[index]?.label}`} className={row.best === index ? styles.bestCell : ""}>
                          {typeof value === "number" ? value.toFixed(row.digits) : "-"}
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
