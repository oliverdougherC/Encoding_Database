"use client";

import { useEffect, useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { useChartTheme } from "../lib/useChartTheme";
import { escapeHtml } from "../lib/escapeHtml";
import EChart from "./EChart";

const CONTENT_CLASSES = ["mixed", "talkingHead", "action", "animation", "screen", "nature", "gaming"] as const;
const CONTENT_LABELS: Record<string, string> = {
  mixed: "Mixed",
  talkingHead: "Talking Head",
  action: "Action",
  animation: "Animation",
  screen: "Screen",
  nature: "Nature",
  gaming: "Gaming",
};
const COLORS = ["#6C8FD5", "#52b788", "#9693CC", "#d4a843", "#e07a5f", "#8aabea"];
const MAX_SELECTOR = 10;
const MAX_SELECTED = 6;

type CodecData = { codec: string; samples: number; scores: Record<string, number> };

function computeCodecScores(data: Benchmark[]): CodecData[] {
  const map = new Map<string, Map<string, { vmafSum: number; count: number }>>();
  for (const row of data) {
    if (typeof row.vmaf !== "number") continue;
    const cc = row.contentClass ?? "mixed";
    if (!map.has(row.codec)) map.set(row.codec, new Map());
    const ccMap = map.get(row.codec)!;
    if (!ccMap.has(cc)) ccMap.set(cc, { vmafSum: 0, count: 0 });
    const e = ccMap.get(cc)!;
    e.vmafSum += row.vmaf;
    e.count += 1;
  }
  return Array.from(map.entries())
    .map(([codec, ccMap]) => {
      const scores: Record<string, number> = {};
      let samples = 0;
      for (const cc of CONTENT_CLASSES) {
        const e = ccMap.get(cc);
        scores[cc] = e && e.count > 0 ? e.vmafSum / e.count : 0;
        if (e) samples += e.count;
      }
      return { codec, samples, scores };
    })
    .sort((a, b) => b.samples - a.samples || a.codec.localeCompare(b.codec));
}

export default function ContentRadarChart({ data, title = "Encoder Quality by Content Class" }: { data: Benchmark[]; title?: string }) {
  const t = useChartTheme();
  const allCodecs = useMemo(() => computeCodecScores(data), [data]);
  const options = useMemo(() => allCodecs.slice(0, MAX_SELECTOR), [allCodecs]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(allCodecs.slice(0, 4).map((d) => d.codec)));

  useEffect(() => {
    if (options.length === 0) return;
    setSelected((prev) => {
      const allowed = new Set(options.map((d) => d.codec));
      const next = new Set(Array.from(prev).filter((c) => allowed.has(c)));
      if (next.size === 0) options.slice(0, 4).forEach((d) => next.add(d.codec));
      return next.size > MAX_SELECTED ? new Set(Array.from(next).slice(0, MAX_SELECTED)) : next;
    });
  }, [options]);

  const activeClasses = useMemo(() => {
    const seen = new Set(data.map((r) => r.contentClass ?? "mixed"));
    return CONTENT_CLASSES.filter((cc) => seen.has(cc));
  }, [data]);

  const colorByCodec = useMemo(
    () => new Map(options.map((entry, i) => [entry.codec, COLORS[i % COLORS.length]])),
    [options],
  );

  const selectedData = options.filter((d) => selected.has(d.codec));

  const option = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.fg, fontSize: 12 },
      formatter: (params: { name: string; value: number[] }) => {
        const lines = activeClasses
          .map((cc, i) => `${CONTENT_LABELS[cc] ?? cc}: <b>${(params.value[i] || 0).toFixed(1)}</b>`)
          .join("<br/>");
        return `<b>${escapeHtml(params.name)}</b><br/>${lines}`;
      },
    },
    radar: {
      indicator: activeClasses.map((cc) => ({ name: CONTENT_LABELS[cc] ?? cc, max: 100 })),
      splitLine: { lineStyle: { color: t.border } },
      axisLine: { lineStyle: { color: t.border } },
      splitArea: { show: false },
      axisName: { color: t.fg, fontSize: 11 },
      center: ["50%", "50%"],
      radius: "68%",
    },
    series: [
      {
        type: "radar",
        data: selectedData.map((cd) => ({
          name: cd.codec,
          value: activeClasses.map((cc) => cd.scores[cc] || 0),
          lineStyle: { color: colorByCodec.get(cd.codec) ?? COLORS[0], width: 2 },
          areaStyle: { color: colorByCodec.get(cd.codec) ?? COLORS[0], opacity: 0.12 },
          itemStyle: { color: colorByCodec.get(cd.codec) ?? COLORS[0] },
          symbol: "circle",
          symbolSize: 4,
        })),
      },
    ],
  }), [selectedData, activeClasses, colorByCodec, t]);

  if (allCodecs.length === 0 || activeClasses.length < 3) return null;

  const toggle = (codec: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(codec)) { next.delete(codec); }
      else if (next.size < MAX_SELECTED) { next.add(codec); }
      return next;
    });
  };

  return (
    <div className="card" style={{ padding: 12, height: "100%", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      <div style={{ fontWeight: 600, marginBottom: 8, flex: "0 0 auto" }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 8, flex: "0 0 auto" }}>
        {options.map((entry) => {
          const isOn = selected.has(entry.codec);
          const disabled = !isOn && selected.size >= MAX_SELECTED;
          const color = colorByCodec.get(entry.codec) ?? COLORS[0];
          return (
            <button
              key={entry.codec}
              type="button"
              title={`${entry.codec} (${entry.samples} samples)`}
              onClick={() => !disabled && toggle(entry.codec)}
              style={{
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 11,
                border: `1.5px solid ${isOn ? color : "var(--border)"}`,
                background: isOn ? `color-mix(in srgb, ${color} 18%, var(--surface))` : "transparent",
                color: "var(--foreground)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.4 : 1,
              }}
            >
              {entry.codec}
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}><EChart option={option} /></div>
    </div>
  );
}
