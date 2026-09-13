"use client";

import { useEffect, useRef } from "react";
import type { Benchmark } from "./BenchmarksTable";
import styles from "./ComparePanel.module.css";

type CompareRow = Benchmark;

type Metric = {
  label: string;
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
  { label: "FPS", getValue: r => r.performance.encodeFps == null ? "-" : r.performance.encodeFps.toFixed(2), getNumeric: r => r.performance.encodeFps, higherIsBetter: true },
  { label: "Realtime", getValue: r => r.performance.realTimeRatio == null ? "-" : `${r.performance.realTimeRatio.toFixed(2)}x`, getNumeric: r => r.performance.realTimeRatio, higherIsBetter: true },
  { label: "VMAF", getValue: r => r.quality.vmafMean == null ? "-" : r.quality.vmafMean.toFixed(1), getNumeric: r => r.quality.vmafMean, higherIsBetter: true },
  { label: "VMAF p5", getValue: r => r.quality.vmafP5 == null ? "-" : r.quality.vmafP5.toFixed(1), getNumeric: r => r.quality.vmafP5, higherIsBetter: true },
  { label: "Bitrate (Mbps)", getValue: r => r.bitrate.videoBitrateBps == null ? "-" : (r.bitrate.videoBitrateBps / 1_000_000).toFixed(2), getNumeric: r => r.bitrate.videoBitrateBps, higherIsBetter: false },
  { label: "File Size (MB)", getValue: r => r.fileSizeBytes == null ? "-" : (r.fileSizeBytes / (1024 * 1024)).toFixed(2), getNumeric: r => r.fileSizeBytes, higherIsBetter: false },
  { label: "Evidence tier", getValue: r => r.status.evidenceTier, getNumeric: () => null, higherIsBetter: true },
  { label: "PL status", getValue: r => r.status.scoring === "PUBLIC" ? "Public" : "Withheld", getNumeric: () => null, higherIsBetter: true },
  { label: "Accepted runs", getValue: r => String(r.sampleCounts.accepted), getNumeric: r => r.sampleCounts.accepted, higherIsBetter: true },
  { label: "Repetitions", getValue: r => String(r.sampleCounts.repetitions), getNumeric: r => r.sampleCounts.repetitions, higherIsBetter: true },
  { label: "Confidence", getValue: r => r.confidence.available ? `${r.confidence.lower?.toFixed(3)} to ${r.confidence.upper?.toFixed(3)}` : "Unavailable", getNumeric: () => null, higherIsBetter: true },
];

function findBestIndex(rows: CompareRow[], metric: Metric): number | null {
  const numericVals = rows.map(r => metric.getNumeric(r));
  const nonNull = numericVals.filter(v => v != null);
  if (nonNull.length < 2) return null;
  if (nonNull.every(v => v === nonNull[0])) return null;

  let bestIdx: number | null = null;
  let bestVal: number | null = null;
  for (let i = 0; i < rows.length; i++) {
    const v = numericVals[i];
    if (v == null) continue;
    if (bestVal == null || (metric.higherIsBetter ? v > bestVal : v < bestVal)) {
      bestVal = v;
      bestIdx = i;
    }
  }
  return bestIdx;
}

const normalizeIdentityPart = (value: string | number | null | undefined) => String(value ?? "").trim().toLowerCase();

export function workloadIdentity(row: CompareRow): string {
  return [row.workloadId, row.recipe.fingerprint, row.environment.fingerprint, row.versions.referenceContextVersion, row.versions.benchmarkProtocolVersion]
    .map(normalizeIdentityPart)
    .join("|");
}

export function hasIncompatibleWorkloads(rows: CompareRow[]): boolean {
  return new Set(rows.map(workloadIdentity)).size > 1;
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
          {incompatible ? <p className={styles.compatibilityWarning}>These configurations differ by workload, recipe fingerprint, environment fingerprint, or benchmark protocol lineage. Their performance, bitrate, and quality metrics are not directly comparable.</p> : null}
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
