import type { Benchmark } from "./BenchmarksTable";

type Bar = {
  label: string;
  value: number;
};

function computeAverageFpsByCodec(rows: Benchmark[]): Bar[] {
  const sums = new Map<string, { total: number; count: number }>();
  for (const row of rows) {
    const key = row.codec;
    const current = sums.get(key) || { total: 0, count: 0 };
    current.total += Number(row.fps) || 0;
    current.count += 1;
    sums.set(key, current);
  }
  const bars: Bar[] = [];
  for (const [codec, agg] of sums.entries()) {
    if (agg.count > 0) {
      bars.push({ label: codec, value: agg.total / agg.count });
    }
  }
  bars.sort((a, b) => a.label.localeCompare(b.label));
  return bars;
}

export default function FpsByCodecChart({ data, title = "Average FPS by Codec" }: { data: Benchmark[]; title?: string }) {
  const bars = computeAverageFpsByCodec(data);
  if (bars.length === 0) return null;

  const width = 640;
  const height = 260;
  const margin = { top: 32, right: 16, bottom: 60, left: 48 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const maxValue = Math.max(...bars.map(b => b.value), 1);
  const barGap = 8;
  const barWidth = Math.max(4, (chartWidth - barGap * (bars.length - 1)) / bars.length);

  const xForIndex = (i: number) => margin.left + i * (barWidth + barGap);
  const yForValue = (v: number) => margin.top + chartHeight - (v / maxValue) * chartHeight;

  const axisColor = "#e5e7eb"; // gray-200
  const barColor = "#2563eb"; // blue-600
  const textColor = "#374151"; // gray-700

  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, marginTop: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>{title}</div>
      <svg width={width} height={height} role="img" aria-label={title}>
        {/* Y axis grid lines */}
        {Array.from({ length: 5 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke={axisColor} strokeWidth={1} />
          );
        })}

        {/* Bars */}
        {bars.map((b, i) => {
          const x = xForIndex(i);
          const y = yForValue(b.value);
          const h = margin.top + chartHeight - y;
          return <rect key={b.label} x={x} y={y} width={barWidth} height={h} fill={barColor} rx={3} />;
        })}

        {/* X axis labels */}
        {bars.map((b, i) => (
          <text
            key={b.label}
            x={xForIndex(i) + barWidth / 2}
            y={height - margin.bottom + 36}
            textAnchor="middle"
            fontSize={12}
            fill={textColor}
          >
            {b.label}
          </text>
        ))}

        {/* Y axis ticks */}
        {Array.from({ length: 5 }).map((_, i) => {
          const value = (maxValue * (4 - i)) / 4;
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <text key={i} x={margin.left - 8} y={y + 4} textAnchor="end" fontSize={12} fill={textColor}>
              {value.toFixed(0)}
            </text>
          );
        })}

        {/* Y axis title */}
        <text x={margin.left - 36} y={margin.top - 10} textAnchor="start" fontSize={12} fill={textColor}>
          FPS
        </text>
      </svg>
    </div>
  );
}


