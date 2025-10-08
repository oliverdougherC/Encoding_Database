"use client";

import { useMemo, useState, useEffect } from "react";

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

  // Weights for PLOVE score (sum must equal 1.0)
  const [wQuality, setWQuality] = useState<number>(1 / 3);
  const [wSize, setWSize] = useState<number>(1 / 3);
  const [wSpeed, setWSpeed] = useState<number>(1 / 3);
  const [showDetailId, setShowDetailId] = useState<string | null>(null);
  const [showFfmpegId, setShowFfmpegId] = useState<string | null>(null);

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

  // Dataset min/max for normalization
  const ranges = useMemo(() => {
    const vmafVals = filtered.map(r => (typeof r.vmaf === "number" ? r.vmaf : 0));
    const sizeVals = filtered.map(r => r.fileSizeBytes);
    const fpsVals = filtered.map(r => Math.max(0, r.fps || 0));
    const vmafMin = vmafVals.length ? Math.min(...vmafVals) : 0;
    const vmafMax = vmafVals.length ? Math.max(...vmafVals) : 0;
    const sizeMin = sizeVals.length ? Math.min(...sizeVals) : 0;
    const sizeMax = sizeVals.length ? Math.max(...sizeVals) : 0;
    const fpsMin = fpsVals.length ? Math.min(...fpsVals) : 0;
    const fpsMax = fpsVals.length ? Math.max(...fpsVals) : 0;
    return { vmafMin, vmafMax, sizeMin, sizeMax, fpsMin, fpsMax };
  }, [filtered]);

  function normalizeUp(value: number, min: number, max: number): number {
    if (!(max > min)) return 100;
    return 100 * ((value - min) / (max - min));
  }

  function normalizeDown(value: number, min: number, max: number): number {
    if (!(max > min)) return 100;
    return 100 * ((max - value) / (max - min));
  }

  const withScores = useMemo(() => {
    return filtered.map(row => {
      const vmafValue = typeof row.vmaf === "number" ? Math.max(0, Math.min(100, row.vmaf)) : 0;
      const fpsValue = Math.max(0, row.fps || 0);
      const vmafNorm = normalizeUp(vmafValue, ranges.vmafMin, ranges.vmafMax);
      const sizeNorm = normalizeDown(row.fileSizeBytes, ranges.sizeMin, ranges.sizeMax);
      const fpsNorm = normalizeUp(fpsValue, ranges.fpsMin, ranges.fpsMax);
      const plove = wQuality * vmafNorm + wSize * sizeNorm + wSpeed * fpsNorm;
      const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / sizeBaseline : 1;
      const encoder = (row.encoderName ?? row.codec ?? "").toLowerCase();
      const codecLabel = formatCodecLabel(encoder);
      return { ...row, _plove: plove, _relSize: relSize, _codecLabel: codecLabel } as Benchmark & { _plove: number; _relSize: number; _codecLabel: string };
    });
  }, [filtered, ranges, wQuality, wSize, wSpeed, sizeBaseline]);

  const sorted = useMemo(() => {
    const data = [...withScores];
    data.sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      const av = sortKey === "codec" ? (a as any)._codecLabel : (a as any)[sortKey];
      const bv = sortKey === "codec" ? (b as any)._codecLabel : (b as any)[sortKey];
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

  function setWeights(changed: "quality" | "size" | "speed", next: number) {
    const clamp = (x: number) => Math.max(0, Math.min(1, x));
    if (changed === "quality") {
      const q = clamp(next);
      const remain = 1 - q;
      const totalOther = wSize + wSpeed || 1;
      setWQuality(q);
      setWSize(clamp(remain * (wSize / totalOther)));
      setWSpeed(clamp(remain * (wSpeed / totalOther)));
    } else if (changed === "size") {
      const s = clamp(next);
      const remain = 1 - s;
      const totalOther = wQuality + wSpeed || 1;
      setWSize(s);
      setWQuality(clamp(remain * (wQuality / totalOther)));
      setWSpeed(clamp(remain * (wSpeed / totalOther)));
    } else {
      const sp = clamp(next);
      const remain = 1 - sp;
      const totalOther = wQuality + wSize || 1;
      setWSpeed(sp);
      setWQuality(clamp(remain * (wQuality / totalOther)));
      setWSize(clamp(remain * (wSize / totalOther)));
    }
  }

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <input
          placeholder="Filter CPU model"
          value={cpuFilter}
          onChange={e => setCpuFilter(e.target.value)}
          className="input"
        />
        <input
          placeholder="Filter GPU model"
          value={gpuFilter}
          onChange={e => setGpuFilter(e.target.value)}
          className="input"
        />
        <select value={codecFilter} onChange={e => setCodecFilter(e.target.value)} className="input">
          <option value="">All codecs</option>
          {codecs.map(c => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select value={presetFilter} onChange={e => setPresetFilter(e.target.value)} className="input">
          <option value="">All presets</option>
          {presets.map(p => (<option key={p} value={p}>{p}</option>))}
        </select>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Scoring Weights</div>
          <div className="subtle" style={{ fontSize: 12 }}>Sum is constrained to 1.00</div>
        </div>
        <WeightControl label="Quality (VMAF)" value={wQuality} onChange={(nv) => setWeights("quality", nv)} />
        <WeightControl label="Size" value={wSize} onChange={(nv) => setWeights("size", nv)} />
        <WeightControl label="Speed (FPS)" value={wSpeed} onChange={(nv) => setWeights("speed", nv)} />
      </div>

      <div className="card" style={{ overflowX: "auto" }}>
        <table className="table">
          <colgroup>
            <col style={{ width: "10%" }} /> {/* Details */}
            <col style={{ width: "18%" }} /> {/* CPU */}
            <col style={{ width: "18%" }} /> {/* GPU */}
            <col style={{ width: "14%" }} /> {/* Codec */}
            <col style={{ width: "8%" }} />  {/* CRF */}
            <col style={{ width: "12%" }} /> {/* Preset */}
            <col style={{ width: "12%" }} /> {/* PLOVE */}
            <col style={{ width: "8%" }} />  {/* FFmpeg */}
          </colgroup>
          <thead className="thead">
            <tr>
              <th className="th" style={{ textAlign: "center" }}>Details</th>
              <Th onClick={() => setSort("cpuModel")} label="CPU" active={sortKey === "cpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("gpuModel")} label="GPU" active={sortKey === "gpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("codec")} label="Codec" active={sortKey === "codec"} dir={sortDir} />
              <Th onClick={() => setSort("crf")} label="CRF" active={sortKey === "crf"} dir={sortDir} align="right" />
              <Th onClick={() => setSort("preset")} label="Preset" active={sortKey === "preset"} dir={sortDir} />
              <Th onClick={() => setSort("_plove")} label="PLOVE Score" active={sortKey === "_plove"} dir={sortDir} align="right" />
              <th className="th" style={{ textAlign: "center" }}>FFmpeg</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr key={row.id}>
                <td className="td" style={{ textAlign: "center" }}>
                  <DetailsButton onClick={() => setShowDetailId(row.id)} />
                </td>
                <td className="td">{row.cpuModel}</td>
                <td className="td">{row.gpuModel ?? "-"}</td>
                <td className="td">{(row as any)._codecLabel ?? row.codec}</td>
                <td className="td" style={{ textAlign: "right" }}>{row.crf == null ? "-" : row.crf}</td>
                <td className="td">{row.preset}</td>
                <td className="td" style={{ textAlign: "right" }}>{(row as any)._plove ? (row as any)._plove.toFixed(2) : "-"}</td>
                <td className="td" style={{ textAlign: "center" }}>
                  <FfmpegButton onClick={() => setShowFfmpegId(row.id)} />
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="td" style={{ textAlign: "center" }}>
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

      {showFfmpegId && (
        <FfmpegModal row={sorted.find(r => r.id === showFfmpegId)!} onClose={() => setShowFfmpegId(null)} />
      )}
    </div>
  );
}

function Th({ label, onClick, active, dir, align }: { label: string; onClick: () => void; active: boolean; dir: "asc" | "desc"; align?: "left" | "right" }) {
  return (
    <th
      onClick={onClick}
      className="th"
      style={{ cursor: "pointer", textAlign: align || "left", userSelect: "none" }}
      title="Click to sort"
    >
      {label}{active ? (dir === "asc" ? " ▲" : " ▼") : ""}
    </th>
  );
}

function DetailsModal({ row, onClose, relSize }: { row: Benchmark; onClose: () => void; relSize: number }) {
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-header">
          <div style={{ fontWeight: 600 }}>Encode Details</div>
          <button onClick={onClose} className="btn" style={{ padding: "6px 10px" }}>Close</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <LabelValue label="Time" value={new Date(row.createdAt).toLocaleString()} />
          <LabelValue label="RAM (GB)" value={String(row.ramGB)} />
          <LabelValue label="OS" value={row.os} />
          <LabelValue label="Encoder" value={(row.encoderName ?? row.codec) || "-"} />
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
      <div className="subtle" style={{ fontSize: 12 }}>{label}</div>
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
      className="btn"
      style={{ padding: "6px 12px", background: hover ? "color-mix(in srgb, var(--accent) 12%, var(--surface-2))" : undefined }}
      aria-label="View details"
    >
      Details
    </button>
  );
}

function FfmpegButton({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
      className="btn"
      style={{ padding: "6px 12px", background: hover ? "color-mix(in srgb, var(--accent) 12%, var(--surface-2))" : undefined }}
      aria-label="View ffmpeg command"
    >
      FFmpeg
    </button>
  );
}

function FfmpegModal({ row, onClose }: { row: Benchmark; onClose: () => void }) {
  const [inputPath, setInputPath] = useState<string>("input.mp4");
  const [outputPath, setOutputPath] = useState<string>("output.mp4");
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(t);
  }, [copied]);

  const command = useMemo(() => {
    const encoder = (row.encoderName ?? row.codec ?? "").trim();
    const parts: string[] = [
      "ffmpeg",
      "-i",
      inputPath || "input.mp4",
    ];
    if (encoder) {
      parts.push("-c:v", encoder);
    }
    if (row.crf != null) {
      parts.push("-crf", String(row.crf));
    }
    if (row.preset) {
      parts.push("-preset", row.preset);
    }
    parts.push("-c:a", "copy");
    parts.push(outputPath || "output.mp4");
    return parts.join(" ");
  }, [row, inputPath, outputPath]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {}
  };

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-header">
          <div style={{ fontWeight: 600 }}>FFmpeg Command</div>
          <button onClick={onClose} className="btn" style={{ padding: "6px 10px" }}>Close</button>
        </div>
        <div className="modal-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div className="subtle" style={{ fontSize: 12, marginBottom: 6 }}>Input video</div>
              <input className="input" placeholder="input.mp4" value={inputPath} onChange={e => setInputPath(e.target.value)} />
            </div>
            <div>
              <div className="subtle" style={{ fontSize: 12, marginBottom: 6 }}>Output video</div>
              <input className="input" placeholder="output.mp4" value={outputPath} onChange={e => setOutputPath(e.target.value)} />
            </div>
          </div>
          <div style={{ position: "relative" }}>
            <pre className="kbd" aria-label="FFmpeg command"><code>{command}</code></pre>
            <button className={`copy-btn${copied ? " success" : ""}`} onClick={copy} aria-label="Copy command">
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatCodecLabel(encoderLower: string): string {
  // Hardware engines
  const suffix = (name: string) => {
    if (name.endsWith("_videotoolbox")) return " VideoToolbox";
    if (name.endsWith("_nvenc")) return " NVENC";
    if (name.endsWith("_qsv")) return " QSV";
    if (name.endsWith("_amf")) return " AMF";
    if (name.endsWith("_vaapi")) return " VAAPI";
    return "";
  };
  const suf = suffix(encoderLower);
  // Map to families
  if (encoderLower.includes("av1")) return `AV1${suf}`.trim();
  if (encoderLower.includes("hevc") || encoderLower.includes("h265") || encoderLower.includes("x265")) return `HEVC (H.265)${suf}`.trim();
  if (encoderLower.includes("h264") || encoderLower.includes("x264") || encoderLower.includes("avc")) return `H.264${suf}`.trim();
  if (encoderLower.includes("vp9") || encoderLower.includes("libvpx")) return `VP9${suf}`.trim();
  // Fallback to original when unknown
  return encoderLower;
}

function WeightControl({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span>{label}</span>
      <input
        type="number"
        min={0}
        max={1}
        step={0.05}
        value={Number(value.toFixed(2))}
        onChange={e => onChange(Number(e.target.value))}
        className="input"
        style={{ width: 80 }}
      />
    </label>
  );
}


