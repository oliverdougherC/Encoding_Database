"use client";

import { useMemo, useState } from "react";
import AnalyticsFilterBar from "../components/AnalyticsFilterBar";
import Button from "../components/ui/Button";
import SectionCard from "../components/ui/SectionCard";
import type { AnalyticsFilters, LeaderboardAnalyticsRow } from "../lib/types";
import styles from "./page.module.css";

type Category = {
  id: string;
  label: string;
  valueLabel: string;
  description: string;
  entries: Array<{ name: string; value: number; formattedValue: string }>;
};

export default function LeaderboardsWorkspace({
  rows,
  filters,
}: {
  rows: LeaderboardAnalyticsRow[];
  filters: AnalyticsFilters;
}) {
  const categories = useMemo((): Category[] => [
    {
      id: "pl",
      label: "Best PL Score",
      valueLabel: "Score",
      description: "Balanced ranking across quality, size, speed, and efficiency for the active benchmark slice.",
      entries: rows
        .map((row) => ({
          name: `${row.encoderName} / ${row.preset}`,
          value: row.plScore,
          formattedValue: row.plScore.toFixed(1),
        }))
        .sort((a, b) => b.value - a.value),
    },
    {
      id: "speed",
      label: "Fastest",
      valueLabel: "Avg FPS",
      description: "Ranks encoder/preset profiles by average throughput within the selected slice.",
      entries: rows
        .map((row) => ({
          name: `${row.encoderName} / ${row.preset}`,
          value: row.avgFps,
          formattedValue: `${row.avgFps.toFixed(1)} FPS`,
        }))
        .sort((a, b) => b.value - a.value),
    },
    {
      id: "quality",
      label: "Best Quality",
      valueLabel: "Avg VMAF",
      description: "Ranks encoder/preset profiles by average VMAF where quality samples exist.",
      entries: rows
        .filter((row) => row.avgVmaf != null)
        .map((row) => ({
          name: `${row.encoderName} / ${row.preset}`,
          value: row.avgVmaf ?? 0,
          formattedValue: (row.avgVmaf ?? 0).toFixed(1),
        }))
        .sort((a, b) => b.value - a.value),
    },
    {
      id: "compression",
      label: "Best Compression",
      valueLabel: "Avg Size",
      description: "Ranks encoder/preset profiles by lowest average output size in the selected slice.",
      entries: rows
        .map((row) => ({
          name: `${row.encoderName} / ${row.preset}`,
          value: 1 / Math.max(1, row.avgSizeBytes),
          formattedValue: `${(row.avgSizeBytes / (1024 * 1024)).toFixed(2)} MB`,
        }))
        .sort((a, b) => b.value - a.value),
    },
  ], [rows]);

  const [activeId, setActiveId] = useState<string>(categories[0]?.id ?? "");
  const active = useMemo(() => categories.find((c) => c.id === activeId) ?? categories[0], [categories, activeId]);

  if (!active) return null;

  const max = active.entries.reduce((m, e) => Math.max(m, e.value), 0);

  return (
    <div className={styles.workspace}>
      <SectionCard title="Benchmark Slice" subtitle="Change the workload slice before interpreting rankings.">
        <AnalyticsFilterBar filters={filters} />
      </SectionCard>

      <SectionCard title="Metric Selector" subtitle="Switch leaderboard objective.">
        <div className={styles.tabRow}>
          {categories.map((cat) => (
            <Button
              key={cat.id}
              variant={cat.id === active.id ? "primary" : "ghost"}
              className={styles.tabBtn}
              onClick={() => setActiveId(cat.id)}
            >
              {cat.label}
            </Button>
          ))}
        </div>
      </SectionCard>

      <div className={styles.mainGrid}>
        <SectionCard title={active.label} subtitle={active.description}>
          <div className={styles.rankTableWrap}>
            <table className={styles.rankTable}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Name</th>
                  <th>{active.valueLabel}</th>
                </tr>
              </thead>
              <tbody>
                {active.entries.slice(0, 10).map((entry, index) => {
                  const ratio = max > 0 ? (entry.value / max) * 100 : 0;
                  return (
                    <tr key={entry.name}>
                      <td className={styles.rankCell}>{index + 1}</td>
                      <td>
                        <div className={styles.nameCell}>
                          <span className={styles.barTrack}><span className={styles.barFill} style={{ width: `${ratio}%` }} /></span>
                          <span className={styles.nameText}>{entry.name}</span>
                        </div>
                      </td>
                      <td className={styles.valueCell}>{entry.formattedValue}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Context" subtitle="How to interpret this ranking.">
          <div className={styles.contextBlock}>
            <p>{active.description}</p>
            <dl className={styles.contextList}>
              <div>
                <dt>Slice</dt>
                <dd>{filters.contentClass} / {filters.resolution} / CRF {filters.crf}</dd>
              </div>
              <div>
                <dt>Top entry</dt>
                <dd>{active.entries[0]?.name ?? "-"}</dd>
              </div>
              <div>
                <dt>Top value</dt>
                <dd>{active.entries[0]?.formattedValue ?? "-"}</dd>
              </div>
              <div>
                <dt>Population</dt>
                <dd>{active.entries.length} ranked groups</dd>
              </div>
            </dl>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
