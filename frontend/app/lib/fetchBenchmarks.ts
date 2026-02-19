import { headers } from "next/headers";
import type { Benchmark } from "./types";

export async function fetchBenchmarks(): Promise<Benchmark[]> {
  const internal = process.env.INTERNAL_API_BASE_URL;

  let host = "localhost:3000";
  let proto = "http";
  try {
    const h = await headers();
    host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
    proto = h.get("x-forwarded-proto") || "http";
  } catch {
    // Headers unavailable, use defaults
  }

  const origin = `${proto}://${host}`;
  const primaryUrl = internal ? `${internal}/query` : `${origin}/api/query`;
  try {
    const res = await fetch(primaryUrl, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
    return res.json();
  } catch (err) {
    if (internal) {
      const res = await fetch(`${origin}/api/query`, { signal: AbortSignal.timeout(10000) });
      if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
      return res.json();
    }
    throw err;
  }
}
