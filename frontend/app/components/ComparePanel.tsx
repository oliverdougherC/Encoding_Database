"use client";

import { useEffect, useRef } from "react";
import type { Benchmark } from "./BenchmarksTable";
import { measurementBasis, artifactIntegrity, artifactRetention, hasPublicPl } from "../lib/evidence";
import styles from "./ComparePanel.module.css";

type CompareRow = Benchmark;

type Metric = {
  label: string;
  context?: "measurement" | "quality";
  getValue: (row: CompareRow) => string;
  getNumeric: (row: CompareRow) => number | null;
  higherIsBetter: boolean;
};

const METRICS: Metric[] = [
  { label: "CPU", getValue: r => r.cpuModel, getNumeric: () => null, higherIsBetter: true },
  { label: "GPU", getValue: r => r.gpuModel || "-", getNumeric: () => null, higherIsBetter: true },
  { label: "Encoder", getValue: r => r.encoderName, getNumeric: () => null, higherIsBetter: true },
  { label: "Preset", getValue: r => r.preset, getNumeric: () => null, higherIsBetter: true },
  { label: "Recipe fingerprint", getValue: r => r.recipe.fingerprint, getNumeric: () => null, higherIsBetter: true },
  { label: "Rate control", getValue: r => r.recipe.rateControl.label, getNumeric: () => null, higherIsBetter: true },
  { label: "Workload ID", getValue: r => r.workloadId, getNumeric: () => null, higherIsBetter: true },
  { label: "FPS", context: "measurement", getValue: r => r.performance.encodeFps == null ? "-" : r.performance.encodeFps.toFixed(2), getNumeric: r => r.performance.encodeFps, higherIsBetter: true },
  { label: "Realtime", context: "measurement", getValue: r => r.performance.realTimeRatio == null ? "-" : `${r.performance.realTimeRatio.toFixed(2)}x`, getNumeric: r => r.performance.realTimeRatio, higherIsBetter: true },
  { label: "VMAF", context: "quality", getValue: r => r.quality.vmafMean == null ? "-" : r.quality.vmafMean.toFixed(1), getNumeric: r => r.quality.vmafMean, higherIsBetter: true },
  { label: "VMAF p5", context: "quality", getValue: r => r.quality.vmafP5 == null ? "-" : r.quality.vmafP5.toFixed(1), getNumeric: r => r.quality.vmafP5, higherIsBetter: true },
  { label: "Bitrate (Mbps)", context: "measurement", getValue: r => r.bitrate.videoBitrateBps == null ? "-" : (r.bitrate.videoBitrateBps / 1_000_000).toFixed(2), getNumeric: r => r.bitrate.videoBitrateBps, higherIsBetter: false },
  { label: "File Size (MB)", context: "measurement", getValue: r => r.fileSizeBytes == null ? "-" : (r.fileSizeBytes / (1024 * 1024)).toFixed(2), getNumeric: r => r.fileSizeBytes, higherIsBetter: false },
  { label: "Measurement basis", getValue: measurementBasis, getNumeric: () => null, higherIsBetter: true },
  { label: "Artifact integrity", getValue: artifactIntegrity, getNumeric: () => null, higherIsBetter: true },
  { label: "Artifact retention", getValue: artifactRetention, getNumeric: () => null, higherIsBetter: true },
  { label: "Evidence tier", getValue: r => r.status.evidenceTier, getNumeric: () => null, higherIsBetter: true },
  { label: "PL status", getValue: r => hasPublicPl(r) ? "Public" : "Unavailable", getNumeric: () => null, higherIsBetter: true },
  { label: "Accepted runs", getValue: r => String(r.sampleCounts.accepted), getNumeric: () => null, higherIsBetter: true },
  { label: "Suspect runs", getValue: r => String(r.sampleCounts.suspect), getNumeric: () => null, higherIsBetter: true },
  { label: "Repetitions", getValue: r => String(r.sampleCounts.repetitions), getNumeric: () => null, higherIsBetter: true },
  { label: "Confidence", getValue: r => r.confidence.available ? `${r.confidence.lower?.toFixed(3)} to ${r.confidence.upper?.toFixed(3)}` : "Unavailable", getNumeric: () => null, higherIsBetter: true },
];

function findBestIndex(rows: CompareRow[], metric: Metric): number | null {
  if (!metric.context || !canCompareMetric(rows, metric.context)) return null;
  const numericVals = rows.map(r => metric.getNumeric(r));
  const nonNull = numericVals.filter(v => v != null && Number.isFinite(v));
  if (nonNull.length < 2) return null;
  if (nonNull.every(v => v === nonNull[0])) return null;

  let bestIdx: number | null = null;
  let bestVal: number | null = null;
  for (let i = 0; i < rows.length; i++) {
    const v = numericVals[i];
    if (v == null || !Number.isFinite(v)) continue;
    if (bestVal == null || (metric.higherIsBetter ? v > bestVal : v < bestVal)) {
      bestVal = v;
      bestIdx = i;
    }
  }
  return bestIdx;
}

// Recipes are the variables being compared. Exact workload, environment and
// measurement lineage must agree before emphasizing differences between them.
export function workloadIdentity(row: CompareRow): string {
  return JSON.stringify([row.workloadId, row.environment.fingerprint,
    row.versions.sourceSuiteVersion, row.versions.benchmarkProtocolId,
    row.versions.benchmarkProtocolVersion, row.versions.aggregatorVersion]);
}

export function hasIncompatibleWorkloads(rows: CompareRow[]): boolean {
  return rows.some(row => !row.workloadId || !row.environment.fingerprint ||
    !row.versions.sourceSuiteVersion || !row.versions.benchmarkProtocolId ||
    !row.versions.benchmarkProtocolVersion || !row.versions.aggregatorVersion) ||
    new Set(rows.map(workloadIdentity)).size > 1;
}

export function canCompareMetric(rows: CompareRow[], context: "measurement" | "quality"): boolean {
  if (rows.length < 2 || hasIncompatibleWorkloads(rows) || rows.some(row =>
    !["accepted", "eligible-stable-groups"].includes(row.status.centerBasis ?? "") || row.sampleCounts.accepted === 0)) return false;
  if (context === "measurement") return true;
  return rows.every(row => row.quality.qualityModelId && row.versions.analysisWorkerVersion) &&
    new Set(rows.map(row => JSON.stringify([row.quality.qualityModelId, row.versions.analysisWorkerVersion]))).size === 1;
}

export default function ComparePanel({
  rows,
  onClose,
  onClear,
}: {
  rows: CompareRow[];
  onClose: () => void;
  onClear: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const incompatible = hasIncompatibleWorkloads(rows);
  return (
    <div
      className={styles.panelBackdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="compare-panel-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.panel} ref={panelRef} tabIndex={-1}>
        <div className={styles.panelHeader}>
          <div id="compare-panel-title" className={styles.panelTitle}>
            Compare selected configurations
          </div>
          <div className={styles.panelActions}>
            <button type="button" onClick={onClear} className={`btn btn-ghost ${styles.clearBtn}`}>Clear All</button>
            <button type="button" onClick={onClose} className={`btn ${styles.clearBtn}`} aria-label="Close compare panel">Close</button>
          </div>
        </div>
        <div className={styles.panelBody}>
          {incompatible ? <p className={styles.compatibilityWarning}>Different workload, environment, or measurement protocol. Values are shown without winner highlights.</p> : null}
          {!incompatible && !canCompareMetric(rows, "measurement") ? <p className={styles.compatibilityWarning}>Suspect or unknown measurement basis. Values are shown for inspection only.</p> : null}
          {canCompareMetric(rows, "measurement") && !canCompareMetric(rows, "quality") ? <p className={styles.compatibilityWarning}>Quality model or analysis version differs or is unknown. Quality values have no winner highlights.</p> : null}
          <table className={styles.compareTable}>
            <thead>
              <tr>
                <th>Metric</th>
                {rows.map((r, i) => (
                  <th key={r.id}>Row {String.fromCharCode(65 + i)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map(metric => {
                const bestIdx = findBestIndex(rows, metric);
                return (
                  <tr key={metric.label}>
                    <td className={styles.metricCell}>{metric.label}</td>
                    {rows.map((r, i) => (
                      <td key={r.id} className={bestIdx === i ? styles.bestCell : undefined}>
                        {metric.getValue(r)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function CompareStickyBar({
  count,
  onCompare,
  onClear,
}: {
  count: number;
  onCompare: () => void;
  onClear: () => void;
}) {
  if (count < 2) return null;
  return (
    <div className={styles.stickyBar}>
      <button type="button" className={`btn btn-primary ${styles.compareBtn}`} onClick={onCompare}>
        Compare ({count})
      </button>
      <button type="button" className={`btn btn-ghost ${styles.clearBtn}`} onClick={onClear}>
        Clear Selection
      </button>
    </div>
  );
}
