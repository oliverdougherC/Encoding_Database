"use client";

import { useMemo, useState, useRef } from "react";
import type { Benchmark } from "./BenchmarksTable";
import styles from "./GroupedSizeByPreset.module.css";

type Group = {
  preset: string;
  codec: string;
  avgMB: number;
};

const CHART_COLORS = ["#6C8FD5", "#173B34", "#9693CC", "#d4a843", "#CDDBCD", "#8aabea"];

export default function GroupedSizeByPreset({ data }: { data: Benchmark[] }) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, { sum: number; count: number; preset: string; codec: string }>();
    for (const r of data) {
      const key = `${r.preset}|${r.codec}`;
      const g = map.get(key) || { sum: 0, count: 0, preset: r.preset, codec: r.codec };
      g.sum += r.fileSizeBytes;
      g.count += 1;
      map.set(key, g);
    }
    const out: Group[] = [];
    for (const g of map.values()) {
      out.push({ preset: g.preset, codec: g.codec, avgMB: (g.sum / Math.max(1, g.count)) / (1024 * 1024) });
    }
    out.sort((a, b) => a.preset.localeCompare(b.preset) || a.codec.localeCompare(b.codec));
    return out;
  }, [data]);

  const presets = Array.from(new Set(groups.map((g) => g.preset)));
  const codecs = Array.from(new Set(groups.map((g) => g.codec)));

  // O(1) lookup map instead of O(n) .find() per bar
  const groupMap = useMemo(() => {
    const m = new Map<string, Group>();
    for (const g of groups) m.set(`${g.preset}|${g.codec}`, g);
    return m;
  }, [groups]);

  const width = 720;
  const height = 320;
  const margin = { top: 24, right: 16, bottom: 64, left: 56 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const groupGap = 18;
  const barGap = 6;
  const barWidth = Math.max(4, (chartWidth - groupGap * (presets.length - 1)) / presets.length / Math.max(1, codecs.length) - barGap);
  const xStartForGroup = (i: number) => margin.left + i * ((barWidth + barGap) * codecs.length + groupGap);

  let maxValue = 1;
  for (const g of groups) if (g.avgMB > maxValue) maxValue = g.avgMB;
  const yFor = (v: number) => margin.top + chartHeight - (v / maxValue) * chartHeight;

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
    <div className={`card ${styles.chartCard}`} style={{ position: "relative" }}>
      <div className={styles.chartTitle}>Average File Size by Preset and Codec</div>
      <svg ref={svgRef} width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Grouped size by preset and codec" onMouseLeave={() => setHover(null)}>
        {/* Grid */}
        {Array.from({ length: 4 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 3;
          return <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />;
        })}

        {/* Bars */}
        {presets.map((p, pi) => {
          const x0 = xStartForGroup(pi);
          return codecs.map((c, ci) => {
            const g = groupMap.get(`${p}|${c}`);
            if (!g) return null; // Skip missing combinations
            const v = g.avgMB;
            const x = x0 + ci * (barWidth + barGap);
            const y = yFor(v);
            const h = margin.top + chartHeight - y;
            const color = CHART_COLORS[ci % CHART_COLORS.length];
            return (
              <g
                key={`${p}|${c}`}
                onMouseEnter={() => {
                  const dom = svgToDom(x + barWidth / 2 + 8, y - 8);
                  setHover({ x: dom.x, y: dom.y, text: `${p} \u2022 ${c}: ${v.toFixed(2)} MB` });
                }}
                onMouseLeave={() => setHover(null)}
              >
                <rect x={x} y={y} width={barWidth} height={h} fill={color} rx={3} style={{ cursor: "pointer" }} />
              </g>
            );
          });
        })}

        {/* X axis labels */}
        {presets.map((p, pi) => {
          const x = xStartForGroup(pi) + ((barWidth + barGap) * codecs.length - barGap) / 2;
          return (
            <text key={p} x={x} y={height - margin.bottom + 40} textAnchor="middle" fontSize={12} fill="var(--foreground)">
              {p}
            </text>
          );
        })}

        {/* Y axis */}
        <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="var(--border)" />
        {Array.from({ length: 5 }).map((_, i) => {
          const value = (maxValue * (4 - i)) / 4;
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <text key={i} x={margin.left - 10} y={y + 4} textAnchor="end" fontSize={12} fill="var(--foreground)">
              {value.toFixed(1)} MB
            </text>
          );
        })}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          {hover.text}
        </div>
      )}

      {/* Legend */}
      <div className={`subtle ${styles.legend}`}>
        {codecs.map((c, i) => (
          <div key={c} className={styles.legendItem}>
            <span className={styles.legendSwatch} style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
            <span>{c}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
