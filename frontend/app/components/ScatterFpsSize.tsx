"use client";

import { useMemo, useState, useRef, useEffect } from "react";
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
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [view, setView] = useState<{ xMax: number; yMax: number }>({ xMax: 1, yMax: 1 });
  const svgRef = useRef<SVGSVGElement | null>(null);

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

  const maxXRaw = Math.max(1, ...points.map((p) => p.x));
  const maxYRaw = Math.max(1, ...points.map((p) => p.y));
  const maxX = Math.max(1, view.xMax, maxXRaw);
  const maxY = Math.max(1, view.yMax, maxYRaw);

  const xFor = (v: number) => margin.left + (v / maxX) * chartWidth;
  const yFor = (v: number) => margin.top + chartHeight - (v / maxY) * chartHeight;

  useEffect(() => {
    setView({ xMax: maxXRaw, yMax: maxYRaw });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxXRaw, maxYRaw]);

  function onMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    // find nearest point within radius
    let best: { d2: number; p: Point } | null = null;
    for (const p of points) {
      const dx = xFor(p.x) - mx;
      const dy = yFor(p.y) - my;
      const d2 = dx * dx + dy * dy;
      if (!best || d2 < best.d2) best = { d2, p };
    }
    if (best && best.d2 < 12 * 12) {
      setHover({ x: xFor(best.p.x), y: yFor(best.p.y) - 8, text: `${best.p.label} — ${best.p.y.toFixed(1)} FPS, ${best.p.x.toFixed(2)} MB` });
    } else {
      setHover(null);
    }
  }

  function onWheel(e: React.WheelEvent<SVGSVGElement>) {
    e.preventDefault();
    const zoom = e.deltaY > 0 ? 1.1 : 0.9;
    setView(v => ({ xMax: Math.max(1, v.xMax * zoom), yMax: Math.max(1, v.yMax * zoom) }));
  }

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
      <svg ref={svgRef} width={width} height={height} role="img" aria-label="FPS vs File Size" onMouseMove={onMouseMove} onMouseLeave={() => setHover(null)} onWheel={onWheel}>
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
      {hover && (
        <div className="tooltip" style={{ left: hover.x + 8, top: hover.y }}>
          {hover.text}
        </div>
      )}
    </div>
  );
}


