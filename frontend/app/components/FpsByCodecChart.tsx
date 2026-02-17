import type { Benchmark } from "./BenchmarksTable";

type Bar = {
  label: string;
  value: number;
};

const CHART_COLORS = ["#6C8FD5", "#173B34", "#9693CC", "#d4a843", "#CDDBCD", "#8aabea"];

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

  const height = 280;
  const margin = { top: 32, right: 16, bottom: 80, left: 48 };
  const chartHeight = height - margin.top - margin.bottom;
  let maxValue = 1;
  for (const b of bars) if (b.value > maxValue) maxValue = b.value;
  const barGap = 8;
  const minBarWidth = 40;
  const neededWidth = bars.length * (minBarWidth + barGap) - barGap;
  const chartWidth = Math.max(576, neededWidth);
  const width = chartWidth + margin.left + margin.right;
  const barWidth = (chartWidth - barGap * (bars.length - 1)) / bars.length;

  const xForIndex = (i: number) => margin.left + i * (barWidth + barGap);
  const yForValue = (v: number) => margin.top + chartHeight - (v / maxValue) * chartHeight;

  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>{title}</div>
      <div style={{ overflowX: "auto" }}>
      <svg width="100%" style={{ minWidth: width }} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        {/* Y axis grid lines */}
        {Array.from({ length: 5 }).map((_, i) => {
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <line key={i} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />
          );
        })}

        {/* Bars */}
        {bars.map((b, i) => {
          const x = xForIndex(i);
          const y = yForValue(b.value);
          const h = margin.top + chartHeight - y;
          return <rect key={b.label} x={x} y={y} width={barWidth} height={h} fill={CHART_COLORS[i % CHART_COLORS.length]} rx={3} />;
        })}

        {/* X axis labels */}
        {bars.map((b, i) => {
          const cx = xForIndex(i) + barWidth / 2;
          const cy = height - margin.bottom + 16;
          return (
            <text
              key={b.label}
              x={cx}
              y={cy}
              textAnchor="end"
              fontSize={12}
              fill="var(--foreground)"
              transform={`rotate(-40, ${cx}, ${cy})`}
            >
              {b.label}
            </text>
          );
        })}

        {/* Y axis ticks */}
        {Array.from({ length: 5 }).map((_, i) => {
          const value = (maxValue * (4 - i)) / 4;
          const y = margin.top + (i * chartHeight) / 4;
          return (
            <text key={i} x={margin.left - 8} y={y + 4} textAnchor="end" fontSize={12} fill="var(--muted)">
              {value.toFixed(0)}
            </text>
          );
        })}

        {/* Y axis title */}
        <text x={margin.left - 36} y={margin.top - 10} textAnchor="start" fontSize={12} fill="var(--foreground)">
          FPS
        </text>
      </svg>
      </div>
    </div>
  );
}
