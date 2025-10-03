"use client";

import { useMemo, useState } from "react";

export type Benchmark = {
  id: string;
  createdAt: string;
  cpuModel: string;
  gpuModel: string | null;
  ramGB: number;
  os: string;
  codec: string;
  preset: string;
  fps: number;
  vmaf: number | null;
  fileSizeBytes: number;
  notes: string | null;
};

type SortKey = keyof Pick<Benchmark, "createdAt" | "cpuModel" | "gpuModel" | "ramGB" | "os" | "codec" | "preset" | "fps" | "vmaf" | "fileSizeBytes">;

export default function BenchmarksTable({ initialData }: { initialData: Benchmark[] }) {
  const [cpuFilter, setCpuFilter] = useState("");
  const [gpuFilter, setGpuFilter] = useState("");
  const [codecFilter, setCodecFilter] = useState("");
  const [presetFilter, setPresetFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("createdAt");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const codecs = useMemo(() => Array.from(new Set(initialData.map(d => d.codec))).sort(), [initialData]);
  const presets = useMemo(() => Array.from(new Set(initialData.map(d => d.preset))).sort(), [initialData]);

  const filtered = useMemo(() => {
    const cpu = cpuFilter.trim().toLowerCase();
    const gpu = gpuFilter.trim().toLowerCase();
    return initialData.filter(row => {
      if (cpu && !row.cpuModel.toLowerCase().includes(cpu)) return false;
      if (gpu && !(row.gpuModel ?? "").toLowerCase().includes(gpu)) return false;
      if (codecFilter && row.codec !== codecFilter) return false;
      if (presetFilter && row.preset !== presetFilter) return false;
      return true;
    });
  }, [initialData, cpuFilter, gpuFilter, codecFilter, presetFilter]);

  const sorted = useMemo(() => {
    const data = [...filtered];
    data.sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      const av = a[sortKey] as any;
      const bv = b[sortKey] as any;
      // Handle nulls and dates
      if (sortKey === "createdAt") {
        return (new Date(av).getTime() - new Date(bv).getTime()) * mul;
      }
      if (av == null && bv != null) return 1 * mul;
      if (av != null && bv == null) return -1 * mul;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mul;
      const as = String(av);
      const bs = String(bv);
      return as.localeCompare(bs) * mul;
    });
    return data;
  }, [filtered, sortKey, sortDir]);

  const setSort = (key: SortKey) => {
    if (key === sortKey) setSortDir(d => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <input
          placeholder="Filter CPU model"
          value={cpuFilter}
          onChange={e => setCpuFilter(e.target.value)}
          style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}
        />
        <input
          placeholder="Filter GPU model"
          value={gpuFilter}
          onChange={e => setGpuFilter(e.target.value)}
          style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}
        />
        <select value={codecFilter} onChange={e => setCodecFilter(e.target.value)} style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}>
          <option value="">All codecs</option>
          {codecs.map(c => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select value={presetFilter} onChange={e => setPresetFilter(e.target.value)} style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}>
          <option value="">All presets</option>
          {presets.map(p => (<option key={p} value={p}>{p}</option>))}
        </select>
      </div>

      <div style={{ overflowX: "auto", border: "1px solid #eee", borderRadius: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead style={{ background: "#fafafa" }}>
            <tr>
              <Th onClick={() => setSort("createdAt")} label="Time" active={sortKey === "createdAt"} dir={sortDir} />
              <Th onClick={() => setSort("cpuModel")} label="CPU" active={sortKey === "cpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("gpuModel")} label="GPU" active={sortKey === "gpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("ramGB")} label="RAM (GB)" active={sortKey === "ramGB"} dir={sortDir} />
              <Th onClick={() => setSort("os")} label="OS" active={sortKey === "os"} dir={sortDir} />
              <Th onClick={() => setSort("codec")} label="Codec" active={sortKey === "codec"} dir={sortDir} />
              <Th onClick={() => setSort("preset")} label="Preset" active={sortKey === "preset"} dir={sortDir} />
              <Th onClick={() => setSort("fps")} label="FPS" active={sortKey === "fps"} dir={sortDir} align="right" />
              <Th onClick={() => setSort("vmaf")} label="VMAF" active={sortKey === "vmaf"} dir={sortDir} align="right" />
              <Th onClick={() => setSort("fileSizeBytes")} label="Size (MB)" active={sortKey === "fileSizeBytes"} dir={sortDir} align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr key={row.id} style={{ borderTop: "1px solid #eee" }}>
                <td style={{ padding: 8 }}>{new Date(row.createdAt).toLocaleString()}</td>
                <td style={{ padding: 8 }}>{row.cpuModel}</td>
                <td style={{ padding: 8 }}>{row.gpuModel ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.ramGB}</td>
                <td style={{ padding: 8 }}>{row.os}</td>
                <td style={{ padding: 8 }}>{row.codec}</td>
                <td style={{ padding: 8 }}>{row.preset}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{row.fps.toFixed(2)}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{row.vmaf == null ? "-" : row.vmaf.toFixed(1)}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{(row.fileSizeBytes / (1024 * 1024)).toFixed(2)}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={10} style={{ padding: 16, textAlign: "center", color: "#666" }}>
                  No results for current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ label, onClick, active, dir, align }: { label: string; onClick: () => void; active: boolean; dir: "asc" | "desc"; align?: "left" | "right" }) {
  return (
    <th
      onClick={onClick}
      style={{ cursor: "pointer", textAlign: align || "left", padding: 8, userSelect: "none" }}
      title="Click to sort"
    >
      {label}{active ? (dir === "asc" ? " ▲" : " ▼") : ""}
    </th>
  );
}


