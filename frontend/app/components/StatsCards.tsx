import type { Benchmark } from "./BenchmarksTable";
import { formatCodecLabel } from "./codecLabel";
import styles from "./StatsCards.module.css";

export default function StatsCards({ data }: { data: Benchmark[] }) {
  const total = data.length;
  const uniqueCpus = new Set(data.map(d => d.cpuModel)).size;
  const uniqueGpus = new Set(data.map(d => d.gpuModel).filter(Boolean)).size;

  const fpsRows = data.filter(d => d.fps > 0);
  const avgFps = fpsRows.length > 0
    ? (fpsRows.reduce((s, d) => s + d.fps, 0) / fpsRows.length).toFixed(1)
    : "0";

  const codecCounts = new Map<string, number>();
  for (const d of data) {
    codecCounts.set(d.codec, (codecCounts.get(d.codec) || 0) + 1);
  }
  let topCodecRaw = "-";
  let topCount = 0;
  for (const [codec, count] of codecCounts) {
    if (count > topCount) { topCodecRaw = codec; topCount = count; }
  }
  const topCodec = topCodecRaw !== "-" ? formatCodecLabel(topCodecRaw.toLowerCase()) : "-";

  const stats = [
    { label: "Total Benchmarks", value: String(total) },
    { label: "Unique CPUs", value: String(uniqueCpus) },
    { label: "Unique GPUs", value: String(uniqueGpus) },
    { label: "Avg FPS", value: avgFps },
    { label: "Top Codec", value: topCodec },
  ];

  return (
    <div className={styles.grid}>
      {stats.map(s => (
        <div key={s.label} className={`card ${styles.card}`}>
          <div className={styles.label}>{s.label}</div>
          <div className={styles.value}>{s.value}</div>
        </div>
      ))}
    </div>
  );
}
