"use client";

import { useMemo, useState } from "react";
import type { Benchmark } from "./BenchmarksTable";

type HardwareProfile = {
  cpuModel: string;
  gpuModel: string;
  avgFps: number;
  avgVmaf: number | null;
  avgPower: number | null;
  fpsPerWatt: number | null;
  samples: number;
};

type Priority = "speed" | "quality" | "efficiency" | "balanced";

const PROFILE_KEY_SEP = "\u241F"; // unit separator — safe for CPU/GPU model names

export default function HardwareRecommendation({ data }: { data: Benchmark[] }) {
  const [codec, setCodec] = useState("");
  const [priority, setPriority] = useState<Priority>("balanced");

  const codecs = useMemo(() => Array.from(new Set(data.map(d => d.codec))).sort(), [data]);

  const recommendations = useMemo(() => {
    const filtered = codec ? data.filter(d => d.codec === codec) : data;
    const profiles = new Map<string, { fps: number[]; vmaf: number[]; power: number[] }>();

    for (const row of filtered) {
      if (row.fps <= 0) continue;
      const key = [row.cpuModel, row.gpuModel ?? ""].join(PROFILE_KEY_SEP);
      if (!profiles.has(key)) profiles.set(key, { fps: [], vmaf: [], power: [] });
      const p = profiles.get(key)!;
      p.fps.push(row.fps);
      if (row.vmaf != null) p.vmaf.push(row.vmaf);
      const power = row.gpuPowerAvgW;
      if (typeof power === "number" && power > 0) p.power.push(power);
    }

    const results: HardwareProfile[] = [];
    for (const [key, p] of profiles.entries()) {
      const [cpuModel, gpuModel] = key.split(PROFILE_KEY_SEP);
      const avgFps = p.fps.reduce((a, b) => a + b, 0) / p.fps.length;
      const avgVmaf = p.vmaf.length > 0 ? p.vmaf.reduce((a, b) => a + b, 0) / p.vmaf.length : null;
      const avgPower = p.power.length > 0 ? p.power.reduce((a, b) => a + b, 0) / p.power.length : null;
      const fpsPerWatt = avgPower != null && avgPower > 0 ? avgFps / avgPower : null;
      results.push({ cpuModel, gpuModel, avgFps, avgVmaf, avgPower, fpsPerWatt, samples: p.fps.length });
    }

    results.sort((a, b) => {
      switch (priority) {
        case "speed":
          return b.avgFps - a.avgFps;
        case "quality":
          return (b.avgVmaf ?? 0) - (a.avgVmaf ?? 0);
        case "efficiency":
          return (b.fpsPerWatt ?? 0) - (a.fpsPerWatt ?? 0);
        case "balanced":
        default: {
          const scoreA = normalizedScore(a, results);
          const scoreB = normalizedScore(b, results);
          return scoreB - scoreA;
        }
      }
    });

    return results.slice(0, 20);
  }, [data, codec, priority]);

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div>
          <label style={{ display: "block", fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Codec</label>
          <select className="input" value={codec} onChange={e => setCodec(e.target.value)} style={{ minWidth: 160 }}>
            <option value="">All Codecs</option>
            {codecs.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label style={{ display: "block", fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Priority</label>
          <select className="input" value={priority} onChange={e => setPriority(e.target.value as Priority)} style={{ minWidth: 160 }}>
            <option value="balanced">Balanced</option>
            <option value="speed">Speed (FPS)</option>
            <option value="quality">Quality (VMAF)</option>
            <option value="efficiency">Efficiency (FPS/Watt)</option>
          </select>
        </div>
      </div>

      {recommendations.length === 0 ? (
        <div style={{ color: "var(--muted)", padding: "24px 0", textAlign: "center" }}>
          No benchmark data available for the selected filters.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead className="thead">
              <tr>
                <th className="th" style={{ textAlign: "center", width: 40 }}>#</th>
                <th className="th">CPU</th>
                <th className="th">GPU</th>
                <th className="th" style={{ textAlign: "right" }}>Avg FPS</th>
                <th className="th" style={{ textAlign: "right" }}>Avg VMAF</th>
                <th className="th" style={{ textAlign: "right" }}>Avg Power (W)</th>
                <th className="th" style={{ textAlign: "right" }}>FPS/Watt</th>
                <th className="th" style={{ textAlign: "right" }}>Samples</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.map((hw, i) => (
                <tr key={`${hw.cpuModel}-${hw.gpuModel}-${i}`}>
                  <td className="td" style={{ textAlign: "center", fontWeight: 600, color: i < 3 ? "var(--accent)" : "var(--foreground)" }}>
                    {i + 1}
                  </td>
                  <td className="td">{hw.cpuModel}</td>
                  <td className="td">{hw.gpuModel || "-"}</td>
                  <td className="td" style={{ textAlign: "right" }}>{hw.avgFps.toFixed(2)}</td>
                  <td className="td" style={{ textAlign: "right" }}>{hw.avgVmaf != null ? hw.avgVmaf.toFixed(1) : "-"}</td>
                  <td className="td" style={{ textAlign: "right" }}>{hw.avgPower != null ? hw.avgPower.toFixed(1) : "-"}</td>
                  <td className="td" style={{ textAlign: "right" }}>{hw.fpsPerWatt != null ? hw.fpsPerWatt.toFixed(2) : "-"}</td>
                  <td className="td" style={{ textAlign: "right" }}>{hw.samples}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function normalizedScore(hw: HardwareProfile, all: HardwareProfile[]): number {
  let maxFps = 1, maxVmaf = 1, maxEff = 1;
  for (const h of all) {
    if (h.avgFps > maxFps) maxFps = h.avgFps;
    if (h.avgVmaf != null && h.avgVmaf > maxVmaf) maxVmaf = h.avgVmaf;
    if (h.fpsPerWatt != null && h.fpsPerWatt > maxEff) maxEff = h.fpsPerWatt;
  }
  const speedScore = hw.avgFps / maxFps;
  const qualityScore = hw.avgVmaf != null ? hw.avgVmaf / maxVmaf : 0.5;
  const effScore = hw.fpsPerWatt != null ? hw.fpsPerWatt / maxEff : 0.3;
  return 0.4 * speedScore + 0.35 * qualityScore + 0.25 * effScore;
}
