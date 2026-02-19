"use client";

import styles from "./LeaderboardTable.module.css";

type LeaderboardEntry = {
  name: string;
  value: number;
  formattedValue: string;
};

export default function LeaderboardTable({
  title,
  entries,
  valueLabel,
}: {
  title: string;
  entries: LeaderboardEntry[];
  valueLabel: string;
}) {
  if (entries.length === 0) return null;

  const maxValue = entries.reduce((max, e) => Math.max(max, e.value), 0);

  return (
    <div className={`card ${styles.leaderboardCard}`}>
      <div className={styles.title}>{title}</div>
      <div className={styles.header}>
        <span className={styles.rankCol}>#</span>
        <span className={styles.nameCol}>Name</span>
        <span className={styles.valueCol}>{valueLabel}</span>
      </div>
      {entries.slice(0, 10).map((entry, i) => {
        const rank = i + 1;
        const barWidth = maxValue > 0 ? (entry.value / maxValue) * 100 : 0;
        return (
          <div key={entry.name} className={styles.row}>
            <span className={`${styles.rankCol} ${rank <= 3 ? styles[`rank${rank}` as keyof typeof styles] : ""}`}>
              {rank}
            </span>
            <span className={styles.nameCol}>
              <div className={styles.barBg}>
                <div className={styles.bar} style={{ width: `${barWidth}%` }} />
              </div>
              <span className={styles.nameText}>{entry.name}</span>
            </span>
            <span className={styles.valueCol}>{entry.formattedValue}</span>
          </div>
        );
      })}
    </div>
  );
}
