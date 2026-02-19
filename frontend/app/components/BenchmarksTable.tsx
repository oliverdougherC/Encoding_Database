"use client";

import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";
import styles from "./BenchmarksTable.module.css";
import ComparePanel, { CompareStickyBar } from "./ComparePanel";
import { formatCodecLabel } from "./codecLabel";
import { fetchFilteredBenchmarks } from "../lib/fetchBenchmarksClient";
import type { Benchmark } from "../lib/types";
import { createPlScoreContext, scorePlBenchmarkV6 } from "../lib/plScore";

export type { Benchmark } from "../lib/types";

const PAGE_SIZE = 50;
const COL_WIDTHS = "4% 9% 17% 17% 13% 7% 11% 12% 7% 7%";

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

const CONTENT_CLASS_LABELS: Record<string, string> = {
  mixed: "Mixed (Original)",
  talkingHead: "Talking Head",
  action: "Action / Sports",
  animation: "Animation / Cartoon",
  screen: "Screen Recording",
  nature: "Nature / Documentary",
  gaming: "Gaming",
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
  // Multi-content filters (Sprint 5)
  const [contentClassFilter, setContentClassFilter] = useState(() => searchParams.get("cc") || "");
  const [resolutionFilter, setResolutionFilter] = useState(() => searchParams.get("res") || "");
  const [passesFilter, setPassesFilter] = useState(() => searchParams.get("passes") || "");
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
      if (contentClassFilter) params.set("cc", contentClassFilter);
      if (resolutionFilter) params.set("res", resolutionFilter);
      if (passesFilter) params.set("passes", passesFilter);
      if (softwareOnly) params.set("sw", "1");
      if (hardwareOnly) params.set("hw", "1");
      const qs = params.toString();
      const base = window.location.pathname;
      window.history.replaceState(null, "", qs ? `${base}?${qs}` : base);
    }, 300);
    return () => { if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current); };
  }, [cpuFilter, gpuFilter, codecFilter, presetFilter, sortKey, sortDir, contentClassFilter, resolutionFilter, passesFilter, softwareOnly, hardwareOnly]);

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

  // Server-side filtering state (F-02)
  const [serverData, setServerData] = useState<Benchmark[] | null>(null);
  const [serverTotal, setServerTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [fetching, setFetching] = useState(false);

  // Debounced server-side fetch when filters change
  const fetchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (fetchDebounceRef.current) clearTimeout(fetchDebounceRef.current);
    fetchDebounceRef.current = setTimeout(() => {
      const params: Record<string, string> = {
        limit: String(PAGE_SIZE),
        skip: String(page * PAGE_SIZE),
        total: "1",
      };
      if (cpuFilter.trim()) params.cpu = cpuFilter.trim();
      if (gpuFilter.trim()) params.gpu = gpuFilter.trim();
      if (codecFilter.trim()) params.codecSearch = codecFilter.trim();
      setFetching(true);
      fetchFilteredBenchmarks(params)
        .then(({ data, total }) => { setServerData(data); setServerTotal(total); })
        .catch(() => { setServerData(null); }) // fallback to client-side
        .finally(() => setFetching(false));
    }, 300);
    return () => { if (fetchDebounceRef.current) clearTimeout(fetchDebounceRef.current); };
  }, [cpuFilter, gpuFilter, codecFilter, page]);

  // Reset page when filters change
  const prevFiltersRef = useRef({ cpuFilter, gpuFilter, codecFilter });
  useEffect(() => {
    const prev = prevFiltersRef.current;
    if (prev.cpuFilter !== cpuFilter || prev.gpuFilter !== gpuFilter || prev.codecFilter !== codecFilter) {
      setPage(0);
      prevFiltersRef.current = { cpuFilter, gpuFilter, codecFilter };
    }
  }, [cpuFilter, gpuFilter, codecFilter]);

  // Use server data if available, otherwise fall back to initialData
  const activeData = serverData ?? initialData;
  const totalRows = serverData ? serverTotal : initialData.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  const codecs = useMemo(() => Array.from(new Set(initialData.map(d => d.codec))).sort(), [initialData]);
  const presets = useMemo(() => Array.from(new Set(initialData.map(d => d.preset))).sort(), [initialData]);
  const contentClasses = useMemo(() => Array.from(new Set(initialData.map(d => d.contentClass ?? "mixed"))).sort(), [initialData]);
  const resolutions = useMemo(() => {
    const order = ["480p", "720p", "1080p", "1440p", "4k"];
    const set = new Set(initialData.map(d => d.resolution ?? "1080p"));
    return order.filter(r => set.has(r));
  }, [initialData]);
  const filteredPresets = useMemo(() => {
    if (!codecFilter) return presets;
    const lower = codecFilter.toLowerCase();
    const matching = initialData.filter(r => r.codec.toLowerCase().includes(lower));
    return Array.from(new Set(matching.map(r => r.preset))).sort();
  }, [initialData, codecFilter, presets]);

  // Pre-compute hardware encoder classification once per row to avoid repeated regex tests
  const dataWithHwClass = useMemo(() => {
    return activeData.map(row => {
      const encLower = (row.encoderName ?? row.codec ?? "").toLowerCase();
      return { ...row, _isHardware: isHardwareEncoder(encLower) };
    });
  }, [activeData]);

  const filtered = useMemo(() => {
    const cpu = cpuFilter.trim().toLowerCase();
    const gpu = gpuFilter.trim().toLowerCase();
    return dataWithHwClass.filter(row => {
      if (cpu && !row.cpuModel.toLowerCase().includes(cpu)) return false;
      if (gpu && !(row.gpuModel ?? "").toLowerCase().includes(gpu)) return false;
      if (codecFilter && !row.codec.toLowerCase().includes(codecFilter.toLowerCase())) return false;
      if (presetFilter && row.preset !== presetFilter) return false;
      if (contentClassFilter && (row.contentClass ?? "mixed") !== contentClassFilter) return false;
      if (resolutionFilter && (row.resolution ?? "1080p") !== resolutionFilter) return false;
      if (passesFilter && String(row.passes ?? 1) !== passesFilter) return false;
      if (softwareOnly && !hardwareOnly) return !row._isHardware;
      if (hardwareOnly && !softwareOnly) return row._isHardware;
      return true;
    });
  }, [dataWithHwClass, cpuFilter, gpuFilter, codecFilter, presetFilter, contentClassFilter, resolutionFilter, passesFilter, softwareOnly, hardwareOnly]);

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
    return perRowMetrics.map((row): EnrichedBenchmark => {
      const scored = scorePlBenchmarkV6(row, plContext, {
        quality: wQuality,
        size: wSize,
        speed: wSpeed,
      });
      return { ...row, _plScore: scored.total };
    });
  }, [perRowMetrics, plContext, wQuality, wSize, wSpeed]);

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
        <select value={contentClassFilter} onChange={e => setContentClassFilter(e.target.value)} className="input" aria-label="Filter by content class">
          <option value="">All content</option>
          {contentClasses.map(cc => (<option key={cc} value={cc}>{CONTENT_CLASS_LABELS[cc] ?? cc}</option>))}
        </select>
        <select value={resolutionFilter} onChange={e => setResolutionFilter(e.target.value)} className="input" aria-label="Filter by resolution">
          <option value="">All resolutions</option>
          {resolutions.map(r => (<option key={r} value={r}>{r}</option>))}
        </select>
        <select value={passesFilter} onChange={e => setPassesFilter(e.target.value)} className="input" aria-label="Filter by encoding passes">
          <option value="">All passes</option>
          <option value="1">1-pass (CRF)</option>
          <option value="2">2-pass (CBR/VBR)</option>
        </select>
        <label className={`btn ${styles.encoderFilterLabel}${softwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={softwareOnly} onChange={e => { const v = e.target.checked; setSoftwareOnly(v); if (v) setHardwareOnly(false); }} />
          Software Only
        </label>
        <label className={`btn ${styles.encoderFilterLabel}${hardwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={hardwareOnly} onChange={e => { const v = e.target.checked; setHardwareOnly(v); if (v) setSoftwareOnly(false); }} />
          Hardware Only
        </label>
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

      <VirtualTable
        sorted={sorted}
        selectedIds={selectedIds}
        toggleSelect={toggleSelect}
        setShowDetailId={setShowDetailId}
        setShowFfmpegId={setShowFfmpegId}
        sortKey={sortKey}
        sortDir={sortDir}
        setSort={setSort}
        fetching={fetching}
      />

      <div className={styles.paginationBar}>
        <span className="subtle">
          Showing {sorted.length === 0 ? 0 : page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, totalRows)} of {totalRows}
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" style={{ padding: "6px 10px" }} disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>Prev</button>
          <span>Page {page + 1} of {totalPages}</span>
          <button className="btn" style={{ padding: "6px 10px" }} disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>Next</button>
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

function VirtualTable({ sorted, selectedIds, toggleSelect, setShowDetailId, setShowFfmpegId, sortKey, sortDir, setSort, fetching }: { sorted: EnrichedBenchmark[]; selectedIds: Set<string>; toggleSelect: (id: string) => void; setShowDetailId: (id: string | null) => void; setShowFfmpegId: (id: string | null) => void; sortKey: SortKey; sortDir: "asc" | "desc"; setSort: (key: SortKey) => void; fetching: boolean }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({ count: sorted.length, getScrollElement: () => parentRef.current, estimateSize: () => 48, overscan: 10 });
  return (
    <div className={`card ${styles.cardOverflow}`}>
      <div className={styles.virtualHeader} role="row" style={{ display: "grid", gridTemplateColumns: COL_WIDTHS }}>
        <div className={`th ${styles.textCenter}`} role="columnheader" style={{ padding: "8px 4px" }}></div>
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
        <div style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}>
          {fetching && sorted.length === 0 && <div style={{ padding: 16, textAlign: "center", color: "var(--muted)" }}>Loading...</div>}
          {virtualizer.getVirtualItems().map(vr => {
            const row = sorted[vr.index];
            return (
              <div key={row.id} role="row" className={styles.virtualRow} style={{ position: "absolute", top: 0, left: 0, width: "100%", height: vr.size, transform: `translateY(${vr.start}px)`, display: "grid", gridTemplateColumns: COL_WIDTHS, background: selectedIds.has(row.id) ? "color-mix(in srgb, var(--highlight) 20%, var(--surface))" : undefined }}>
                <div role="cell" className={`td ${styles.textCenter}`} style={{ padding: "8px 4px" }}><input type="checkbox" checked={selectedIds.has(row.id)} onChange={() => toggleSelect(row.id)} disabled={!selectedIds.has(row.id) && selectedIds.size >= 6} aria-label="Select for comparison" style={{ accentColor: "var(--accent)" }} /></div>
                <div role="cell" className={`td ${styles.textCenter}`}><button onClick={() => setShowDetailId(row.id)} className={`btn ${styles.hoverBtn}`} aria-label="View details">Details</button></div>
                <div role="cell" className="td" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{renderHardwareLink(row.cpuModel, "cpu")}</div>
                <div role="cell" className="td" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{renderGpuCell(row)}</div>
                <div role="cell" className="td">{row._codecLabel}</div>
                <div role="cell" className={`td ${styles.textRight}`}>{row.crf == null ? "-" : row.crf}</div>
                <div role="cell" className="td">{row.preset}</div>
                <div role="cell" className={`td ${styles.textRight}`}>{row._plScore > 0 ? row._plScore.toFixed(2) : "-"}</div>
                <div role="cell" className={`td ${styles.textCenter}`}><button onClick={() => setShowFfmpegId(row.id)} className={`btn ${styles.hoverBtn}`} aria-label="View ffmpeg command">FFmpeg</button></div>
                <div role="cell" className={`td ${styles.textCenter}`}>{typeof row.samples === "number" ? row.samples : "-"}</div>
              </div>
            );
          })}
          {sorted.length === 0 && !fetching && <div style={{ padding: 16, textAlign: "center", color: "var(--muted)" }}>No results for current filters.</div>}
        </div>
      </div>
    </div>
  );
}

function ThDiv({ label, onClick, active, dir, align }: { label: string; onClick: () => void; active: boolean; dir: "asc" | "desc"; align?: "left" | "right" }) {
  return (
    <div onClick={onClick} className={`th ${styles.sortable}`} role="columnheader" style={{ textAlign: align || "left", cursor: "pointer" }} title="Click to sort" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      {label}{active && <span aria-hidden="true" className={styles.sortIndicator}>{dir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </div>
  );
}

function DetailsModal({ row, onClose, relSize }: { row: EnrichedBenchmark; onClose: () => void; relSize: number }) {
  const [showAdditional, setShowAdditional] = useState(false);

  const acceptedSamplesRaw = typeof row.samples === "number" ? row.samples : 1;
  const acceptedSamples = acceptedSamplesRaw > 0 ? acceptedSamplesRaw : 1;
  const isAggregate = acceptedSamples > 1;
  const aggregateSuffix = isAggregate ? " (avg)" : "";
  const vmafSamples = typeof row.vmafSamples === "number" ? row.vmafSamples : row.vmaf != null ? acceptedSamples : 0;
  const ssimSamples = typeof row.ssimSamples === "number" ? row.ssimSamples : row.ssim != null ? acceptedSamples : 0;
  const psnrSamples = typeof row.psnrSamples === "number" ? row.psnrSamples : row.psnr != null ? acceptedSamples : 0;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="details-modal-title">
      <div className={`modal ${styles.detailsModal}`}>
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
                      ? `Averages across ${acceptedSamples} accepted submissions with identical CPU/GPU, codec, preset, CRF, content class, resolution, and pass count.`
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
              <ConfigRow label="Content Class" value={CONTENT_CLASS_LABELS[row.contentClass ?? "mixed"] ?? (row.contentClass || "mixed")} />
              <ConfigRow label="Resolution / Passes" value={`${row.resolution ?? "1080p"} / ${row.passes === 2 ? "2-pass" : "1-pass"}`} />
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

function FfmpegModal({ row, onClose }: { row: EnrichedBenchmark; onClose: () => void }) {
  const [inputPath, setInputPath] = useState<string>("input.mp4");
  const [outputPath, setOutputPath] = useState<string>("output.mp4");
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(t);
  }, [copied]);

  // Check for potentially dangerous characters in paths
  const pathWarning = hasShellMetachars(inputPath) || hasShellMetachars(outputPath);

  const command = useMemo(() => {
    const encoder = (row.encoderName ?? row.codec ?? "").trim();
    const safeInput = inputPath || "input.mp4";
    const safeOutput = outputPath || "output.mp4";

    const parts: string[] = [
      "ffmpeg",
      "-i",
      safeInput,
    ];
    if (encoder) {
      parts.push("-c:v", encoder);
    }
    if (row.crf != null) {
      parts.push("-crf", String(row.crf));
    }
    if (row.preset) {
      parts.push("-preset", row.preset);
    }
    parts.push("-c:a", "copy");
    parts.push(safeOutput);
    return parts.join(" ");
  }, [row, inputPath, outputPath]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {}
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="ffmpeg-modal-title">
      <div className="modal">
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
        style={{ accentColor: "var(--accent)" }}
      />
    </label>
  );
}
