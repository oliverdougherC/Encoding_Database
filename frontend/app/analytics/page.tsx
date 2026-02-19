import type { Benchmark } from "../components/BenchmarksTable";
import FpsByCodecChart from "../components/FpsByCodecChart";
import VmafHistogram from "../components/VmafHistogram";
import ScatterFpsSize from "../components/ScatterFpsSize";
import GroupedSizeByPreset from "../components/GroupedSizeByPreset";
import SsimHistogram from "../components/SsimHistogram";
import PsnrHistogram from "../components/PsnrHistogram";
import ScatterSsimVmaf from "../components/ScatterSsimVmaf";
import RateDistortionChart from "../components/RateDistortionChart";
import LazyChart from "../components/LazyChart";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import styles from "./page.module.css";

export const revalidate = 60;

export default async function AnalyticsPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className={styles.container}>
        <h1 className={styles.heading}>Analytics</h1>
        <div style={{ background: "var(--error-bg)", color: "var(--error-fg)", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Analytics</h1>
      <div className={styles.grid}>
        <LazyChart><FpsByCodecChart data={data} /></LazyChart>
        <LazyChart><VmafHistogram data={data} /></LazyChart>
        <LazyChart><SsimHistogram data={data} /></LazyChart>
        <LazyChart><PsnrHistogram data={data} /></LazyChart>
        <LazyChart><ScatterFpsSize data={data} /></LazyChart>
        <LazyChart><ScatterSsimVmaf data={data} /></LazyChart>
        <LazyChart><GroupedSizeByPreset data={data} /></LazyChart>
        <LazyChart><RateDistortionChart data={data} /></LazyChart>
      </div>
    </div>
  );
}
