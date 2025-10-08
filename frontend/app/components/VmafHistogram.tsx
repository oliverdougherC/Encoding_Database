"use client";

import type { Benchmark } from "./BenchmarksTable";

import { useRef, useState } from "react";

export default function VmafHistogram({ data, bins = 10 }: { data: Benchmark[]; bins?: number }) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [range, setRange] = useState<{ min: number; max: number }>({ min: 0, max: 100 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const values = data.map((d) => typeof d.vmaf === "number" ? Math.max(0, Math.min(100, d.vmaf)) : null).filter((v): v is number => v != null);
  if (values.length === 0) return null;

  const min = range.min;
  const max = range.max;
  const step = (max - min) / bins;
  const counts = new Array(bins).fill(0) as number[];
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.floor((v - min) / step));
    counts[idx] += 1;
  }
  const maxCount = Math.max(...counts, 1);

  const width = 720;
  const height = 280;
  const margin = { top: 24, right: 16, bottom: 40, left: 40 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  const barGap = 2;
  const barWidth = (chartWidth - barGap * (bins - 1)) / bins;
  const xFor = (i: number) => margin.left + i * (barWidth + barGap);
  const yFor = (c: number) => margin.top + chartHeight - (c / maxCount) * chartHeight;

  function onWheel(e: React.WheelEvent<SVGSVGElement>) {
    e.preventDefault();
    const zoom = e.deltaY > 0 ? 1.1 : 0.9;
    const mid = (range.min + range.max) / 2;
    const half = ((range.max - range.min) / 2) * zoom;
    const nextMin = Math.max(0, mid - half);
    const nextMax = Math.min(100, mid + half);
    if (nextMax - nextMin >= 5) setRange({ min: nextMin, max: nextMax });
  }

  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>VMAF Distribution</div>
      <svg ref={svgRef} width={width} height={height} role="img" aria-label="VMAF Histogram" onWheel={onWheel} onMouseLeave={() => setHover(null)}>
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
            <g key={i} onMouseMove={(e) => setHover({ x: x + barWidth / 2 + 8, y, text: `${labelFrom}–${labelTo}: ${c}` })}>
              <rect x={x} y={y} width={barWidth} height={h} fill="#2563eb" rx={3} />
            </g>
          );
        })}

        {/* Axis */}
        <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="var(--border)" />
        {Array.from({ length: 5 }).map((_, i) => {
          const x = margin.left + (i * chartWidth) / 4;
          const value = (max * i) / 4;
          return (
            <text key={i} x={x} y={height - margin.bottom + 24} textAnchor="middle" fontSize={12} fill="var(--foreground)">
              {value.toFixed(0)}
            </text>
          );
        })}
        <text x={margin.left} y={margin.top - 8} fontSize={12} fill="var(--foreground)">VMAF</text>
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          {hover.text}
        </div>
      )}
    </div>
  );
}


