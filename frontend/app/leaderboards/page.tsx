import { pageMetadata } from "../lib/seo";
import { fetchLeaderboards } from "../lib/api";
import { buildAnalyticsSearchString, parseAnalyticsSearchParams, type PlFitMode } from "../lib/queryState";
import DataUnavailable from "../components/DataUnavailable";
import LeaderboardsPanel from "../components/LeaderboardsPanel";

export const metadata = pageMetadata("/leaderboards", "Video Encoder Benchmark Leaderboards | EncodingDB", "Explore video encoder leaderboards with workload filters, evidence requirements, and separate quality, storage, and realtime comparison modes.");

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
  let payload;
  try { payload = await fetchLeaderboards(state); }
  catch (error) {
    console.error("Unable to load leaderboards", error);
    const search = toParams(searchParams ? await searchParams : undefined).toString();
    return <div className="page"><header className="page-heading"><h1>Leaderboards</h1><p>Rankings for a specific workload, environment, and score context.</p></header><DataUnavailable href={search ? `/leaderboards?${search}` : "/leaderboards"} subject="Rankings" /></div>;
  }
  const modeLinks = Object.fromEntries(MODE_ORDER.map((mode) => [
    mode,
    `/leaderboards?${buildAnalyticsSearchString({ ...state, fitMode: mode })}`,
  ])) as Record<PlFitMode, string>;

  return <div className="page">
    <LeaderboardsPanel payload={payload} modeLinks={modeLinks} searchState={state} />
  </div>;
}
