import type { Benchmark } from "../components/BenchmarksTable";
import ErrorBoundary from "../components/ErrorBoundary";
import HardwareRecommendation from "../components/HardwareRecommendation";
import EfficiencyChart from "../components/EfficiencyChart";
import GpuUtilChart from "../components/GpuUtilChart";
import PowerConsumptionChart from "../components/PowerConsumptionChart";
import CpuUtilHeatmap from "../components/CpuUtilHeatmap";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function HardwarePage() {
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
        <h1 className={styles.heading}>Hardware Intelligence</h1>
        <div style={{ background: "var(--error-bg)", color: "var(--error-fg)", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Hardware Intelligence</h1>
      <p className="subtle" style={{ marginBottom: 24 }}>
        Hardware recommendations and efficiency analysis based on real benchmark data.
        Power and GPU metrics require submissions from systems with NVIDIA GPUs.
      </p>

      <div className="card" style={{ padding: 16, marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 12 }}>Hardware Recommendation Engine</h2>
        <p className="subtle" style={{ marginBottom: 16, fontSize: 14 }}>
          Select a codec and priority to see which hardware performs best. Rankings are based on
          aggregated benchmark data from all submissions.
        </p>
        <ErrorBoundary>
          <HardwareRecommendation data={data} />
        </ErrorBoundary>
      </div>

      <h2 className={styles.subheading}>Efficiency Metrics</h2>
      <div className={styles.grid}>
        <ErrorBoundary><EfficiencyChart data={data} /></ErrorBoundary>
        <ErrorBoundary><GpuUtilChart data={data} /></ErrorBoundary>
        <ErrorBoundary><PowerConsumptionChart data={data} /></ErrorBoundary>
      </div>

      <div style={{ marginTop: 16 }}>
        <ErrorBoundary><CpuUtilHeatmap data={data} /></ErrorBoundary>
      </div>
    </div>
  );
}
