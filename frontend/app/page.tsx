import BenchmarksTable, { Benchmark } from "./components/BenchmarksTable";

async function fetchBenchmarks(): Promise<Benchmark[]> {
  // Default to talking directly to the backend service on the Docker network
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://server:3001";
  const res = await fetch(`${base}/query`, { next: { revalidate: 30 } });
  if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
  return res.json();
}

export default async function Home() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: any) {
    error = e?.message || "Unknown error";
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 16 }}>Encoding Benchmarks</h1>
      <p style={{ marginBottom: 16, color: "#555" }}>
        Source: <code>{process.env.NEXT_PUBLIC_API_BASE_URL || "http://server:3001"}</code>
      </p>
      {error ? (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      ) : (
        <BenchmarksTable initialData={data} />
      )}
    </div>
  );
}
