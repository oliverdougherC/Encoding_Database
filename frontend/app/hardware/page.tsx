import type { Benchmark } from "../components/BenchmarksTable";
import ErrorBoundary from "../components/ErrorBoundary";
import HardwareRecommendation from "../components/HardwareRecommendation";
import EfficiencyChart from "../components/EfficiencyChart";
import LazyChart from "../components/LazyChart";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import PageHeader from "../components/ui/PageHeader";
import SectionCard from "../components/ui/SectionCard";
import StatusBanner from "../components/ui/StatusBanner";
import styles from "./page.module.css";

export const revalidate = 60;

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
      <div className="page">
        <PageHeader title="Hardware Recommendations" subtitle="Recommendation-first hardware view for operational decisions." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  return (
    <div className={`page ${styles.layout}`}>
      <PageHeader
        title="Hardware Recommendations"
        subtitle="Find the best hardware profile for your current encoder priorities, then validate with compact efficiency context."
      />

      <SectionCard
        title="Recommendation Engine"
        subtitle="Ranked hardware profiles from accepted benchmark aggregates."
      >
        <ErrorBoundary>
          <HardwareRecommendation data={data} />
        </ErrorBoundary>
      </SectionCard>

      <SectionCard
        title="Efficiency Snapshot"
        subtitle="High-level FPS/Watt view across codecs."
      >
        <div className={styles.chartArea}>
          <LazyChart>
            <ErrorBoundary>
              <EfficiencyChart data={data} title="Top Codec Efficiency (FPS/Watt)" />
            </ErrorBoundary>
          </LazyChart>
        </div>
      </SectionCard>

    </div>
  );
}
