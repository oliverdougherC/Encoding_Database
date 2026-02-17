"use client";

import { useMemo, useState, useRef, useEffect, useCallback } from "react";
import type { Benchmark } from "./BenchmarksTable";
import styles from "./ScatterFpsSize.module.css";

type Point = {
  x: number; // file size (MB)
  y: number; // fps
  label: string;
  color: string;
};

const COLORS: Record<string, string> = {
  av1: "#173B34",   // Evergreen
  h264: "#6C8FD5",  // Cornflower Blue
  hevc: "#9693CC",  // Lavender Grey
  vp9: "#d4a843",   // Darker gold (accessible contrast)
  other: "#CDDBCD", // Ash Grey
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
  const [hover, setHover] = useState<{ domX: number; domY: number; text: string; svgX: number; svgY: number } | null>(null);
  const [view, setView] = useState<{ xMax: number; yMax: number }>({ xMax: 1, yMax: 1 });
  const svgRef = useRef<SVGSVGElement | null>(null);

  const points = useMemo<Point[]>(() => {
    return data
      .filter((d) => !codecFilter || d.codec.toLowerCase().includes(codecFilter.toLowerCase()))
      .map((d) => ({
        x: Math.max(0.001, d.fileSizeBytes / (1024 * 1024)),
        y: Math.max(0, d.fps),
        label: `${d.codec} \u2022 ${d.preset}${d.crf != null ? ` \u2022 CRF ${d.crf}` : ""}`,
        color: COLORS[codecKey(d.codec)],
      }));
  }, [data, codecFilter]);

  const width = 720;
  const height = 380;
  const margin = { top: 24, right: 24, bottom: 48, left: 56 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  let maxXRaw = 1, maxYRaw = 1;
  for (const p of points) { if (p.x > maxXRaw) maxXRaw = p.x; if (p.y > maxYRaw) maxYRaw = p.y; }
  const maxX = Math.max(1, view.xMax);
  const maxY = Math.max(1, view.yMax);

  const xFor = (v: number) => margin.left + (v / maxX) * chartWidth;
  const yFor = (v: number) => margin.top + chartHeight - (v / maxY) * chartHeight;

  // Initialize view to fit data; update when data changes
  useEffect(() => {
    setView({ xMax: Math.ceil(maxXRaw), yMax: Math.ceil(maxYRaw) });
  }, [maxXRaw, maxYRaw]);

  // Throttle mouse move to one update per animation frame
  const rafRef = useRef<number | null>(null);
  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); }, []);

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const clientX = e.clientX;
    const clientY = e.clientY;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const scaleX = width / rect.width;
      const scaleY = height / rect.height;
      const svgMx = (clientX - rect.left) * scaleX;
      const svgMy = (clientY - rect.top) * scaleY;

      let best: { d2: number; p: Point } | null = null;
      for (const p of points) {
        const dx = xFor(p.x) - svgMx;
        const dy = yFor(p.y) - svgMy;
        const d2 = dx * dx + dy * dy;
        if (!best || d2 < best.d2) best = { d2, p };
      }
      if (best && best.d2 < 16 * 16) {
        setHover({
          domX: clientX - rect.left,
          domY: clientY - rect.top,
          svgX: xFor(best.p.x),
          svgY: yFor(best.p.y),
          text: `${best.p.label} \u2014 ${best.p.y.toFixed(1)} FPS, ${best.p.x.toFixed(2)} MB`,
        });
      } else {
        setHover(null);
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, maxX, maxY]);

  return (
    <div className={`card ${styles.chartCard}`} style={{ position: "relative" }}>
      <div className={styles.headerRow}>
        <div className={styles.chartTitle}>FPS vs File Size</div>
        <input
          className={`input ${styles.codecInput}`}
          placeholder="Filter by codec (e.g. av1, h264)"
          value={codecFilter}
          onChange={(e) => setCodecFilter(e.target.value)}
        />
      </div>
      <svg ref={svgRef} width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="FPS vs File Size" onMouseMove={onMouseMove} onMouseLeave={() => setHover(null)}>
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
        {points.map((p, idx) => {
          const cx = xFor(p.x);
          const cy = yFor(p.y);
          const isHovered = hover && Math.hypot(hover.svgX - cx, hover.svgY - cy) < 16;
          return (
            <circle key={idx} cx={cx} cy={cy} r={isHovered ? 6 : 4} fill={p.color} stroke="var(--foreground)" strokeWidth={1} />
          );
        })}

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
        <div className="tooltip" style={{ left: hover.domX + 8, top: hover.domY + 8 }}>
          {hover.text}
        </div>
      )}

      {/* Axis range controls */}
      <div className={styles.rangeControls}>
        <div className={styles.xRangeWrapper}>
          <input type="range" min={Math.max(1, Math.ceil(maxXRaw/4))} max={Math.max(2, Math.ceil(maxXRaw * 1.5))} step={1} value={Math.ceil(maxX)} onChange={(e)=> setView(v=>({ ...v, xMax: Number(e.target.value) }))} style={{ width: "100%", accentColor: "var(--accent)" }} />
          <div className={`subtle ${styles.xRangeLabel}`}>Max File Size (MB)</div>
        </div>
      </div>
    </div>
  );
}
