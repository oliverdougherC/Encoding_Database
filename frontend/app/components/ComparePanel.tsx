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
  { label: "Encoder", getValue: r => r.encoderName || r.codec, getNumeric: () => null, higherIsBetter: true },
  { label: "CRF", getValue: r => r.crf == null ? "-" : String(r.crf), getNumeric: r => r.crf ?? null, higherIsBetter: false },
  { label: "Preset", getValue: r => r.preset, getNumeric: () => null, higherIsBetter: true },
  { label: "Content class", getValue: r => r.contentClass || "-", getNumeric: () => null, higherIsBetter: true },
  { label: "Resolution", getValue: r => r.resolution || "-", getNumeric: () => null, higherIsBetter: true },
  { label: "Passes", getValue: r => r.passes == null ? "-" : String(r.passes), getNumeric: () => null, higherIsBetter: true },
  { label: "FPS", getValue: r => r.fps.toFixed(2), getNumeric: r => r.fps, higherIsBetter: true },
  { label: "VMAF", getValue: r => r.vmaf == null ? "-" : r.vmaf.toFixed(1), getNumeric: r => r.vmaf, higherIsBetter: true },
  { label: "SSIM", getValue: r => r.ssim == null ? "-" : r.ssim.toFixed(4), getNumeric: r => r.ssim, higherIsBetter: true },
  { label: "PSNR (dB)", getValue: r => r.psnr == null ? "-" : r.psnr.toFixed(2), getNumeric: r => r.psnr, higherIsBetter: true },
  { label: "File Size (MB)", getValue: r => (r.fileSizeBytes / (1024 * 1024)).toFixed(2), getNumeric: r => r.fileSizeBytes, higherIsBetter: false },
  { label: "GPU Util (%)", getValue: r => r.gpuUtilAvg != null ? r.gpuUtilAvg.toFixed(1) : "-", getNumeric: r => r.gpuUtilAvg ?? null, higherIsBetter: true },
  { label: "GPU Power (W)", getValue: r => r.gpuPowerAvgW != null ? r.gpuPowerAvgW.toFixed(1) : "-", getNumeric: r => r.gpuPowerAvgW ?? null, higherIsBetter: false },
  { label: "FPS/Watt", getValue: r => r.fpsPerWatt != null ? r.fpsPerWatt.toFixed(2) : "-", getNumeric: r => r.fpsPerWatt ?? null, higherIsBetter: true },
  { label: "CPU Util (%)", getValue: r => r.cpuUtilAvg != null ? r.cpuUtilAvg.toFixed(1) : "-", getNumeric: r => r.cpuUtilAvg ?? null, higherIsBetter: false },
  { label: "Peak Memory (MB)", getValue: r => r.peakMemoryMB != null ? Math.round(r.peakMemoryMB).toString() : "-", getNumeric: r => r.peakMemoryMB ?? null, higherIsBetter: false },
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
  return [row.codec, row.preset, row.crf, row.contentClass, row.resolution, row.passes, row.inputHash]
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
          {incompatible ? <p className={styles.compatibilityWarning}>These configurations differ by codec, preset, CRF, content class, resolution, pass count, or canonical input. Their performance, size, and quality metrics are not directly comparable.</p> : null}
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
