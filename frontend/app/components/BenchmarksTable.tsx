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
  // CRF is optional depending on encoder; when absent show "-"
  crf?: number | null;
  preset: string;
  fps: number;
  vmaf: number | null;
  fileSizeBytes: number;
  notes: string | null;
  ffmpegVersion?: string | null;
  encoderName?: string | null;
  clientVersion?: string | null;
  inputHash?: string | null;
  runMs?: number | null;
  status?: string | null;
};

type SortKey = "cpuModel" | "gpuModel" | "codec" | "crf" | "preset" | "_plove";

export default function BenchmarksTable({ initialData }: { initialData: Benchmark[] }) {
  const [cpuFilter, setCpuFilter] = useState("");
  const [gpuFilter, setGpuFilter] = useState("");
  const [codecFilter, setCodecFilter] = useState("");
  const [presetFilter, setPresetFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("_plove");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Weights for PLOVE score
  const [wQuality, setWQuality] = useState<number>(1);
  const [wSize, setWSize] = useState<number>(1);
  const [wSpeed, setWSpeed] = useState<number>(1);
  const [showDetailId, setShowDetailId] = useState<string | null>(null);

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

  // Compute relative size baseline (median size across filtered rows)
  const sizeBaseline = useMemo(() => {
    const sizes = filtered.map(r => r.fileSizeBytes).filter(s => s > 0).sort((a,b)=>a-b);
    if (sizes.length === 0) return 1;
    const mid = Math.floor(sizes.length / 2);
    return sizes.length % 2 === 0 ? Math.max(1, Math.floor((sizes[mid-1] + sizes[mid]) / 2)) : Math.max(1, sizes[mid]);
  }, [filtered]);

  const withScores = useMemo(() => {
    return filtered.map(row => {
      const vmaf = typeof row.vmaf === "number" ? Math.max(0, Math.min(100, row.vmaf)) : 0;
      const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / sizeBaseline : 1;
      const fps = Math.max(0.0001, row.fps || 0);
      // Normalize components to avoid zeroing; use multiplicative form
      const qualityTerm = Math.pow(Math.max(1e-6, vmaf), wQuality);
      const sizeTerm = Math.pow(Math.max(1e-6, 1 / relSize), wSize);
      const speedTerm = Math.pow(Math.max(1e-6, fps), wSpeed);
      const plove = qualityTerm * sizeTerm * speedTerm;
      return { ...row, _plove: plove, _relSize: relSize } as Benchmark & { _plove: number; _relSize: number };
    });
  }, [filtered, sizeBaseline, wQuality, wSize, wSpeed]);

  const sorted = useMemo(() => {
    const data = [...withScores];
    data.sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      const av = (a as any)[sortKey];
      const bv = (b as any)[sortKey];
      if (av == null && bv != null) return 1 * mul;
      if (av != null && bv == null) return -1 * mul;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mul;
      const as = String(av);
      const bs = String(bv);
      return as.localeCompare(bs) * mul;
    });
    return data;
  }, [withScores, sortKey, sortDir]);

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

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Scoring Weights</div>
          <div style={{ fontSize: 12, color: "#555" }}>
            PLOVE Score balances Quality, Size, and Speed for your goals.
          </div>
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span>Quality Priority</span>
          <input type="number" min={0} max={10} step={0.1} value={wQuality} onChange={e => setWQuality(Number(e.target.value))} style={{ width: 80, padding: 6, border: "1px solid #ddd", borderRadius: 6 }} />
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span>Size Priority</span>
          <input type="number" min={0} max={10} step={0.1} value={wSize} onChange={e => setWSize(Number(e.target.value))} style={{ width: 80, padding: 6, border: "1px solid #ddd", borderRadius: 6 }} />
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span>Speed Priority</span>
          <input type="number" min={0} max={10} step={0.1} value={wSpeed} onChange={e => setWSpeed(Number(e.target.value))} style={{ width: 80, padding: 6, border: "1px solid #ddd", borderRadius: 6 }} />
        </label>
      </div>

      <div style={{ overflowX: "auto", border: "1px solid #eee", borderRadius: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "20%" }} />
            <col style={{ width: "20%" }} />
            <col style={{ width: "15%" }} />
            <col style={{ width: "8%" }} />
            <col style={{ width: "12%" }} />
            <col style={{ width: "15%" }} />
            <col style={{ width: "10%" }} />
          </colgroup>
          <thead style={{ background: "#fafafa" }}>
            <tr>
              <Th onClick={() => setSort("cpuModel")} label="CPU" active={sortKey === "cpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("gpuModel")} label="GPU" active={sortKey === "gpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("codec")} label="Codec" active={sortKey === "codec"} dir={sortDir} />
              <Th onClick={() => setSort("crf")} label="CRF" active={sortKey === "crf"} dir={sortDir} align="right" />
              <Th onClick={() => setSort("preset")} label="Preset" active={sortKey === "preset"} dir={sortDir} />
              <Th onClick={() => setSort("_plove")} label="PLOVE Score" active={sortKey === "_plove"} dir={sortDir} align="right" />
              <th style={{ padding: 8, textAlign: "center" }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr key={row.id} style={{ borderTop: "1px solid #eee" }}>
                <td style={{ padding: 8 }}>{row.cpuModel}</td>
                <td style={{ padding: 8 }}>{row.gpuModel ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.codec}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{row.crf == null ? "-" : row.crf}</td>
                <td style={{ padding: 8 }}>{row.preset}</td>
                <td style={{ padding: 8, textAlign: "right" }}>{(row as any)._plove ? (row as any)._plove.toFixed(2) : "-"}</td>
                <td style={{ padding: 8, textAlign: "center" }}>
                  <DetailsButton onClick={() => setShowDetailId(row.id)} />
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 16, textAlign: "center", color: "#666" }}>
                  No results for current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showDetailId && (
        <DetailsModal row={sorted.find(r => r.id === showDetailId)!} onClose={() => setShowDetailId(null)} relSize={Number((sorted.find(r => r.id === showDetailId) as any)?._relSize || 1)} />
      )}
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

function DetailsModal({ row, onClose, relSize }: { row: Benchmark; onClose: () => void; relSize: number }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ background: "#fff", borderRadius: 8, maxWidth: 520, width: "100%", border: "1px solid #eee" }}>
        <div style={{ padding: 12, borderBottom: "1px solid #eee", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 600 }}>Encode Details</div>
          <button onClick={onClose} style={{ border: "1px solid #ddd", borderRadius: 6, padding: "4px 8px", background: "#fafafa" }}>Close</button>
        </div>
        <div style={{ padding: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <LabelValue label="Time" value={new Date(row.createdAt).toLocaleString()} />
          <LabelValue label="RAM (GB)" value={String(row.ramGB)} />
          <LabelValue label="OS" value={row.os} />
          <LabelValue label="FFmpeg Version" value={row.ffmpegVersion ?? "-"} />
          <LabelValue label="FPS" value={row.fps.toFixed(2)} />
          <LabelValue label="VMAF score" value={row.vmaf == null ? "-" : row.vmaf.toFixed(1)} />
          <LabelValue label="Relative File Size" value={relSize.toFixed(2)} />
        </div>
      </div>
    </div>
  );
}

function LabelValue({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 12, color: "#666" }}>{label}</div>
      <div style={{ fontWeight: 500 }}>{value}</div>
    </div>
  );
}

function DetailsButton({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
      style={{
        padding: "6px 12px",
        border: "1px solid #ddd",
        borderRadius: 10,
        background: hover ? "#eef2ff" : "#f9fafb",
        transition: "all 150ms ease",
        transform: hover ? "translateY(-1px)" : "none",
        boxShadow: hover ? "0 2px 6px rgba(0,0,0,0.08)" : "none",
      }}
      aria-label="View details"
    >
      Details
    </button>
  );
}


