import { fetchLeaderboards } from "../lib/api";
import { parseAnalyticsSearchParams } from "../lib/queryState";
import type { AnalyticsFilters, LeaderboardAnalyticsRow } from "../lib/types";
import PageHeader from "../components/ui/PageHeader";
import StatusBanner from "../components/ui/StatusBanner";
import LeaderboardsWorkspace from "./LeaderboardsWorkspace";

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

export default async function LeaderboardsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  let rows: LeaderboardAnalyticsRow[] = [];
  let error: string | null = null;
  const filters: AnalyticsFilters = parseAnalyticsSearchParams(toUrlSearchParams(searchParams ? await searchParams : undefined));

  try {
    rows = await fetchLeaderboards(filters);
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className="page">
        <PageHeader title="Leaderboards" subtitle="Single-objective ranking view for a fixed benchmark slice." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader title="Leaderboards" subtitle="Single-objective ranking workspace using a fixed content, resolution, and CRF slice." />
      <LeaderboardsWorkspace rows={rows} filters={filters} />
    </div>
  );
}
