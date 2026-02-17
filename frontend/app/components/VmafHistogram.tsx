"use client";

import type { Benchmark } from "./BenchmarksTable";

import { useMemo, useRef, useState } from "react";

export default function VmafHistogram({ data, bins = 12 }: { data: Benchmark[]; bins?: number }) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const valuesAll = useMemo(() => {
    return data.map((d) => typeof d.vmaf === "number" ? Math.max(0, Math.min(100, d.vmaf)) : null).filter((v): v is number => v != null);
  }, [data]);

  const { autoMin, autoMax } = useMemo(() => {
    if (valuesAll.length === 0) return { autoMin: 0, autoMax: 100 };
    let lo = valuesAll[0], hi = valuesAll[0];
    for (const v of valuesAll) { if (v < lo) lo = v; if (v > hi) hi = v; }
    return { autoMin: Math.max(0, Math.min(lo, 80)), autoMax: Math.min(100, Math.max(hi, 95)) };
  }, [valuesAll]);

  const [range, setRange] = useState<{ min: number; max: number }>({ min: autoMin, max: autoMax });

  if (valuesAll.length === 0) return null;

  const { counts, maxCount, step } = useMemo(() => {
    const mn = range.min;
    const mx = range.max;
    const s = (mx - mn) / bins;
    const visible = valuesAll.filter(v => v >= mn && v <= mx);
    const c = new Array(bins).fill(0) as number[];
    for (const v of visible) {
      const idx = Math.min(bins - 1, Math.floor((v - mn) / s));
      c[idx] += 1;
    }
    let mc = 1;
    for (const count of c) if (count > mc) mc = count;
    return { counts: c, maxCount: mc, step: s };
  }, [valuesAll, range.min, range.max, bins]);

  const min = range.min;
  const max = range.max;

  const width = 720;
  const height = 280;
  const margin = { top: 24, right: 16, bottom: 40, left: 40 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  const barGap = 2;
  const barWidth = (chartWidth - barGap * (bins - 1)) / bins;
  const xFor = (i: number) => margin.left + i * (barWidth + barGap);
  const yFor = (c: number) => margin.top + chartHeight - (c / maxCount) * chartHeight;

  // Convert SVG coordinates to DOM pixel coordinates for tooltip positioning
  function svgToDom(svgX: number, svgY: number): { x: number; y: number } {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: svgX, y: svgY };
    return {
      x: (svgX / width) * rect.width,
      y: (svgY / height) * rect.height,
    };
  }

  return (
    <div className="card" style={{ padding: 12, position: "relative" }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>VMAF Distribution</div>
      <svg ref={svgRef} width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="VMAF Histogram" onMouseLeave={() => setHover(null)}>
        {/* Grid */}
        {Array.from({ length: 4 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 3;
          return <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />;
        })}

        {counts.map((c, i) => {
          const x = xFor(i);
          const y = yFor(c);
          const h = margin.top + chartHeight - y;
          const labelFrom = Math.round(min + i * step);
          const labelTo = Math.round(min + (i + 1) * step);
          return (
            <g key={i} onMouseEnter={() => {
              const dom = svgToDom(x + barWidth / 2 + 8, y);
              setHover({ x: dom.x, y: dom.y, text: `${labelFrom}\u2013${labelTo}: ${c}` });
            }} onMouseLeave={() => setHover(null)}>
              <rect x={x} y={y} width={barWidth} height={h} fill="var(--accent-secondary)" rx={3} />
            </g>
          );
        })}

        {/* Axis */}
        <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="var(--border)" />
        {Array.from({ length: 5 }).map((_, i) => {
          const x = margin.left + (i * chartWidth) / 4;
          const value = min + ((max - min) * i) / 4;
          return (
            <text key={i} x={x} y={height - margin.bottom + 24} textAnchor="middle" fontSize={12} fill="var(--foreground)">
              {value.toFixed(0)}
            </text>
          );
        })}
        <text x={margin.left} y={margin.top - 8} fontSize={12} fill="var(--foreground)">VMAF</text>
      </svg>
      {/* Range sliders under chart */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 8 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="subtle" style={{ fontSize: 12 }}>Min VMAF</span>
          <input type="range" min={0} max={Math.max(0, range.max - 5)} step={1} value={range.min} onChange={e => setRange(r => ({ ...r, min: Math.min(Number(e.target.value), r.max - 5) }))} style={{ accentColor: "var(--accent)" }} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="subtle" style={{ fontSize: 12 }}>Max VMAF</span>
          <input type="range" min={Math.min(100, range.min + 5)} max={100} step={1} value={range.max} onChange={e => setRange(r => ({ ...r, max: Math.max(Number(e.target.value), r.min + 5) }))} style={{ accentColor: "var(--accent)" }} />
        </label>
      </div>
      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          {hover.text}
        </div>
      )}
    </div>
  );
}
