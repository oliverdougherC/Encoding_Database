import ErrorBoundary from "../components/ErrorBoundary";
import AnalyticsFilterBar from "../components/AnalyticsFilterBar";
import HardwareRecommendation from "../components/HardwareRecommendation";
import EfficiencyChart from "../components/EfficiencyChart";
import LazyChart from "../components/LazyChart";
import { fetchHardwareAnalytics } from "../lib/api";
import { parseAnalyticsSearchParams } from "../lib/queryState";
import type { AnalyticsFilters, HardwareAnalyticsRow } from "../lib/types";
import PageHeader from "../components/ui/PageHeader";
import SectionCard from "../components/ui/SectionCard";
import StatusBanner from "../components/ui/StatusBanner";
import styles from "./page.module.css";

export const revalidate = 60;

function toUrlSearchParams(raw: Record<string, string | string[] | undefined> | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (!raw) return params;
  for (const [key, value] of Object.entries(raw)) {
    if (Array.isArray(value)) {
      if (value[0]) params.set(key, value[0]);
    } else if (value) {
      params.set(key, value);
    }
  }
  return params;
}

export default async function HardwarePage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  let data: HardwareAnalyticsRow[] = [];
  let error: string | null = null;
  const filters: AnalyticsFilters = parseAnalyticsSearchParams(toUrlSearchParams(searchParams ? await searchParams : undefined));
  try {
    data = await fetchHardwareAnalytics(filters);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className="page">
        <PageHeader title="Hardware Recommendations" subtitle="Recommendation-first hardware view for a fixed benchmark slice." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  return (
    <div className={`page ${styles.layout}`}>
      <PageHeader
        title="Hardware Recommendations"
        subtitle="Find the best hardware profile for a fixed workload slice, then validate the efficiency tradeoffs."
      />

      <SectionCard
        title="Benchmark Slice"
        subtitle="Change content, resolution, or CRF before comparing hardware."
      >
        <AnalyticsFilterBar filters={filters} />
      </SectionCard>

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
        subtitle="High-level FPS/Watt view across the ranked slice."
      >
        <div className={styles.chartArea}>
          <LazyChart>
            <ErrorBoundary>
              <EfficiencyChart data={data} title="Top Profile Efficiency (FPS/Watt)" />
            </ErrorBoundary>
          </LazyChart>
        </div>
      </SectionCard>

    </div>
  );
}
