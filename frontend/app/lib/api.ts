import type {
  Benchmark,
  EncoderAnalyticsRow,
  HardwareAnalyticsRow,
  LeaderboardAnalyticsRow,
} from "./types";
import { WORKBENCH_PAGE_SIZE, type AnalyticsSearchState, type WorkbenchSearchState } from "./queryState";
import {
  buildMockEncoders,
  buildMockHardware,
  buildMockLeaderboards,
  MOCK_QUERY_ROWS,
} from "../api/_lib/mockData";

const FETCH_TIMEOUT_MS = 10_000;
export const BENCHMARKS_REVALIDATE_SECONDS = 60;

function parseTotalCount(raw: string | null): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function toSearchString(params?: URLSearchParams | Record<string, string | number | undefined>): string {
  if (!params) return "";
  if (params instanceof URLSearchParams) return params.toString();
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") continue;
    search.set(key, String(value));
  }
  return search.toString();
}

export function resolveAppOrigin(): string {
  const envOrigin = process.env.APP_URL || process.env.NEXT_PUBLIC_APP_URL;
  if (envOrigin) return envOrigin.replace(/\/+$/, "");
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  const port = process.env.PORT || "3000";
  return `http://127.0.0.1:${port}`;
}

function buildCandidates(endpointPath: string): string[] {
  const trimmedPath = endpointPath.startsWith("/") ? endpointPath : `/${endpointPath}`;
  const internal = process.env.INTERNAL_API_BASE_URL?.replace(/\/+$/, "");
  const fallback = `${resolveAppOrigin()}/api${trimmedPath}`;
  const candidates: string[] = [];
  if (internal) {
    const internalUrl = internal.endsWith(trimmedPath) ? internal : `${internal}${trimmedPath}`;
    candidates.push(internalUrl);
  }
  candidates.push(fallback);
  return Array.from(new Set(candidates));
}

function mockEnabled(): boolean {
  return String(process.env.ENABLE_QUERY_MOCK || "").trim() === "1";
}

function readMock<T>(endpointPath: string, params?: URLSearchParams | Record<string, string | number | undefined>): { data: T; totalCount: number | null } | null {
  if (!mockEnabled()) return null;
  if (endpointPath === "/query") {
    const search = params instanceof URLSearchParams ? params : new URLSearchParams(toSearchString(params));
    const limit = Number(search.get("limit") || WORKBENCH_PAGE_SIZE);
    const skip = Number(search.get("skip") || 0);
    const rows = MOCK_QUERY_ROWS.slice(Math.max(0, skip), Math.max(0, skip) + Math.max(1, limit));
    return { data: rows as T, totalCount: MOCK_QUERY_ROWS.length };
  }
  if (endpointPath === "/analytics/leaderboards") {
    return { data: buildMockLeaderboards() as T, totalCount: null };
  }
  if (endpointPath === "/analytics/hardware") {
    return { data: buildMockHardware() as T, totalCount: null };
  }
  if (endpointPath === "/analytics/encoders") {
    return { data: buildMockEncoders() as T, totalCount: null };
  }
  return null;
}

async function fetchJson<T>(
  endpointPath: string,
  params?: URLSearchParams | Record<string, string | number | undefined>,
): Promise<{ data: T; totalCount: number | null }> {
  const search = toSearchString(params);
  const mock = readMock<T>(endpointPath, params);
  if (!process.env.INTERNAL_API_BASE_URL && mock) {
    return mock;
  }
  const errors: string[] = [];
  for (const candidate of buildCandidates(endpointPath)) {
    const url = search ? `${candidate}?${search}` : candidate;
    try {
      const res = await fetch(url, {
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        next: { revalidate: BENCHMARKS_REVALIDATE_SECONDS },
      });
      if (!res.ok) throw new Error(`Failed to fetch ${endpointPath}: ${res.status}`);
      const totalCount = parseTotalCount(res.headers.get("X-Total-Count"));
      const data = await res.json() as T;
      return { data, totalCount };
    } catch (err) {
      errors.push(`${candidate}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  if (mock) {
    return mock;
  }
  throw new Error(`Failed to fetch ${endpointPath}. ${errors.join(" | ")}`);
}

export async function fetchWorkbenchPage(state: WorkbenchSearchState): Promise<{ rows: Benchmark[]; totalCount: number }> {
  const { data, totalCount } = await fetchJson<Benchmark[]>("/query", {
    limit: WORKBENCH_PAGE_SIZE,
    skip: (state.page - 1) * WORKBENCH_PAGE_SIZE,
    total: 1,
    cpu: state.cpu || undefined,
    gpu: state.gpu || undefined,
    search: state.search || undefined,
    preset: state.preset || undefined,
    sort: state.sort || undefined,
    dir: state.sort ? state.dir : undefined,
    encoderType: state.encoderType || undefined,
  });
  return { rows: data, totalCount: totalCount ?? data.length };
}

export async function fetchLeaderboards(filters: AnalyticsSearchState): Promise<LeaderboardAnalyticsRow[]> {
  const { data } = await fetchJson<LeaderboardAnalyticsRow[]>("/analytics/leaderboards", filters);
  return data;
}

export async function fetchHardwareAnalytics(filters: AnalyticsSearchState): Promise<HardwareAnalyticsRow[]> {
  const { data } = await fetchJson<HardwareAnalyticsRow[]>("/analytics/hardware", filters);
  return data;
}

export async function fetchEncoderAnalytics(filters: AnalyticsSearchState): Promise<EncoderAnalyticsRow[]> {
  const { data } = await fetchJson<EncoderAnalyticsRow[]>("/analytics/encoders", filters);
  return data;
}
