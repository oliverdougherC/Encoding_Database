import ScatterFpsSize from "../components/ScatterFpsSize";
import VmafHistogram from "../components/VmafHistogram";
import GroupedSizeByPreset from "../components/GroupedSizeByPreset";
import type { Benchmark } from "../components/BenchmarksTable";

export const dynamic = "force-dynamic";

async function fetchBenchmarks(): Promise<Benchmark[]> {
  const base = process.env.INTERNAL_API_BASE_URL || "http://server:3001";
  const res = await fetch(`${base}/query`);
  if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
  return res.json();
}

export default async function GraphsPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: any) {
    error = e?.message || "Unknown error";
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600 }}>Graphs</h1>
      {error ? (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      ) : (
        <>
          <ScatterFpsSize data={data} />
          <VmafHistogram data={data} />
          <GroupedSizeByPreset data={data} />
        </>
      )}
    </div>
  );
}


