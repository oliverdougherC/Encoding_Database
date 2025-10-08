"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";

type Group = {
  preset: string;
  codec: string;
  avgMB: number;
};

export default function GroupedSizeByPreset({ data }: { data: Benchmark[] }) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
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
  const colors = ["#2563eb", "#10b981", "#a855f7", "#f59e0b", "#ef4444", "#22c55e"];

  const width = 720;
  const height = 320;
  const margin = { top: 24, right: 16, bottom: 64, left: 56 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const groupGap = 18;
  const barGap = 6;
  const barWidth = Math.max(4, (chartWidth - groupGap * (presets.length - 1)) / presets.length / Math.max(1, codecs.length) - barGap);
  const xStartForGroup = (i: number) => margin.left + i * ((barWidth + barGap) * codecs.length + groupGap);

  const maxValue = Math.max(1, ...groups.map((g) => g.avgMB));
  const yFor = (v: number) => margin.top + chartHeight - (v / maxValue) * chartHeight;

  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>Average File Size by Preset and Codec</div>
      <svg width={width} height={height} role="img" aria-label="Grouped size by preset and codec">
        {/* Grid */}
        {Array.from({ length: 4 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 3;
          return <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />;
        })}

        {/* Bars */}
        {presets.map((p, pi) => {
          const x0 = xStartForGroup(pi);
          return codecs.map((c, ci) => {
            const g = groups.find((g) => g.preset === p && g.codec === c);
            const v = g ? g.avgMB : 0;
            const x = x0 + ci * (barWidth + barGap);
            const y = yFor(v);
            const h = margin.top + chartHeight - y;
            const color = colors[ci % colors.length];
            return (
              <g key={`${p}|${c}`} onMouseMove={() => setHover({ x: x + barWidth / 2 + 8, y, text: `${p} • ${c}: ${v.toFixed(2)} MB` })} onMouseLeave={() => setHover(null)}>
                <rect x={x} y={y} width={barWidth} height={h} fill={color} rx={3} />
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
      <div className="subtle" style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
        {codecs.map((c, i) => (
          <div key={c} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 12, height: 12, background: colors[i % colors.length], borderRadius: 3, display: "inline-block" }} />
            <span>{c}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


