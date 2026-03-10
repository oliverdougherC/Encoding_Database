"use client";

import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";
import styles from "./BenchmarksTable.module.css";
import ComparePanel, { CompareStickyBar } from "./ComparePanel";
import { formatCodecLabel } from "./codecLabel";
import type { Benchmark } from "../lib/types";
import { createPlScoreContext, scorePlBenchmarkV6 } from "../lib/plScore";

export type { Benchmark } from "../lib/types";

const PAGE_SIZE = 50;
const COL_WIDTHS = "minmax(38px,0.45fr) minmax(72px,0.9fr) minmax(170px,2fr) minmax(170px,2fr) minmax(130px,1.5fr) minmax(58px,0.7fr) minmax(108px,1.15fr) minmax(96px,1.05fr) minmax(78px,0.85fr) minmax(56px,0.7fr)";

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

// Intermediate type with per-row metrics (expensive computation, cached separately)
type PerRowMetrics = Benchmark & {
  _q: number;       // quality component
  _s: number;       // size component
  _sp: number;      // speed component
  _eff: number;     // efficiency component
  _rel: number;     // reliability component
  _confidence: number;
  _relSize: number;
  _codecLabel: string;
  _isHardware: boolean;
};

// Extended type for benchmarks with computed scores
type EnrichedBenchmark = PerRowMetrics & {
  _plScore: number;
};

type SortKey = "cpuModel" | "gpuModel" | "codec" | "crf" | "preset" | "_plScore";

export default function BenchmarksTable({ initialData }: { initialData: Benchmark[] }) {
  const searchParams = useSearchParams();
  const isInitRef = useRef(false);

  const [cpuFilter, setCpuFilter] = useState(() => searchParams.get("cpu") || "");
  const [gpuFilter, setGpuFilter] = useState(() => searchParams.get("gpu") || "");
  const [codecFilter, setCodecFilter] = useState(() => searchParams.get("codec") || "");
  const [presetFilter, setPresetFilter] = useState(() => searchParams.get("preset") || "");
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const s = searchParams.get("sort");
    if (s === "_plove") return "_plScore"; // backward compatibility with older links
    if (s && ["cpuModel", "gpuModel", "codec", "crf", "preset", "_plScore"].includes(s)) return s as SortKey;
    return "_plScore";
  });
  const [sortDir, setSortDir] = useState<"asc" | "desc">(() => {
    const d = searchParams.get("dir");
    return d === "asc" ? "asc" : "desc";
  });
  // Encoder type filters
  const [softwareOnly, setSoftwareOnly] = useState<boolean>(() => searchParams.get("sw") === "1");
  const [hardwareOnly, setHardwareOnly] = useState<boolean>(() => searchParams.get("hw") === "1");

  // Sync filter state to URL search params using native replaceState (F-07)
  const urlDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!isInitRef.current) { isInitRef.current = true; return; }
    if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current);
    urlDebounceRef.current = setTimeout(() => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams();
      if (cpuFilter) params.set("cpu", cpuFilter);
      if (gpuFilter) params.set("gpu", gpuFilter);
      if (codecFilter) params.set("codec", codecFilter);
      if (presetFilter) params.set("preset", presetFilter);
      if (sortKey !== "_plScore") params.set("sort", sortKey);
      if (sortDir !== "desc") params.set("dir", sortDir);
      if (softwareOnly) params.set("sw", "1");
      if (hardwareOnly) params.set("hw", "1");
      const qs = params.toString();
      const base = window.location.pathname;
      window.history.replaceState(null, "", qs ? `${base}?${qs}` : base);
    }, 300);
    return () => { if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current); };
  }, [cpuFilter, gpuFilter, codecFilter, presetFilter, sortKey, sortDir, softwareOnly, hardwareOnly]);

  // Core PL Score v6 weights (sum normalized to 1.0)
  const [wQuality, setWQuality] = useState<number>(1 / 3);
  const [wSize, setWSize] = useState<number>(1 / 3);
  const [wSpeed, setWSpeed] = useState<number>(1 / 3);
  // UI sliders that users can adjust freely; applied via Apply button
  const [uiQuality, setUiQuality] = useState<number>(1 / 3);
  const [uiSize, setUiSize] = useState<number>(1 / 3);
  const [uiSpeed, setUiSpeed] = useState<number>(1 / 3);
  // Batch weight resets using a single callback to minimize re-renders
  const resetWeights = useCallback(() => {
    const defaultWeight = 1 / 3;
    setWQuality(defaultWeight);
    setWSize(defaultWeight);
    setWSpeed(defaultWeight);
    setUiQuality(defaultWeight);
    setUiSize(defaultWeight);
    setUiSpeed(defaultWeight);
  }, []);
  const [showDetailId, setShowDetailId] = useState<string | null>(null);
  const [showFfmpegId, setShowFfmpegId] = useState<string | null>(null);
  // Compare mode
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showCompare, setShowCompare] = useState(false);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else if (next.size < 6) { next.add(id); }
      return next;
    });
  }, []);
  const clearSelection = useCallback(() => { setSelectedIds(new Set()); setShowCompare(false); }, []);
  const [page, setPage] = useState(0);

  // Reset page when any filter changes
  useEffect(() => {
    setPage(0);
  }, [cpuFilter, gpuFilter, codecFilter, presetFilter, softwareOnly, hardwareOnly]);

  const codecs = useMemo(() => Array.from(new Set(initialData.map(d => d.codec))).sort(), [initialData]);
  const presets = useMemo(() => Array.from(new Set(initialData.map(d => d.preset))).sort(), [initialData]);
  const filteredPresets = useMemo(() => {
    if (!codecFilter) return presets;
    const lower = codecFilter.toLowerCase();
    const matching = initialData.filter(r => r.codec.toLowerCase().includes(lower));
    return Array.from(new Set(matching.map(r => r.preset))).sort();
  }, [initialData, codecFilter, presets]);

  const activeFilterChips = useMemo(() => {
    const chips: Array<{ key: string; label: string; clear: () => void }> = [];
    if (cpuFilter) chips.push({ key: "cpu", label: `CPU: ${cpuFilter}`, clear: () => setCpuFilter("") });
    if (gpuFilter) chips.push({ key: "gpu", label: `GPU: ${gpuFilter}`, clear: () => setGpuFilter("") });
    if (codecFilter) chips.push({ key: "codec", label: `Codec: ${codecFilter}`, clear: () => setCodecFilter("") });
    if (presetFilter) chips.push({ key: "preset", label: `Preset: ${presetFilter}`, clear: () => setPresetFilter("") });
    if (softwareOnly) chips.push({ key: "sw", label: "Software Only", clear: () => setSoftwareOnly(false) });
    if (hardwareOnly) chips.push({ key: "hw", label: "Hardware Only", clear: () => setHardwareOnly(false) });
    return chips;
  }, [cpuFilter, gpuFilter, codecFilter, presetFilter, softwareOnly, hardwareOnly]);

  const resetAllFilters = useCallback(() => {
    setCpuFilter("");
    setGpuFilter("");
    setCodecFilter("");
    setPresetFilter("");
    setSoftwareOnly(false);
    setHardwareOnly(false);
  }, []);

  // Pre-compute hardware encoder classification once per row to avoid repeated regex tests
  const dataWithHwClass = useMemo(() => {
    return initialData.map(row => {
      const encLower = (row.encoderName ?? row.codec ?? "").toLowerCase();
      return { ...row, _isHardware: isHardwareEncoder(encLower) };
    });
  }, [initialData]);

  const filtered = useMemo(() => {
    const cpu = cpuFilter.trim().toLowerCase();
    const gpu = gpuFilter.trim().toLowerCase();
    return dataWithHwClass.filter(row => {
      if (cpu && !row.cpuModel.toLowerCase().includes(cpu)) return false;
      if (gpu && !(row.gpuModel ?? "").toLowerCase().includes(gpu)) return false;
      if (codecFilter && !row.codec.toLowerCase().includes(codecFilter.toLowerCase())) return false;
      if (presetFilter && row.preset !== presetFilter) return false;
      if (softwareOnly && !hardwareOnly) return !row._isHardware;
      if (hardwareOnly && !softwareOnly) return row._isHardware;
      return true;
    });
  }, [dataWithHwClass, cpuFilter, gpuFilter, codecFilter, presetFilter, softwareOnly, hardwareOnly]);

  const plContext = useMemo(() => createPlScoreContext(filtered), [filtered]);

  // Stage 1: compute PL Score v6 components that are independent from user weights
  const perRowMetrics = useMemo((): PerRowMetrics[] => {
    return filtered.map((row): PerRowMetrics => {
      const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / plContext.sizeBaseline : 1;
      const encoder = (row.encoderName ?? row.codec ?? "").toLowerCase();
      const codecLabel = formatCodecLabel(encoder);
      const scored = scorePlBenchmarkV6(row, plContext, { quality: 1 / 3, size: 1 / 3, speed: 1 / 3 });
      return {
        ...row,
        _q: scored.quality,
        _s: scored.size,
        _sp: scored.speed,
        _eff: scored.efficiency,
        _rel: scored.reliability,
        _confidence: scored.measurementConfidence,
        _relSize: relSize,
        _codecLabel: codecLabel,
      };
    });
  }, [filtered, plContext]);

  // Stage 2: recompute final PL score when weights change
  const withScores = useMemo((): EnrichedBenchmark[] => {
    const weightSum = Math.max(0.0001, wQuality + wSize + wSpeed);
    const normalizedQuality = wQuality / weightSum;
    const normalizedSize = wSize / weightSum;
    const normalizedSpeed = wSpeed / weightSum;
    return perRowMetrics.map((row): EnrichedBenchmark => {
      const core = clamp(
        normalizedQuality * row._q + normalizedSize * row._s + normalizedSpeed * row._sp,
        0,
        100,
      );
      const confidenceAdj = (row._confidence - 0.7) * 6;
      const total = clamp(core * 0.78 + row._eff * 0.14 + row._rel * 0.08 + confidenceAdj, 0, 100);
      return { ...row, _plScore: total };
    });
  }, [perRowMetrics, wQuality, wSize, wSpeed]);

  const sorted = useMemo((): EnrichedBenchmark[] => {
    const data = [...withScores];
    data.sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      const getValue = (row: EnrichedBenchmark): string | number | null => {
        if (sortKey === "codec") return row._codecLabel;
        if (sortKey === "_plScore") return row._plScore;
        return row[sortKey] ?? null;
      };
      const av = getValue(a);
      const bv = getValue(b);
      if (av == null && bv != null) return 1 * mul;
      if (av != null && bv == null) return -1 * mul;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mul;
      const as = String(av);
      const bs = String(bv);
      return as.localeCompare(bs) * mul;
    });
    return data;
  }, [withScores, sortKey, sortDir]);

  // Keep selections in-sync with currently visible filtered dataset.
  useEffect(() => {
    const allowed = new Set(sorted.map(row => row.id));
    setSelectedIds(prev => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (allowed.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [sorted]);

  const totalRows = sorted.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  useEffect(() => {
    if (page >= totalPages) {
      setPage(Math.max(0, totalPages - 1));
    }
  }, [page, totalPages]);

  const pagedRows = useMemo(() => {
    const start = page * PAGE_SIZE;
    return sorted.slice(start, start + PAGE_SIZE);
  }, [sorted, page]);

  const compareRows = useMemo(() => sorted.filter(r => selectedIds.has(r.id)), [sorted, selectedIds]);

  const setSort = (key: SortKey) => {
    if (key === sortKey) setSortDir(d => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  function applyWeightsFromUI() {
    const sum = uiQuality + uiSize + uiSpeed;
    if (sum <= 0) {
      // All sliders at zero: reset to equal weights (B-F02)
      const d = 1 / 3;
      setWQuality(d);
      setWSize(d);
      setWSpeed(d);
      setUiQuality(d);
      setUiSize(d);
      setUiSpeed(d);
      return;
    }
    setWQuality(uiQuality / sum);
    setWSize(uiSize / sum);
    setWSpeed(uiSpeed / sum);
  }

  const weightsNeedNormalization = useMemo(() => {
    const sum = uiQuality + uiSize + uiSpeed;
    return sum > 0 && Math.abs(sum - 1.0) > 0.05;
  }, [uiQuality, uiSize, uiSpeed]);

  return (
    <div>
      <div className={styles.filterGrid}>
        <input
          placeholder="Filter CPU model"
          value={cpuFilter}
          onChange={e => setCpuFilter(e.target.value)}
          className="input"
        />
        <input
          placeholder="Filter GPU model"
          value={gpuFilter}
          onChange={e => setGpuFilter(e.target.value)}
          className="input"
        />
        <div>
          <input
            list="codec-options"
            placeholder="Filter codec (type to search)"
            value={codecFilter}
            onChange={e => { setCodecFilter(e.target.value); setPresetFilter(""); }}
            className="input"
          />
          <datalist id="codec-options">
            {codecs.map(c => (<option key={c} value={c} />))}
          </datalist>
        </div>
        <select
          value={presetFilter}
          onChange={e => setPresetFilter(e.target.value)}
          className={`input${codecFilter && filteredPresets.length > 0 ? "" : ` ${styles.presetDisabled}`}`}
          disabled={!codecFilter || filteredPresets.length === 0}
          aria-disabled={!codecFilter || filteredPresets.length === 0}
          aria-label={!codecFilter ? "Preset filter (type a codec first)" : "Filter by preset"}
          title={!codecFilter ? "Type a codec first" : undefined}
        >
          <option value="">All presets</option>
          {filteredPresets.map(p => (<option key={p} value={p}>{p}</option>))}
        </select>
      </div>

      <div className={styles.encoderFilters}>
        <label className={`btn ${styles.encoderFilterLabel}${softwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={softwareOnly} onChange={e => { const v = e.target.checked; setSoftwareOnly(v); if (v) setHardwareOnly(false); }} />
          Software Only
        </label>
        <label className={`btn ${styles.encoderFilterLabel}${hardwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={hardwareOnly} onChange={e => { const v = e.target.checked; setHardwareOnly(v); if (v) setSoftwareOnly(false); }} />
          Hardware Only
        </label>
      </div>

      <div className={styles.commandRow}>
        <div className={styles.chipsRow}>
          {activeFilterChips.length === 0 ? (
            <span className="subtle">No active filters</span>
          ) : (
            activeFilterChips.map((chip) => (
              <button key={chip.key} type="button" className={styles.filterChip} onClick={chip.clear} aria-label={`Clear ${chip.label}`}>
                {chip.label}
                <span aria-hidden="true">×</span>
              </button>
            ))
          )}
        </div>
        <button className={`btn ${styles.actionBtn}`} onClick={resetAllFilters}>Reset Filters</button>
      </div>

      <div className={styles.weightsGrid}>
        <div>
          <div className={styles.weightsLabel}>PL Score v6 Core Weights</div>
          <div className={`subtle ${styles.weightSliderValue}`}>Quality, Size, and Speed are normalized to sum to 1.00</div>
        </div>
        <WeightSlider label="Quality (VMAF/SSIM/PSNR)" value={uiQuality} onChange={setUiQuality} />
        <WeightSlider label="Size" value={uiSize} onChange={setUiSize} />
        <WeightSlider label="Speed (FPS)" value={uiSpeed} onChange={setUiSpeed} />
      </div>

      <div className={styles.weightsActions}>
        <div className={`subtle ${styles.appliedWeights}`}>Applied: Q {wQuality.toFixed(2)} • S {wSize.toFixed(2)} • V {wSpeed.toFixed(2)}</div>
        {weightsNeedNormalization && (
          <div className={styles.weightWarning}>Sliders will be normalized to sum to 1.0 on Apply</div>
        )}
        <button className={`btn ${styles.actionBtn}`} onClick={resetWeights}>Reset</button>
        <button className={`btn ${styles.applyBtn}`} onClick={applyWeightsFromUI}>Apply</button>
      </div>

      <div className={styles.desktopTable}>
        <VirtualTable
          rows={pagedRows}
          selectedIds={selectedIds}
          toggleSelect={toggleSelect}
          setShowDetailId={setShowDetailId}
          setShowFfmpegId={setShowFfmpegId}
          sortKey={sortKey}
          sortDir={sortDir}
          setSort={setSort}
        />
      </div>
      <MobileCards
        rows={pagedRows}
        selectedIds={selectedIds}
        toggleSelect={toggleSelect}
        setShowDetailId={setShowDetailId}
        setShowFfmpegId={setShowFfmpegId}
      />

      <div className={styles.paginationBar}>
        <span className="subtle">
          Showing {totalRows === 0 ? 0 : page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, totalRows)} of {totalRows}
        </span>
        <div className={styles.paginationActions}>
          <button className={`btn ${styles.paginationBtn}`} disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>Prev</button>
          <span>Page {page + 1} of {totalPages}</span>
          <button className={`btn ${styles.paginationBtn}`} disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>Next</button>
        </div>
      </div>

      {showDetailId && (() => {
        const detailRow = sorted.find(r => r.id === showDetailId);
        return detailRow ? (
          <DetailsModal row={detailRow} onClose={() => setShowDetailId(null)} relSize={detailRow._relSize} />
        ) : null;
      })()}

      {showFfmpegId && (() => {
        const ffmpegRow = sorted.find(r => r.id === showFfmpegId);
        return ffmpegRow ? (
          <FfmpegModal row={ffmpegRow} onClose={() => setShowFfmpegId(null)} />
        ) : null;
      })()}

      <CompareStickyBar
        count={selectedIds.size}
        onCompare={() => setShowCompare(true)}
        onClear={clearSelection}
      />

      {showCompare && selectedIds.size >= 2 && (
        <ComparePanel
          rows={compareRows}
          onClose={() => setShowCompare(false)}
          onClear={clearSelection}
        />
      )}
    </div>
  );
}

function VirtualTable({ rows, selectedIds, toggleSelect, setShowDetailId, setShowFfmpegId, sortKey, sortDir, setSort }: { rows: EnrichedBenchmark[]; selectedIds: Set<string>; toggleSelect: (id: string) => void; setShowDetailId: (id: string | null) => void; setShowFfmpegId: (id: string | null) => void; sortKey: SortKey; sortDir: "asc" | "desc"; setSort: (key: SortKey) => void }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => parentRef.current, estimateSize: () => 48, overscan: 10 });
  return (
    <div className={`card ${styles.cardOverflow}`}>
      <div className={`${styles.virtualHeader} ${styles.virtualGrid}`} role="row" style={{ ["--col-layout" as any]: COL_WIDTHS }}>
        <div className={`th ${styles.textCenter} ${styles.selectionHead}`} role="columnheader"></div>
        <div className={`th ${styles.textCenter}`} role="columnheader">Details</div>
        <ThDiv onClick={() => setSort("cpuModel")} label="CPU" active={sortKey === "cpuModel"} dir={sortDir} />
        <ThDiv onClick={() => setSort("gpuModel")} label="GPU" active={sortKey === "gpuModel"} dir={sortDir} />
        <ThDiv onClick={() => setSort("codec")} label="Codec" active={sortKey === "codec"} dir={sortDir} />
        <ThDiv onClick={() => setSort("crf")} label="CRF" active={sortKey === "crf"} dir={sortDir} align="right" />
        <ThDiv onClick={() => setSort("preset")} label="Preset" active={sortKey === "preset"} dir={sortDir} />
        <ThDiv onClick={() => setSort("_plScore")} label="PL Score v6" active={sortKey === "_plScore"} dir={sortDir} align="right" />
        <div className={`th ${styles.textCenter}`} role="columnheader">FFmpeg</div>
        <div className={`th ${styles.textCenter}`} role="columnheader" title="Accepted submissions">Subs</div>
      </div>
      <div ref={parentRef} className={styles.virtualScrollContainer} role="table">
        <div className={styles.virtualCanvas} style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map(vr => {
            const row = rows[vr.index];
            return (
              <div key={row.id} role="row" className={`${styles.virtualRow} ${styles.virtualGrid} ${selectedIds.has(row.id) ? styles.selectedRow : ""}`.trim()} style={{ ["--col-layout" as any]: COL_WIDTHS, height: vr.size, transform: `translateY(${vr.start}px)` }}>
                <div role="cell" className={`${styles.textCenter} ${styles.selectionCell}`}><input type="checkbox" checked={selectedIds.has(row.id)} onChange={() => toggleSelect(row.id)} disabled={!selectedIds.has(row.id) && selectedIds.size >= 6} aria-label="Select for comparison" className={styles.rowCheckbox} /></div>
                <div role="cell" className={styles.textCenter}><button onClick={() => setShowDetailId(row.id)} className={styles.hoverBtn} aria-label="View details">Details</button></div>
                <div role="cell" className={styles.ellipsisCell}>{renderHardwareLink(row.cpuModel, "cpu")}</div>
                <div role="cell" className={styles.ellipsisCell}>{renderGpuCell(row)}</div>
                <div role="cell">{row._codecLabel}</div>
                <div role="cell" className={styles.textRight}>{row.crf == null ? "-" : row.crf}</div>
                <div role="cell">{row.preset}</div>
                <div role="cell" className={styles.textRight}>{row._plScore > 0 ? row._plScore.toFixed(2) : "-"}</div>
                <div role="cell" className={styles.textCenter}><button onClick={() => setShowFfmpegId(row.id)} className={styles.hoverBtn} aria-label="View ffmpeg command">FFmpeg</button></div>
                <div role="cell" className={styles.textCenter}>{typeof row.samples === "number" ? row.samples : "-"}</div>
              </div>
            );
          })}
          {rows.length === 0 && <div className={styles.noResults}>No results for current filters.</div>}
        </div>
      </div>
    </div>
  );
}

function MobileCards({
  rows,
  selectedIds,
  toggleSelect,
  setShowDetailId,
  setShowFfmpegId,
}: {
  rows: EnrichedBenchmark[];
  selectedIds: Set<string>;
  toggleSelect: (id: string) => void;
  setShowDetailId: (id: string | null) => void;
  setShowFfmpegId: (id: string | null) => void;
}) {
  return (
    <div className={styles.mobileCards}>
      {rows.length === 0 ? (
        <div className={styles.noResults}>No results for current filters.</div>
      ) : (
        rows.map((row) => (
          <article key={row.id} className={styles.mobileCard}>
            <header className={styles.mobileCardHeader}>
              <label className={styles.mobileSelect}>
                <input
                  type="checkbox"
                  checked={selectedIds.has(row.id)}
                  onChange={() => toggleSelect(row.id)}
                  disabled={!selectedIds.has(row.id) && selectedIds.size >= 6}
                  aria-label="Select for comparison"
                />
                Compare
              </label>
              <span className={styles.mobileScore}>PL {row._plScore > 0 ? row._plScore.toFixed(2) : "-"}</span>
            </header>
            <div className={styles.mobilePair}><span className="subtle">CPU</span><span>{row.cpuModel}</span></div>
            <div className={styles.mobilePair}><span className="subtle">GPU</span><span>{renderGpuCell(row)}</span></div>
            <div className={styles.mobilePair}><span className="subtle">Codec</span><span>{row._codecLabel}</span></div>
            <div className={styles.mobilePair}><span className="subtle">Preset/CRF</span><span>{row.preset} / {row.crf == null ? "-" : row.crf}</span></div>
            <div className={styles.mobileActions}>
              <button type="button" className={`btn ${styles.hoverBtn}`} onClick={() => setShowDetailId(row.id)}>Details</button>
              <button type="button" className={`btn ${styles.hoverBtn}`} onClick={() => setShowFfmpegId(row.id)}>FFmpeg</button>
            </div>
          </article>
        ))
      )}
    </div>
  );
}

function ThDiv({ label, onClick, active, dir, align }: { label: string; onClick: () => void; active: boolean; dir: "asc" | "desc"; align?: "left" | "right" }) {
  return (
    <div className={`th ${styles.sortable} ${align === "right" ? styles.textRight : ""}`} role="columnheader" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={onClick}
        className={styles.sortButton}
        title="Sort column"
        aria-label={`Sort by ${label}`}
      >
        {label}{active && <span aria-hidden="true" className={styles.sortIndicator}>{dir === "asc" ? "\u25B2" : "\u25BC"}</span>}
      </button>
    </div>
  );
}

function DetailsModal({ row, onClose, relSize }: { row: EnrichedBenchmark; onClose: () => void; relSize: number }) {
  const [showAdditional, setShowAdditional] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
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

  const acceptedSamplesRaw = typeof row.samples === "number" ? row.samples : 1;
  const acceptedSamples = acceptedSamplesRaw > 0 ? acceptedSamplesRaw : 1;
  const isAggregate = acceptedSamples > 1;
  const aggregateSuffix = isAggregate ? " (avg)" : "";
  const vmafSamples = typeof row.vmafSamples === "number" ? row.vmafSamples : row.vmaf != null ? acceptedSamples : 0;
  const ssimSamples = typeof row.ssimSamples === "number" ? row.ssimSamples : row.ssim != null ? acceptedSamples : 0;
  const psnrSamples = typeof row.psnrSamples === "number" ? row.psnrSamples : row.psnr != null ? acceptedSamples : 0;
  const encodeModeLabel = "CRF (single-pass)";

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="details-modal-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={`modal ${styles.detailsModal}`} ref={dialogRef} tabIndex={-1}>
        <div className="modal-header">
          <div id="details-modal-title" className={styles.modalTitle}>Encode Details</div>
          <button onClick={onClose} className={`btn ${styles.modalCloseBtn}`} aria-label="Close details modal">Close</button>
        </div>
        <div className={`modal-body ${styles.detailsBody}`}>
          <div className={styles.detailsOverviewGrid}>
            <div className={styles.aggregateCard}>
              <div className={styles.aggregateHeader}>
                <div>
                  <div className={styles.aggregateTitle}>{isAggregate ? "Aggregate settings row" : "Single-submission row"}</div>
                  <div className={`subtle ${styles.aggregateSubtitle}`}>
                    {isAggregate
                      ? `Averages across ${acceptedSamples} accepted submissions with identical CPU/GPU, codec, preset, and CRF.`
                      : "One accepted submission currently exists for this exact settings profile."}
                  </div>
                </div>
                <div className={`${styles.aggregateBadge} ${isAggregate ? styles.aggregateBadgeMany : styles.aggregateBadgeSingle}`}>
                  {acceptedSamples} {acceptedSamples === 1 ? "submission" : "submissions"}
                </div>
              </div>
              <div className={styles.samplePills}>
                <SamplePill label="VMAF n" count={vmafSamples} />
                <SamplePill label="SSIM n" count={ssimSamples} />
                <SamplePill label="PSNR n" count={psnrSamples} />
              </div>
            </div>

            <div className={styles.keyCard}>
              <div className={`subtle ${styles.sectionTitle}`}>Key performance snapshot</div>
              <div className={styles.keyStatsGrid}>
                <KeyStat label="PL Score v6" value={row._plScore.toFixed(2)} />
                <KeyStat label={`FPS${aggregateSuffix}`} value={row.fps.toFixed(2)} />
                <KeyStat label={`VMAF${aggregateSuffix}`} value={row.vmaf == null ? "-" : row.vmaf.toFixed(1)} />
                <KeyStat label={`Relative Size${aggregateSuffix}`} value={relSize.toFixed(2)} />
                <KeyStat label={`FPS/Watt${aggregateSuffix}`} value={row.fpsPerWatt != null ? row.fpsPerWatt.toFixed(2) : "-"} />
                <KeyStat label={`Quality/Watt${aggregateSuffix}`} value={row.qualityPerWatt != null ? row.qualityPerWatt.toFixed(2) : "-"} />
              </div>
            </div>
          </div>

          <div className={styles.configCard}>
            <div className={`subtle ${styles.sectionTitle}`}>Configuration</div>
            <div className={styles.configGrid}>
              <ConfigRow label="CPU" value={row.cpuModel} />
              <ConfigRow label="GPU" value={row.gpuModel ?? "N/A"} />
              <ConfigRow label="Encoder" value={(row.encoderName ?? row.codec) || "-"} />
              <ConfigRow label="Preset / CRF" value={`${row.preset} / ${row.crf == null ? "-" : row.crf}`} />
              <ConfigRow label="Mode" value={encodeModeLabel} />
            </div>
          </div>

          <div className={styles.additionalToggleRow}>
            <button
              onClick={() => setShowAdditional(v => !v)}
              className={`btn ${styles.additionalToggleBtn}`}
              aria-expanded={showAdditional}
              aria-controls="details-additional-data"
            >
              {showAdditional ? "Hide additional data" : "Show additional data"}
            </button>
          </div>

          {showAdditional && (
            <div id="details-additional-data" className={styles.additionalPanel}>
              <div className={`subtle ${styles.sectionTitle}`}>Additional data</div>
              <div className={styles.detailsGrid}>
                <LabelValue label="First Seen" value={new Date(row.createdAt).toLocaleString()} />
                <LabelValue label="RAM (GB)" value={String(row.ramGB)} />
                <LabelValue label="OS" value={row.os} />
                <LabelValue label="FFmpeg Version" value={row.ffmpegVersion ?? "-"} />
                <LabelValue label="Run Duration (ms)" value={row.runMs != null ? String(Math.round(row.runMs)) : "-"} />
                <LabelValue label="Thermal Throttle" value={row.thermalThrottle === true ? "Yes" : row.thermalThrottle === false ? "No" : "-"} />
                <LabelValue label={`GPU Utilization${aggregateSuffix}`} value={row.gpuUtilAvg != null ? `${row.gpuUtilAvg.toFixed(1)}%` : "-"} />
                <LabelValue label={`GPU Power${aggregateSuffix}`} value={row.gpuPowerAvgW != null ? `${row.gpuPowerAvgW.toFixed(1)} W` : "-"} />
                <LabelValue label="GPU Memory Peak" value={row.gpuMemPeakMB != null ? `${Math.round(row.gpuMemPeakMB)} MB` : "-"} />
                <LabelValue label={`CPU Utilization${aggregateSuffix}`} value={row.cpuUtilAvg != null ? `${row.cpuUtilAvg.toFixed(1)}%` : "-"} />
                <LabelValue label="CPU Peak" value={row.cpuUtilMax != null ? `${row.cpuUtilMax.toFixed(1)}%` : "-"} />
                <LabelValue label="Peak Memory" value={row.peakMemoryMB != null ? `${Math.round(row.peakMemoryMB)} MB` : "-"} />
                <LabelValue label="PL Quality Component" value={row._q.toFixed(1)} />
                <LabelValue label="PL Size Component" value={row._s.toFixed(1)} />
                <LabelValue label="PL Speed Component" value={row._sp.toFixed(1)} />
                <LabelValue label="PL Efficiency Component" value={row._eff.toFixed(1)} />
                <LabelValue label="PL Reliability Component" value={row._rel.toFixed(1)} />
                <LabelValue label="Metric Confidence" value={`${(row._confidence * 100).toFixed(0)}%`} />
                <LabelValue label="Notes" value={row.notes && row.notes.trim() ? row.notes : "-"} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SamplePill({ label, count }: { label: string; count: number }) {
  return (
    <div className={styles.samplePill}>
      <span className="subtle">{label}</span>
      <span className={styles.samplePillValue}>{count}</span>
    </div>
  );
}

function KeyStat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.keyStat}>
      <div className={styles.keyStatLabel}>{label}</div>
      <div className={styles.keyStatValue}>{value}</div>
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.configRow}>
      <div className={`subtle ${styles.configLabel}`}>{label}</div>
      <div className={styles.configValue}>{value}</div>
    </div>
  );
}

function LabelValue({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.labelValueGroup}>
      <div className={`subtle ${styles.labelText}`}>{label}</div>
      <div className={styles.valueText}>{value}</div>
    </div>
  );
}

// Helper to escape shell metacharacters for display warning
function hasShellMetachars(s: string): boolean {
  return /[;&|`$(){}[\]<>\\!"'*?#~]/.test(s);
}

function shellQuotePosix(value: string): string {
  if (value.length === 0) return "''";
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function isSafeCliToken(value: string): boolean {
  return /^[a-z0-9_:+.-]+$/i.test(value);
}

function FfmpegModal({ row, onClose }: { row: EnrichedBenchmark; onClose: () => void }) {
  const [inputPath, setInputPath] = useState<string>("input.mp4");
  const [outputPath, setOutputPath] = useState<string>("output.mp4");
  const [copied, setCopied] = useState<boolean>(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
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

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(t);
  }, [copied]);

  // Check for potentially dangerous characters in paths
  const encoderRaw = (row.encoderName ?? row.codec ?? "").trim();
  const presetRaw = (row.preset ?? "").trim();
  const safeEncoder = isSafeCliToken(encoderRaw) ? encoderRaw : "";
  const safePreset = isSafeCliToken(presetRaw) ? presetRaw : "";
  const pathWarning = hasShellMetachars(inputPath) || hasShellMetachars(outputPath);
  const profileWarning = (!safeEncoder && encoderRaw.length > 0) || (!safePreset && presetRaw.length > 0);

  const command = useMemo(() => {
    const safeInput = inputPath || "input.mp4";
    const safeOutput = outputPath || "output.mp4";

    const parts: string[] = [
      "ffmpeg",
      "-i",
      shellQuotePosix(safeInput),
    ];
    if (safeEncoder) {
      parts.push("-c:v", shellQuotePosix(safeEncoder));
    }
    if (row.crf != null) {
      parts.push("-crf", String(row.crf));
    }
    if (safePreset) {
      parts.push("-preset", shellQuotePosix(safePreset));
    }
    parts.push("-c:a", "copy");
    parts.push(shellQuotePosix(safeOutput));
    return parts.join(" ");
  }, [row.crf, inputPath, outputPath, safeEncoder, safePreset]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {}
  };

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ffmpeg-modal-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" ref={dialogRef} tabIndex={-1}>
        <div className="modal-header">
          <div id="ffmpeg-modal-title" className={styles.modalTitle}>FFmpeg Command</div>
          <button onClick={onClose} className={`btn ${styles.modalCloseBtn}`} aria-label="Close FFmpeg modal">Close</button>
        </div>
        <div className={`modal-body ${styles.ffmpegBody}`}>
          <div className={styles.pathInputGrid}>
            <div>
              <div className={`subtle ${styles.inputLabel}`}>Input video</div>
              <input
                className="input"
                placeholder="input.mp4"
                value={inputPath}
                onChange={e => setInputPath(e.target.value)}
                aria-label="Input video path"
              />
            </div>
            <div>
              <div className={`subtle ${styles.inputLabel}`}>Output video</div>
              <input
                className="input"
                placeholder="output.mp4"
                value={outputPath}
                onChange={e => setOutputPath(e.target.value)}
                aria-label="Output video path"
              />
            </div>
          </div>
          {pathWarning && (
            <div className={styles.pathWarning}>
              Warning: Path contains special characters. Review the command carefully before running.
            </div>
          )}
          {profileWarning && (
            <div className={styles.pathWarning}>
              Warning: Encoder or preset contained unsafe characters and was omitted from the generated command.
            </div>
          )}
          <div className={styles.kbdWrapper}>
            <pre className="kbd" aria-label="FFmpeg command"><code>{command}</code></pre>
            <button className={`copy-btn${copied ? " success" : ""}`} onClick={copy} aria-label="Copy command">
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function isHardwareEncoder(encoderLower: string): boolean {
  return /(_videotoolbox|_nvenc|_qsv|_amf|_vaapi)$/.test(encoderLower);
}

function renderHardwareLink(model: string, kind: "cpu" | "gpu") {
  const trimmed = (model || "").trim();
  if (!trimmed) return "-";
  const appleWiki = wikipediaAppleUrl(trimmed);
  if (appleWiki) {
    return (
      <a href={appleWiki} target="_blank" rel="noreferrer" className="link" title="Open Wikipedia in new tab">
        {trimmed}
      </a>
    );
  }
  const encoded = encodeURIComponent(trimmed);
  const href = `/api/hwlink?kind=${kind}&q=${encoded}`;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="link" title="Open TechPowerUp search in new tab">
      {trimmed}
    </a>
  );
}

function renderGpuCell(row: Benchmark) {
  const gpu = row.gpuModel ?? (isAppleSilicon(row.cpuModel) ? row.cpuModel : null);
  return gpu ? renderHardwareLink(gpu, "gpu") : "-";
}

function isAppleSilicon(cpu: string | null | undefined): boolean {
  if (!cpu) return false;
  return /\bapple\s+m\d/i.test(cpu);
}

function wikipediaAppleUrl(model: string): string | null {
  const match = model.match(/\bm(\d+)\b/i);
  if (!match) return null;
  // Ensure it's actually an Apple chip reference
  if (!/apple/i.test(model)) return null;
  const gen = match[1];
  return `https://en.wikipedia.org/wiki/Apple_M${gen}`;
}

function WeightSlider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className={styles.weightSlider}>
      <div className={styles.weightSliderHeader}>
        <span>{label}</span>
        <span className={`subtle ${styles.weightSliderValue}`}>{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className={styles.weightRange}
      />
    </label>
  );
}
