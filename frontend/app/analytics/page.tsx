import { headers } from "next/headers";
import type { Benchmark } from "../components/BenchmarksTable";
import FpsByCodecChart from "../components/FpsByCodecChart";
import VmafHistogram from "../components/VmafHistogram";
import ScatterFpsSize from "../components/ScatterFpsSize";
import GroupedSizeByPreset from "../components/GroupedSizeByPreset";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

async function fetchBenchmarks(): Promise<Benchmark[]> {
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

export default async function AnalyticsPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className={styles.container}>
        <h1 className={styles.heading}>Analytics</h1>
        <div style={{ background: "var(--error-bg)", color: "var(--error-fg)", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Analytics</h1>
      <div className={styles.grid}>
        <FpsByCodecChart data={data} />
        <VmafHistogram data={data} />
        <ScatterFpsSize data={data} />
        <GroupedSizeByPreset data={data} />
      </div>
    </div>
  );
}
