"use client";

import { useMemo, useState } from "react";
import type { HardwareAnalyticsRow } from "../lib/types";
import styles from "./HardwareRecommendation.module.css";

type Priority = "speed" | "quality" | "efficiency" | "balanced";

type NormalizationMaxima = {
  maxFps: number;
  maxVmaf: number;
  maxEff: number;
};

export default function HardwareRecommendation({ data }: { data: HardwareAnalyticsRow[] }) {
  const [encoderFilter, setEncoderFilter] = useState("");
  const [priority, setPriority] = useState<Priority>("balanced");

  const encoders = useMemo(() => Array.from(new Set(data.map((d) => d.encoderName))).sort(), [data]);

  const recommendations = useMemo(() => {
    const results = encoderFilter ? data.filter((row) => row.encoderName === encoderFilter) : data.slice();

    if (priority === "speed") {
      results.sort((a, b) => b.avgFps - a.avgFps);
      return results.slice(0, 20);
    }

    if (priority === "quality") {
      results.sort((a, b) => (b.avgVmaf ?? 0) - (a.avgVmaf ?? 0));
      return results.slice(0, 20);
    }

    if (priority === "efficiency") {
      results.sort((a, b) => (b.fpsPerWatt ?? 0) - (a.fpsPerWatt ?? 0));
      return results.slice(0, 20);
    }

    const maxima = buildNormalizationMaxima(results);
    return results
      .map((hw) => ({ hw, score: normalizedScore(hw, maxima) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 20)
      .map((entry) => entry.hw);
  }, [data, encoderFilter, priority]);

  return (
    <div>
      <div className={styles.controlsRow}>
        <div>
          <label className={styles.label}>Encoder</label>
          <select className={`input ${styles.select}`} value={encoderFilter} onChange={e => setEncoderFilter(e.target.value)}>
            <option value="">All Encoders</option>
            {encoders.map((encoder) => <option key={encoder} value={encoder}>{encoder}</option>)}
          </select>
        </div>
        <div>
          <label className={styles.label}>Priority</label>
          <select className={`input ${styles.select}`} value={priority} onChange={e => setPriority(e.target.value as Priority)}>
            <option value="balanced">Balanced</option>
            <option value="speed">Speed (FPS)</option>
            <option value="quality">Quality (VMAF)</option>
            <option value="efficiency">Efficiency (FPS/Watt)</option>
          </select>
        </div>
      </div>

      {recommendations.length === 0 ? (
        <div className={styles.emptyState}>
          No benchmark data available for the selected filters.
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={`table ${styles.table}`}>
            <thead className="thead">
              <tr>
                <th className={`th ${styles.rankHead}`}>#</th>
                <th className="th">CPU</th>
                <th className="th">GPU</th>
                <th className={`th ${styles.numHead}`}>Avg FPS</th>
                <th className={`th ${styles.numHead}`}>Avg VMAF</th>
                <th className={`th ${styles.numHead}`}>Avg Power (W)</th>
                <th className={`th ${styles.numHead}`}>FPS/Watt</th>
                <th className={`th ${styles.numHead}`}>Samples</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.map((hw, i) => (
                <tr key={`${hw.cpuModel}-${hw.gpuModel}-${i}`}>
                  <td className={`td ${styles.rankCell} ${i < 3 ? styles.topRank : ""}`.trim()}>
                    {i + 1}
                  </td>
                  <td className="td">{hw.cpuModel}</td>
                  <td className="td">{hw.gpuModel || "-"}</td>
                  <td className={`td ${styles.numCell}`}>{hw.avgFps.toFixed(2)}</td>
                  <td className={`td ${styles.numCell}`}>{hw.avgVmaf != null ? hw.avgVmaf.toFixed(1) : "-"}</td>
                  <td className={`td ${styles.numCell}`}>{hw.avgPowerW != null ? hw.avgPowerW.toFixed(1) : "-"}</td>
                  <td className={`td ${styles.numCell}`}>{hw.fpsPerWatt != null ? hw.fpsPerWatt.toFixed(2) : "-"}</td>
                  <td className={`td ${styles.numCell}`}>{hw.sampleCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function buildNormalizationMaxima(all: HardwareAnalyticsRow[]): NormalizationMaxima {
  let maxFps = 1;
  let maxVmaf = 1;
  let maxEff = 1;
  for (const hw of all) {
    if (hw.avgFps > maxFps) maxFps = hw.avgFps;
    if (hw.avgVmaf != null && hw.avgVmaf > maxVmaf) maxVmaf = hw.avgVmaf;
    if (hw.fpsPerWatt != null && hw.fpsPerWatt > maxEff) maxEff = hw.fpsPerWatt;
  }
  return { maxFps, maxVmaf, maxEff };
}

function normalizedScore(hw: HardwareAnalyticsRow, maxima: NormalizationMaxima): number {
  const speedScore = hw.avgFps / maxima.maxFps;
  const qualityScore = hw.avgVmaf != null ? hw.avgVmaf / maxima.maxVmaf : 0.5;
  const effScore = hw.fpsPerWatt != null ? hw.fpsPerWatt / maxima.maxEff : 0.3;
  return 0.4 * speedScore + 0.35 * qualityScore + 0.25 * effScore;
}
