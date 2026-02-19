import type { Benchmark } from "./types";

/** Client-side fetch with filter params, returns data + total count. Safe to use from "use client" components. */
export async function fetchFilteredBenchmarks(
  params: Record<string, string>,
): Promise<{ data: Benchmark[]; total: number }> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`/api/query?${qs}`, { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
  const total = Number(res.headers.get("X-Total-Count") ?? "0");
  const data: Benchmark[] = await res.json();
  return { data, total };
}
