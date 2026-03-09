"use client";

import { useMemo, useState } from "react";
import Button from "../components/ui/Button";
import SectionCard from "../components/ui/SectionCard";
import styles from "./page.module.css";

type Entry = {
  name: string;
  value: number;
  formattedValue: string;
};

type Category = {
  id: string;
  label: string;
  valueLabel: string;
  description: string;
  entries: Entry[];
};

export default function LeaderboardsWorkspace({ categories }: { categories: Category[] }) {
  const [activeId, setActiveId] = useState<string>(categories[0]?.id ?? "");
  const active = useMemo(() => categories.find((c) => c.id === activeId) ?? categories[0], [categories, activeId]);

  if (!active) return null;

  const max = active.entries.reduce((m, e) => Math.max(m, e.value), 0);

  return (
    <div className={styles.workspace}>
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
