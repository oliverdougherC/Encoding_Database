"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";

type Point = {
  x: number; // file size (MB)
  y: number; // fps
  label: string;
  color: string;
};

const COLORS: Record<string, string> = {
  av1: "#10b981", // emerald-500
  h264: "#3b82f6", // blue-500
  hevc: "#a855f7", // purple-500
  vp9: "#f59e0b", // amber-500
  other: "#ef4444", // red-500
};

function codecKey(codec: string): keyof typeof COLORS {
  const c = codec.toLowerCase();
  if (c.includes("av1")) return "av1";
  if (c.includes("265") || c.includes("hevc") || c.includes("x265")) return "hevc";
  if (c.includes("264") || c.includes("avc") || c.includes("x264")) return "h264";
  if (c.includes("vp9") || c.includes("libvpx")) return "vp9";
  return "other";
}

export default function ScatterFpsSize({ data }: { data: Benchmark[] }) {
  const [codecFilter, setCodecFilter] = useState<string>("");

  const points = useMemo<Point[]>(() => {
    return data
      .filter((d) => !codecFilter || d.codec.toLowerCase().includes(codecFilter.toLowerCase()))
      .map((d) => ({
        x: Math.max(0.001, d.fileSizeBytes / (1024 * 1024)),
        y: Math.max(0, d.fps),
        label: `${d.codec} • ${d.preset}${d.crf != null ? ` • CRF ${d.crf}` : ""}`,
        color: COLORS[codecKey(d.codec)],
      }));
  }, [data, codecFilter]);

  const width = 720;
  const height = 380;
  const margin = { top: 24, right: 24, bottom: 48, left: 56 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  const maxX = Math.max(1, ...points.map((p) => p.x));
  const maxY = Math.max(1, ...points.map((p) => p.y));

  const xFor = (v: number) => margin.left + (v / maxX) * chartWidth;
  const yFor = (v: number) => margin.top + chartHeight - (v / maxY) * chartHeight;

  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontWeight: 600 }}>FPS vs File Size</div>
        <input
          className="input"
          placeholder="Filter by codec (e.g. av1, h264)"
          value={codecFilter}
          onChange={(e) => setCodecFilter(e.target.value)}
          style={{ maxWidth: 280 }}
        />
      </div>
      <svg width={width} height={height} role="img" aria-label="FPS vs File Size">
        {/* Grid */}
        {Array.from({ length: 5 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 4;
          return <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />;
        })}
        {Array.from({ length: 5 }).map((_, i) => {
          const x = margin.left + (i * chartWidth) / 4;
          return <line key={`x${i}`} y1={margin.top} y2={height - margin.bottom} x1={x} x2={x} stroke="var(--border)" strokeWidth={1} />;
        })}

        {/* Points */}
        {points.map((p, idx) => (
          <circle key={idx} cx={xFor(p.x)} cy={yFor(p.y)} r={4} fill={p.color} />
        ))}

        {/* X axis */}
        <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="var(--border)" />
        {Array.from({ length: 5 }).map((_, i) => {
          const x = margin.left + (i * chartWidth) / 4;
          const value = (maxX * i) / 4;
          return (
            <text key={i} x={x} y={height - margin.bottom + 24} textAnchor="middle" fontSize={12} fill="var(--foreground)">
              {value.toFixed(1)} MB
            </text>
          );
        })}
        <text x={margin.left} y={margin.top - 8} fontSize={12} fill="var(--foreground)">File Size (MB)</text>

        {/* Y axis */}
        <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="var(--border)" />
        {Array.from({ length: 5 }).map((_, i) => {
          const value = (maxY * (4 - i)) / 4;
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <text key={i} x={margin.left - 10} y={y + 4} textAnchor="end" fontSize={12} fill="var(--foreground)">
              {value.toFixed(0)} FPS
            </text>
          );
        })}
      </svg>
      <div className="subtle" style={{ fontSize: 12, marginTop: 6 }}>Hover your cursor to see native browser tooltips on points.</div>
      {/* Hit area labels to avoid overlapping text – rely on native tooltips: */}
      <div style={{ display: "none" }}>
        {points.map((p, idx) => (
          <span key={idx} title={`${p.label} — ${p.y.toFixed(1)} FPS, ${p.x.toFixed(2)} MB`} />
        ))}
      </div>
    </div>
  );
}


