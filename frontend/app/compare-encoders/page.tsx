import type { Benchmark } from "../components/BenchmarksTable";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import EncoderDashboardClient from "./EncoderDashboardClient";

export const revalidate = 60;

export default async function EncoderComparisonPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
        <h1 style={{ marginBottom: 16 }}>Encoder Comparison</h1>
        <div style={{ background: "var(--error-bg)", color: "var(--error-fg)", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      </div>
    );
  }

  return <EncoderDashboardClient data={data} />;
}
