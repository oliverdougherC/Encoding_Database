"use client";

import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import styles from "./BenchmarksTable.module.css";
import ComparePanel, { CompareStickyBar } from "./ComparePanel";
import { formatCodecLabel } from "./codecLabel";

export type Benchmark = {
  id: string;
  createdAt: string;
  cpuModel: string;
  gpuModel: string | null;
  ramGB: number;
  os: string;
  codec: string;
  // CRF is optional depending on encoder; when absent show "-"
  crf?: number | null;
  preset: string;
  fps: number;
  vmaf: number | null;
  fileSizeBytes: number;
  notes: string | null;
  ffmpegVersion?: string | null;
  encoderName?: string | null;
  clientVersion?: string | null;
  inputHash?: string | null;
  runMs?: number | null;
  status?: string | null;
  // Aggregation counts (available from server)
  samples?: number;
  vmafSamples?: number;
};

// Extended type for benchmarks with computed scores
type EnrichedBenchmark = Benchmark & {
  _plove: number;
  _relSize: number;
  _codecLabel: string;
  _isHardware: boolean;
};

type SortKey = "cpuModel" | "gpuModel" | "codec" | "crf" | "preset" | "_plove";

export default function BenchmarksTable({ initialData }: { initialData: Benchmark[] }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const routerRef = useRef(router);
  useEffect(() => { routerRef.current = router; }, [router]);
  const isInitRef = useRef(false);

  const [cpuFilter, setCpuFilter] = useState(() => searchParams.get("cpu") || "");
  const [gpuFilter, setGpuFilter] = useState(() => searchParams.get("gpu") || "");
  const [codecFilter, setCodecFilter] = useState(() => searchParams.get("codec") || "");
  const [presetFilter, setPresetFilter] = useState(() => searchParams.get("preset") || "");
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const s = searchParams.get("sort");
    if (s && ["cpuModel", "gpuModel", "codec", "crf", "preset", "_plove"].includes(s)) return s as SortKey;
    return "_plove";
  });
  const [sortDir, setSortDir] = useState<"asc" | "desc">(() => {
    const d = searchParams.get("dir");
    return d === "asc" ? "asc" : "desc";
  });
  // Encoder type filters
  const [softwareOnly, setSoftwareOnly] = useState<boolean>(() => searchParams.get("sw") === "1");
  const [hardwareOnly, setHardwareOnly] = useState<boolean>(() => searchParams.get("hw") === "1");

  // Sync filter state to URL search params (debounced to avoid excessive updates)
  const urlDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!isInitRef.current) { isInitRef.current = true; return; }
    if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current);
    urlDebounceRef.current = setTimeout(() => {
      const params = new URLSearchParams();
      if (cpuFilter) params.set("cpu", cpuFilter);
      if (gpuFilter) params.set("gpu", gpuFilter);
      if (codecFilter) params.set("codec", codecFilter);
      if (presetFilter) params.set("preset", presetFilter);
      if (sortKey !== "_plove") params.set("sort", sortKey);
      if (sortDir !== "desc") params.set("dir", sortDir);
      if (softwareOnly) params.set("sw", "1");
      if (hardwareOnly) params.set("hw", "1");
      const qs = params.toString();
      const base = typeof window !== "undefined" ? window.location.pathname : "/";
      routerRef.current.replace(qs ? `${base}?${qs}` : base, { scroll: false });
    }, 300);
    return () => { if (urlDebounceRef.current) clearTimeout(urlDebounceRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cpuFilter, gpuFilter, codecFilter, presetFilter, sortKey, sortDir, softwareOnly, hardwareOnly]);

  // Weights for PLOVE score (sum must equal 1.0)
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

  const codecs = useMemo(() => Array.from(new Set(initialData.map(d => d.codec))).sort(), [initialData]);
  const presets = useMemo(() => Array.from(new Set(initialData.map(d => d.preset))).sort(), [initialData]);
  const filteredPresets = useMemo(() => codecFilter ? presetsForCodec(initialData, codecFilter) : presets, [initialData, codecFilter, presets]);

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
      if (codecFilter && row.codec !== codecFilter) return false;
      if (codecFilter && presetFilter && row.preset !== presetFilter) return false;
      if (softwareOnly && !hardwareOnly) return !row._isHardware;
      if (hardwareOnly && !softwareOnly) return row._isHardware;
      return true;
    });
  }, [dataWithHwClass, cpuFilter, gpuFilter, codecFilter, presetFilter, softwareOnly, hardwareOnly]);

  // Compute relative size baseline (median size across filtered rows)
  const sizeBaseline = useMemo(() => {
    const sizes = filtered.map(r => r.fileSizeBytes).filter(s => s > 0).sort((a,b)=>a-b);
    if (sizes.length === 0) return 1;
    const mid = Math.floor(sizes.length / 2);
    return sizes.length % 2 === 0 ? Math.max(1, Math.floor((sizes[mid-1] + sizes[mid]) / 2)) : Math.max(1, sizes[mid]);
  }, [filtered]);

  // Dataset min/max for normalization
  const ranges = useMemo(() => {
    const vmafVals = filtered.filter(r => typeof r.vmaf === "number").map(r => Number(r.vmaf));
    const fpsVals = filtered.map(r => Math.max(0, r.fps || 0));
    const relSizes = filtered.map(r => (r.fileSizeBytes > 0 ? r.fileSizeBytes / sizeBaseline : 1));
    let vmafMin = 0, vmafMax = 0, fpsMin = 0, fpsMax = 0, rsMin = 0, rsMax = 0;
    if (vmafVals.length) { vmafMin = vmafVals[0]; vmafMax = vmafVals[0]; for (const v of vmafVals) { if (v < vmafMin) vmafMin = v; if (v > vmafMax) vmafMax = v; } }
    if (fpsVals.length) { fpsMin = fpsVals[0]; fpsMax = fpsVals[0]; for (const v of fpsVals) { if (v < fpsMin) fpsMin = v; if (v > fpsMax) fpsMax = v; } }
    if (relSizes.length) { rsMin = relSizes[0]; rsMax = relSizes[0]; for (const v of relSizes) { if (v < rsMin) rsMin = v; if (v > rsMax) rsMax = v; } }
    return { vmafMin, vmafMax, fpsMin, fpsMax, rsMin, rsMax };
  }, [filtered, sizeBaseline]);

  const withScores = useMemo((): EnrichedBenchmark[] => {
    function qualityScore(vmaf: number | null | undefined): number {
      if (typeof vmaf !== "number") return 100;
      const v = Math.max(0, Math.min(100, vmaf));
      if (v >= 90) {
        return 50 + 50 * Math.sqrt((v - 90) / 10);
      }
      return 50 * Math.pow(v / 90, 4);
    }
    function sizeScore(rel: number): number {
      if (!(ranges.rsMax > ranges.rsMin)) return 100;
      return 100 * (ranges.rsMax - rel) / (ranges.rsMax - ranges.rsMin);
    }
    function speedScore(fps: number): number {
      const f = Math.max(0, fps || 0);
      if (!(ranges.fpsMax > 0 && ranges.fpsMin > 0)) return 0;
      if (ranges.fpsMax === ranges.fpsMin) return 100;
      const logF = Math.log(f > 0 ? f : ranges.fpsMin);
      const logMin = Math.log(ranges.fpsMin);
      const logMax = Math.log(ranges.fpsMax);
      return 100 * (logF - logMin) / (logMax - logMin);
    }

    return filtered.map((row): EnrichedBenchmark => {
      const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / sizeBaseline : 1;
      const encoder = (row.encoderName ?? row.codec ?? "").toLowerCase();
      const codecLabel = formatCodecLabel(encoder);

      if (relSize >= 1) {
        return { ...row, _plove: 0, _relSize: relSize, _codecLabel: codecLabel };
      }

      const q = qualityScore(row.vmaf);
      const s = sizeScore(relSize);
      const sp = speedScore(row.fps);
      const prelim = wQuality * q + wSize * s + wSpeed * sp;
      const plove = Math.max(0, Math.min(100, prelim));

      return { ...row, _plove: plove, _relSize: relSize, _codecLabel: codecLabel };
    });
  }, [filtered, ranges, wQuality, wSize, wSpeed, sizeBaseline]);

  const sorted = useMemo((): EnrichedBenchmark[] => {
    const data = [...withScores];
    data.sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      const getValue = (row: EnrichedBenchmark): string | number | null => {
        if (sortKey === "codec") return row._codecLabel;
        if (sortKey === "_plove") return row._plove;
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
    const safe = sum > 0 ? sum : 1;
    setWQuality(uiQuality / safe);
    setWSize(uiSize / safe);
    setWSpeed(uiSpeed / safe);
  }

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
        <select value={codecFilter} onChange={e => { setCodecFilter(e.target.value); setPresetFilter(""); }} className="input">
          <option value="">All codecs</option>
          {codecs.map(c => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select
          value={presetFilter}
          onChange={e => setPresetFilter(e.target.value)}
          className={`input${codecFilter ? "" : ` ${styles.presetDisabled}`}`}
          disabled={!codecFilter}
          aria-disabled={!codecFilter}
          aria-label={!codecFilter ? "Preset filter (select a codec first)" : "Filter by preset"}
          title={!codecFilter ? "Select a codec first" : undefined}
        >
          <option value="">All presets</option>
          {filteredPresets.map(p => (<option key={p} value={p}>{p}</option>))}
        </select>
      </div>

      <div className={styles.encoderFilters}>
        <label className={`btn ${styles.encoderFilterLabel}${softwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={softwareOnly} onChange={e => { const v = e.target.checked; setSoftwareOnly(v); if (v) setHardwareOnly(false); }} />
          Software Encoders Only
        </label>
        <label className={`btn ${styles.encoderFilterLabel}${hardwareOnly ? ` ${styles.encoderFilterActive}` : ""}`}>
          <input type="checkbox" checked={hardwareOnly} onChange={e => { const v = e.target.checked; setHardwareOnly(v); if (v) setSoftwareOnly(false); }} />
          Hardware Encoders Only
        </label>
      </div>

      <div className={styles.weightsGrid}>
        <div>
          <div className={styles.weightsLabel}>Scoring Weights</div>
          <div className={`subtle ${styles.weightSliderValue}`}>Sum is constrained to 1.00</div>
        </div>
        <WeightSlider label="Quality (VMAF)" value={uiQuality} onChange={setUiQuality} />
        <WeightSlider label="Size" value={uiSize} onChange={setUiSize} />
        <WeightSlider label="Speed (FPS)" value={uiSpeed} onChange={setUiSpeed} />
      </div>

      <div className={styles.weightsActions}>
        <div className={`subtle ${styles.appliedWeights}`}>Applied: Q {wQuality.toFixed(2)} • S {wSize.toFixed(2)} • V {wSpeed.toFixed(2)}</div>
        <button className={`btn ${styles.actionBtn}`} onClick={resetWeights}>Reset</button>
        <button className={`btn ${styles.applyBtn}`} onClick={applyWeightsFromUI}>Apply</button>
      </div>

      <div className={`card ${styles.cardOverflow}`}>
        <table className="table">
          {(() => {
            const cols = [
              <col key="select" style={{ width: "4%" }} />,
              <col key="details" style={{ width: "9%" }} />,
              <col key="cpu" style={{ width: "17%" }} />,
              <col key="gpu" style={{ width: "17%" }} />,
              <col key="codec" style={{ width: "13%" }} />,
              <col key="crf" style={{ width: "7%" }} />,
              <col key="preset" style={{ width: "11%" }} />,
              <col key="plove" style={{ width: "12%" }} />,
              <col key="ffmpeg" style={{ width: "7%" }} />,
              <col key="samples" style={{ width: "7%" }} />,
            ];
            return <colgroup>{cols}</colgroup>;
          })()}
          <thead className="thead">
            <tr>
              <th className={`th ${styles.textCenter}`} style={{ padding: "8px 4px" }}></th>
              <th className={`th ${styles.textCenter}`}>Details</th>
              <Th onClick={() => setSort("cpuModel")} label="CPU" active={sortKey === "cpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("gpuModel")} label="GPU" active={sortKey === "gpuModel"} dir={sortDir} />
              <Th onClick={() => setSort("codec")} label="Codec" active={sortKey === "codec"} dir={sortDir} />
              <Th onClick={() => setSort("crf")} label="CRF" active={sortKey === "crf"} dir={sortDir} align="right" />
              <Th onClick={() => setSort("preset")} label="Preset" active={sortKey === "preset"} dir={sortDir} />
              <Th onClick={() => setSort("_plove")} label="PLOVE Score" active={sortKey === "_plove"} dir={sortDir} align="right" />
              <th className={`th ${styles.textCenter}`}>FFmpeg</th>
              <th className={`th ${styles.textCenter}`} title="Number of accepted submissions aggregated into this profile">Subs</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr key={row.id} style={selectedIds.has(row.id) ? { background: "color-mix(in srgb, var(--highlight) 20%, var(--surface))" } : undefined}>
                <td className={`td ${styles.textCenter}`} style={{ padding: "8px 4px" }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(row.id)}
                    onChange={() => toggleSelect(row.id)}
                    disabled={!selectedIds.has(row.id) && selectedIds.size >= 6}
                    aria-label="Select for comparison"
                    style={{ accentColor: "var(--accent)" }}
                  />
                </td>
                <td className={`td ${styles.textCenter}`}>
                  <button onClick={() => setShowDetailId(row.id)} className={`btn ${styles.hoverBtn}`} aria-label="View details">
                    Details
                  </button>
                </td>
                <td className="td">{renderHardwareLink(row.cpuModel, "cpu")}</td>
                <td className="td">{renderGpuCell(row)}</td>
                <td className="td">{row._codecLabel}</td>
                <td className={`td ${styles.textRight}`}>{row.crf == null ? "-" : row.crf}</td>
                <td className="td">{row.preset}</td>
                <td className={`td ${styles.textRight}`}>{row._plove > 0 ? row._plove.toFixed(2) : "-"}</td>
                <td className={`td ${styles.textCenter}`}>
                  <button onClick={() => setShowFfmpegId(row.id)} className={`btn ${styles.hoverBtn}`} aria-label="View ffmpeg command">
                    FFmpeg
                  </button>
                </td>
                <td className={`td ${styles.textCenter}`}>{typeof row.samples === "number" ? row.samples : "-"}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={10} className={`td ${styles.noResults}`}>
                  No results for current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
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

function Th({ label, onClick, active, dir, align }: { label: string; onClick: () => void; active: boolean; dir: "asc" | "desc"; align?: "left" | "right" }) {
  return (
    <th
      onClick={onClick}
      className={`th ${styles.sortable}`}
      style={{ textAlign: align || "left" }}
      title="Click to sort"
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      role="columnheader"
    >
      {label}
      {active && (
        <span aria-hidden="true" className={styles.sortIndicator}>
          {dir === "asc" ? "\u25B2" : "\u25BC"}
        </span>
      )}
    </th>
  );
}

function DetailsModal({ row, onClose, relSize }: { row: EnrichedBenchmark; onClose: () => void; relSize: number }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="details-modal-title">
      <div className="modal">
        <div className="modal-header">
          <div id="details-modal-title" className={styles.modalTitle}>Encode Details</div>
          <button onClick={onClose} className={`btn ${styles.modalCloseBtn}`} aria-label="Close details modal">Close</button>
        </div>
        <div className={`modal-body ${styles.detailsGrid}`}>
          <LabelValue label="Time" value={new Date(row.createdAt).toLocaleString()} />
          <LabelValue label="RAM (GB)" value={String(row.ramGB)} />
          <LabelValue label="OS" value={row.os} />
          <LabelValue label="Encoder" value={(row.encoderName ?? row.codec) || "-"} />
          <LabelValue label="FFmpeg Version" value={row.ffmpegVersion ?? "-"} />
          <LabelValue label="FPS" value={row.fps.toFixed(2)} />
          <LabelValue label="VMAF score" value={row.vmaf == null ? "-" : row.vmaf.toFixed(1)} />
          <LabelValue label="Relative File Size" value={relSize.toFixed(2)} />
          <LabelValue label="Submissions (accepted)" value={typeof row.samples === "number" ? String(row.samples) : "-"} />
        </div>
      </div>
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
  const s = cpu.toLowerCase();
  return s.includes("apple m1") || s.includes("apple m2") || s.includes("apple m3") || s.includes("apple m4") || s.includes("m1 ") || s.includes("m2 ") || s.includes("m3 ") || s.includes("m4 ");
}

function wikipediaAppleUrl(model: string): string | null {
  const m = model.toLowerCase();
  if (!m.includes("apple") && !m.startsWith("m")) return null;
  const match = m.match(/\bm([1-5])\b/);
  if (!match) return null;
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

function presetsForCodec(data: Benchmark[], codec: string): string[] {
  const set = new Set<string>();
  for (const r of data) if (r.codec === codec) set.add(r.preset);
  return Array.from(set).sort();
}
