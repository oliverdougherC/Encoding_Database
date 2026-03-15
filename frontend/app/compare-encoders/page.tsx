import { fetchEncoderAnalytics } from "../lib/api";
import { parseAnalyticsSearchParams } from "../lib/queryState";
import type { AnalyticsFilters, EncoderAnalyticsRow } from "../lib/types";
import EncoderDashboardClient from "./EncoderDashboardClient";
import StatusBanner from "../components/ui/StatusBanner";
import PageHeader from "../components/ui/PageHeader";

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

export default async function EncoderComparisonPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  let data: EncoderAnalyticsRow[] = [];
  let error: string | null = null;
  const filters: AnalyticsFilters = parseAnalyticsSearchParams(toUrlSearchParams(searchParams ? await searchParams : undefined));
  try {
    data = await fetchEncoderAnalytics(filters);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className="page">
        <PageHeader title="Compare Workspace" subtitle="Select encoder profiles side by side within a fixed benchmark slice." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  return <EncoderDashboardClient data={data} filters={filters} />;
}
