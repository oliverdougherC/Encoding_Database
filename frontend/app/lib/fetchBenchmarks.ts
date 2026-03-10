import type { Benchmark } from "./types";

const PAGE_SIZE = 500;
const MAX_PAGES = 50;
const FETCH_TIMEOUT_MS = 10_000;
export const BENCHMARKS_REVALIDATE_SECONDS = 60;

function parseTotalCount(raw: string | null): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function resolveAppOrigin(): string {
  const envOrigin = process.env.APP_URL || process.env.NEXT_PUBLIC_APP_URL;
  if (envOrigin) return envOrigin.replace(/\/+$/, "");
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  const port = process.env.PORT || "3000";
  return `http://127.0.0.1:${port}`;
}

async function fetchBenchmarkPage(baseUrl: string, skip: number, limit: number): Promise<{ data: Benchmark[]; total: number | null }> {
  const url = new URL(baseUrl);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("skip", String(skip));
  url.searchParams.set("total", "1");
  const res = await fetch(url.toString(), {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    next: { revalidate: BENCHMARKS_REVALIDATE_SECONDS },
  });
  if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
  const total = parseTotalCount(res.headers.get("X-Total-Count"));
  const data = await res.json() as Benchmark[];
  return { data, total };
}

async function fetchAllBenchmarksFromBase(baseUrl: string): Promise<Benchmark[]> {
  const rows: Benchmark[] = [];
  const seenIds = new Set<string>();
  let skip = 0;
  let total: number | null = null;

  for (let page = 0; page < MAX_PAGES; page++) {
    const { data, total: reportedTotal } = await fetchBenchmarkPage(baseUrl, skip, PAGE_SIZE);
    if (total == null) total = reportedTotal;
    if (data.length === 0) break;

    for (const row of data) {
      if (seenIds.has(row.id)) continue;
      seenIds.add(row.id);
      rows.push(row);
    }

    skip += data.length;
    if (total != null && rows.length >= total) break;
    if (data.length < PAGE_SIZE && total == null) break;
  }

  return rows;
}

export async function fetchBenchmarks(): Promise<Benchmark[]> {
  const internal = process.env.INTERNAL_API_BASE_URL;
  const fallbackBase = `${resolveAppOrigin()}/api/query`;
  const candidates: string[] = [];
  const seen = new Set<string>();

  const addCandidate = (url: string | null | undefined) => {
    if (!url) return;
    const normalized = url.replace(/\/+$/, "");
    if (seen.has(normalized)) return;
    seen.add(normalized);
    candidates.push(normalized);
  };

  if (internal) {
    const normalizedInternal = internal.replace(/\/+$/, "");
    addCandidate(normalizedInternal.endsWith("/query") ? normalizedInternal : `${normalizedInternal}/query`);
  }
  addCandidate(fallbackBase);

  const errors: string[] = [];
  for (const candidate of candidates) {
    try {
      return await fetchAllBenchmarksFromBase(candidate);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      errors.push(`${candidate}: ${msg}`);
    }
  }

  throw new Error(`Failed to fetch benchmarks from all sources. ${errors.join(" | ")}`);
}
