import { fetchLeaderboards } from "../lib/api";
import { buildAnalyticsSearchString, parseAnalyticsSearchParams, type PlFitMode } from "../lib/queryState";
import LeaderboardsPanel from "../components/LeaderboardsPanel";

function toParams(raw: Record<string, string | string[] | undefined> | undefined) {
  const params = new URLSearchParams();
  Object.entries(raw ?? {}).forEach(([key, value]) => {
    const normalized = Array.isArray(value) ? value[0] : value;
    if (normalized) params.set(key, normalized);
  });
  return params;
}

const MODE_ORDER: PlFitMode[] = ["balanced", "quality", "storage", "realtime", "custom"];

export default async function LeaderboardsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const state = parseAnalyticsSearchParams(toParams(searchParams ? await searchParams : undefined));
  const payload = await fetchLeaderboards(state);
  const modeLinks = Object.fromEntries(MODE_ORDER.map((mode) => [
    mode,
    `/leaderboards?${buildAnalyticsSearchString({ ...state, fitMode: mode })}`,
  ])) as Record<PlFitMode, string>;

  return <div className="page">
    <LeaderboardsPanel payload={payload} modeLinks={modeLinks} searchState={state} />
  </div>;
}
