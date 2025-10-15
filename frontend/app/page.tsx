import BenchmarksTable, { Benchmark } from "./components/BenchmarksTable";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

async function fetchBenchmarks(): Promise<Benchmark[]> {
  // Prefer INTERNAL_API_BASE_URL when set; otherwise fall back to local mock API route
  const internal = process.env.INTERNAL_API_BASE_URL;
  const h = await headers();
  const host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
  const proto = h.get("x-forwarded-proto") || "http";
  const origin = `${proto}://${host}`;
  const primaryUrl = internal ? `${internal}/query` : `${origin}/api/query`;
  try {
    const res = await fetch(primaryUrl);
    if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
    return res.json();
  } catch (err) {
    if (internal) {
      // Fallback to mock when server is unavailable
      const res = await fetch(`${origin}/api/query`);
      if (!res.ok) throw new Error(`Failed to fetch: ${res.status}`);
      return res.json();
    }
    throw err;
  }
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
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>Encoding Benchmarks</h1>
      <p style={{ marginBottom: 16, color: "#555" }}>
        Source Code: <a href="https://github.com/oliverdougherC/Encoding_Database" target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>github.com/oliverdougherC/Encoding_Database</a>
      </p>
      <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Get the Client</div>
          <div className="subtle" style={{ fontSize: 14 }}>Download the prebuilt client from GitHub Releases.</div>
        </div>
        <a className="btn" href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer" style={{ padding: "8px 12px" }}>Open Releases</a>
      </div>
      {error ? (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: 12, borderRadius: 8 }}>
          Failed to load data: {error}
        </div>
      ) : (
        <>
          <BenchmarksTable initialData={data} />
          <div className="card" style={{ marginTop: 16, padding: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>About the test video (sample.mp4)</div>
            <div className="subtle" style={{ fontSize: 13 }}>
              Recorded in ProRes 4:2:2, 10-bit, 3840x2160, 30FPS SDR. <br />
              Transcoded to x264 4:2:0, 8-bit, 1920x1080, RF 0, profile main, level 4.0, tune none, preset veryslow, VFR 30FPS SDR.
            </div>
          </div>
          
        </>
      )}
    </div>
  );
}
