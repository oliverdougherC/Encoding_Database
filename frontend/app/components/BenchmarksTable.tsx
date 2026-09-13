"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Benchmark } from "../lib/types";
import { WORKBENCH_PAGE_SIZE, buildWorkbenchSearchString, type EncoderTypeFilter, type WorkbenchSearchState, type WorkbenchSortKey } from "../lib/queryState";
import ComparePanel, { CompareStickyBar } from "./ComparePanel";
import styles from "./BenchmarksTable.module.css";

export type { Benchmark } from "../lib/types";

const columns = "42px minmax(210px,2fr) minmax(165px,1.4fr) minmax(245px,2fr) 92px 92px 118px 120px 88px 74px";
const formatSize = (n: number | null | undefined) => n == null ? "—" : n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
const formatBitrate = (n: number | null | undefined) => n == null ? "—" : `${(n / 1_000_000).toFixed(2)} Mbps`;
const value = (n: number | null | undefined, digits = 1) => n == null ? "—" : n.toFixed(digits);
const plStatus = (row: Benchmark) => row.status.scoring === "PUBLIC" ? "PL public" : "PL unavailable";
const confidenceLabel = (row: Benchmark) => row.confidence.available ? `${value(row.confidence.width, 3)} width` : "No public interval";

export const acceptedSamples = (row: Benchmark) => row.sampleCounts.accepted;

export default function BenchmarksTable({ initialData, totalCount, currentPage }: { initialData: Benchmark[]; totalCount: number; currentPage: number }) {
  const router = useRouter(), pathname = usePathname() ?? "/", params = useSearchParams();
  const initial = useMemo<WorkbenchSearchState>(() => ({
    page: currentPage,
    cpu: params.get("cpu") || "",
    gpu: params.get("gpu") || "",
    search: params.get("search") || "",
    preset: params.get("preset") || "",
    sort: (params.get("sort") as WorkbenchSortKey) || "",
    dir: params.get("dir") === "asc" ? "asc" : "desc",
    encoderType: (params.get("encoderType") as EncoderTypeFilter) || "",
  }), [currentPage, params]);
  const [state, setState] = useState(initial), [selected, setSelected] = useState<Set<string>>(new Set()), [details, setDetails] = useState<Benchmark | null>(null), [compare, setCompare] = useState(false), [myHardware, setMyHardware] = useState(false), [hardwareOpen, setHardwareOpen] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const timer = setTimeout(() => {
      const q = buildWorkbenchSearchString(state);
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    }, 240);
    return () => clearTimeout(timer);
  }, [state, pathname, router]);
  useEffect(() => {
    try {
      const raw = localStorage.getItem("encodingdb-my-hardware");
      const pref = raw ? JSON.parse(raw) : {};
      if (pref.cpu || pref.gpu) {
        setMyHardware(true);
        setState((s) => s.cpu || s.gpu ? s : { ...s, cpu: pref.cpu || "", gpu: pref.gpu || "", page: 1 });
      }
    } catch {
      // Storage is optional.
    }
  }, []);
  const resetComparison = () => { setSelected(new Set()); setCompare(false); };
  const update = (key: keyof WorkbenchSearchState, value: string | number) => {
    if (key === "cpu" || key === "gpu") setMyHardware(false);
    resetComparison();
    setState((s) => ({ ...s, [key]: value, page: key === "page" ? Number(value) : 1 }));
  };
  const rows = initialData;
  const toggle = useCallback((id: string) => setSelected((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else if (next.size < 4) next.add(id);
    return next;
  }), []);
  const setSort = (key: WorkbenchSortKey) => {
    resetComparison();
    setState((s) => ({ ...s, sort: key, dir: s.sort === key && s.dir === "desc" ? "asc" : "desc", page: 1 }));
  };
  const clear = () => { setSelected(new Set()); setCompare(false); };
  const clearFilters = () => { setMyHardware(false); resetComparison(); setState({ page: 1, cpu: "", gpu: "", search: "", preset: "", sort: "", dir: "desc", encoderType: "" }); };
  const applyHardware = (gpu: string, cpu: string) => { setMyHardware(Boolean(gpu || cpu)); resetComparison(); setState((s) => ({ ...s, gpu, cpu, page: 1 })); };
  const selectedRows = rows.filter((row) => selected.has(row.id));
  return <section className={styles.section} aria-label="Benchmark results">
    <div className={styles.controls}>
      <label className={styles.search}><span className="srOnly">Search V7 public corpus</span><input id="benchmark-search" className="input" placeholder="Search hardware, encoder, workload, preset, or context…" value={state.search} onChange={e => update("search", e.target.value)} /></label>
      <select aria-label="Hardware vendor" className="input" value={state.encoderType} onChange={e => update("encoderType", e.target.value)}><option value="">All encoders</option><option value="hardware">Hardware encoders</option><option value="software">Software encoders</option></select>
      <input aria-label="Filter CPU" className="input" placeholder="CPU" value={state.cpu} onChange={e => update("cpu", e.target.value)} />
      <input aria-label="Filter GPU" className="input" placeholder="GPU" value={state.gpu} onChange={e => update("gpu", e.target.value)} />
      <input aria-label="Filter preset" className="input" placeholder="Preset" value={state.preset} onChange={e => update("preset", e.target.value)} />
      <button className="btn" onClick={() => setHardwareOpen(true)}>My Hardware{myHardware ? " · on" : ""}</button>
      <button className="btn" onClick={clearFilters}>Clear filters</button>
    </div>
    <div className={styles.tableMeta}><span>{totalCount.toLocaleString()} V7 workload aggregates</span><span>Choose up to 4 recipe or environment identities to compare</span></div>
    <VirtualTable rows={rows} selected={selected} toggle={toggle} onDetails={setDetails} sort={state.sort} dir={state.dir} setSort={setSort} />
    <div className={styles.pagination}><span>Page {state.page} of {Math.max(1, Math.ceil(totalCount / WORKBENCH_PAGE_SIZE))}</span><div><button className="btn" disabled={state.page <= 1} onClick={() => update("page", state.page - 1)}>Previous</button><button className="btn" disabled={state.page >= Math.ceil(totalCount / WORKBENCH_PAGE_SIZE)} onClick={() => update("page", state.page + 1)}>Next</button></div></div>
    <CompareStickyBar count={selected.size} onCompare={() => setCompare(true)} onClear={clear} />
    {details && <BenchmarkDetailsDialog row={details} close={() => setDetails(null)} />} {compare && selectedRows.length >= 2 && <ComparePanel rows={selectedRows} onClose={() => setCompare(false)} onClear={clear} />} {hardwareOpen && <MyHardware close={() => setHardwareOpen(false)} enabled={myHardware} apply={applyHardware} />}
  </section>;
}

function VirtualTable({ rows, selected, toggle, onDetails, sort, dir, setSort }: { rows: Benchmark[]; selected: Set<string>; toggle: (id: string) => void; onDetails: (row: Benchmark) => void; sort: WorkbenchSortKey; dir: "asc" | "desc"; setSort: (key: WorkbenchSortKey) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => ref.current, estimateSize: () => 62, overscan: 8 });
  const head = (name: string, key: WorkbenchSortKey, cls = "") => <button className={`${styles.headButton} ${cls}`} onClick={() => setSort(key)} aria-sort={sort === key ? (dir === "asc" ? "ascending" : "descending") : "none"}>{name}{sort === key ? (dir === "asc" ? " ↑" : " ↓") : ""}</button>;
  return <div className={styles.tableWrap}><div className={styles.gridHeader} style={{ "--columns": columns } as React.CSSProperties}><span /><span>{head("Hardware", "gpuModel")}</span><span>{head("Encoder", "codec")}</span><span>{head("Configuration", "preset")}</span><span>{head("FPS", "fps", styles.right)}</span><span>{head("VMAF", "vmaf", styles.right)}</span><span>{head("Bitrate", "videoBitrateBps", styles.right)}</span><span>{head("Evidence", "samples")}</span><span>{head("Samples", "samples", styles.right)}</span><span>Details</span></div><div ref={ref} className={styles.scroller} role="table"><div style={{ height: v.getTotalSize(), position: "relative" }}>{v.getVirtualItems().map((item) => { const row = rows[item.index]; const sampleTotal = acceptedSamples(row); return <div key={row.id} className={`${styles.row} ${selected.has(row.id) ? styles.selected : ""}`} style={{ "--columns": columns, height: item.size, transform: `translateY(${item.start}px)` } as React.CSSProperties} role="row"><span><input type="checkbox" aria-label={`Select ${row.id} for comparison`} checked={selected.has(row.id)} disabled={!selected.has(row.id) && selected.size >= 4} onChange={() => toggle(row.id)} /></span><span><strong>{row.gpuModel || row.cpuModel}</strong><small>{row.gpuModel ? row.cpuModel : row.os}</small></span><span><strong>{row.encoderName}</strong><small>{row.codecFamily.toUpperCase()} · {row.environment.ffmpegVersion}</small></span><span><span className="mono">{row.preset}</span><small>{row.recipe.rateControl.label} · {row.workloadId}</small></span><span className="numeric">{value(row.performance.encodeFps ?? row.fps, 2)}</span><span className="numeric">{value(row.quality.vmafMean ?? row.vmaf)}</span><span className="numeric">{formatBitrate(row.bitrate.videoBitrateBps ?? row.videoBitrateBps)}</span><span><strong>{row.status.evidenceTier}</strong><small>{plStatus(row)} · {confidenceLabel(row)}</small></span><span>{sampleTotal < 3 ? <em className={styles.lowSample}>{sampleTotal}</em> : sampleTotal}</span><span><button className={styles.detail} onClick={() => onDetails(row)}>View</button></span></div>; })}{rows.length === 0 && <div className={styles.empty}>No V7 workload aggregates match these filters. <button className={styles.inlineButton} onClick={() => location.assign("/run")}>Run a benchmark</button></div>}</div></div></div>;
}

export function BenchmarkDetailsDialog({ row, close }: { row: Benchmark; close: () => void }) {
  const sampleTotal = acceptedSamples(row);
  const publicPl = row.status.scoring === "PUBLIC";
  const qualityModel = row.quality.qualityModelId ?? row.versions.qualityModelId ?? "Unknown model";
  const confidence = row.confidence.available
    ? `${value(row.confidence.lower, 3)} to ${value(row.confidence.upper, 3)}`
    : row.confidence.unavailableReason;
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="result-title" onMouseDown={e => e.target === e.currentTarget && close()}><article className="modal"><header className="modal-header"><div><strong id="result-title">V7 aggregate details</strong><div className="subtle">Recipe {row.recipe.fingerprint} on environment {row.environment.fingerprint}. Legacy benchmark aggregates are exposed separately.</div></div><button className="btn" onClick={close}>Close</button></header><div className={styles.detailBody}><div className={styles.metricGrid}><Metric n="Encode FPS" v={value(row.performance.encodeFps ?? row.fps, 2)} /><Metric n="VMAF mean / p5" v={`${value(row.quality.vmafMean ?? row.vmaf)} / ${value(row.quality.vmafP5 ?? row.vmafP5)}`} /><Metric n="Video bitrate" v={formatBitrate(row.bitrate.videoBitrateBps ?? row.videoBitrateBps)} /><Metric n="Realtime ratio" v={row.performance.realTimeRatio == null ? "—" : `${row.performance.realTimeRatio.toFixed(2)}x`} /></div><dl className={styles.provenance}><Dt n="Hardware identity" v={`${row.gpuModel || "CPU-only"} · ${row.cpuModel}`} /><Dt n="Encoder recipe" v={`${row.encoderName} · ${row.preset} · ${row.recipe.rateControl.label}`} /><Dt n="Recipe fingerprint" v={row.recipe.fingerprint} /><Dt n="Environment fingerprint" v={row.environment.fingerprint} /><Dt n="Environment" v={`${row.environment.osName} ${row.environment.osVersion} · ${row.environment.cpuArchitecture} · FFmpeg ${row.environment.ffmpegVersion}`} /><Dt n="Bit depth / chroma" v={`${row.recipe.bitDepth}-bit · ${row.recipe.chromaSubsampling} · ${row.recipe.pixelFormat}`} /><Dt n="Workload" v={row.workloadId} /><Dt n="Aggregate file size" v={formatSize(row.bitrate.fileSizeBytes ?? row.fileSizeBytes)} /><Dt n="Accepted runs" v={String(sampleTotal)} /><Dt n="Repetitions" v={String(row.sampleCounts.repetitions)} /><Dt n="Evidence tier" v={`${row.status.evidenceTier}${row.status.eligibleForDefaultRecommendation ? " · recommendation-eligible" : ""}`} /><Dt n="Accepted / suspect / rejected / invalid" v={`${row.sampleCounts.accepted} / ${row.sampleCounts.suspect} / ${row.sampleCounts.rejected} / ${row.sampleCounts.invalid}`} /><Dt n="Independent sources / machines / contributors" v={`${row.sampleCounts.independentSources ?? "—"} / ${row.sampleCounts.machines ?? "—"} / ${row.sampleCounts.contributors ?? "—"}`} /><Dt n="Benchmark protocol / suite" v={`${row.versions.benchmarkProtocolVersion} / ${row.versions.sourceSuiteVersion}`} /><Dt n="Score context" v={row.versions.referenceContextVersion == null ? "Unavailable: no public production DerivedResult published" : `${row.versions.referenceContextVersion} / ${row.versions.scoreContextId}`} /><Dt n="PL status" v={publicPl ? `${value(row.pl.total, 2)} total (${value(row.pl.components?.quality, 3)} / ${value(row.pl.components?.bitrate, 3)} / ${value(row.pl.components?.speed, 3)})` : "Unavailable"} /><Dt n="Confidence" v={confidence ?? "Unavailable"} /><Dt n="Quality model" v={qualityModel} /><Dt n="Reference bitrate" v={formatBitrate(row.bitrate.workloadReferenceBitrateBps)} /><Dt n="Aggregator version" v={row.versions.aggregatorVersion} /><Dt n="Created" v={new Date(row.createdAt).toLocaleString()} /></dl></div></article></div>;
}

const Metric = ({ n, v }: { n: string; v: string }) => <div><dt>{n}</dt><dd className="numeric">{v}</dd></div>;
const Dt = ({ n, v }: { n: string; v: string }) => <><dt>{n}</dt><dd>{v}</dd></>;

function MyHardware({ close, enabled, apply }: { close: () => void; enabled: boolean; apply: (gpu: string, cpu: string) => void }) {
  const [gpu, setGpu] = useState(""), [cpu, setCpu] = useState("");
  useEffect(() => {
    try {
      const p = JSON.parse(localStorage.getItem("encodingdb-my-hardware") || "{}");
      setGpu(p.gpu || "");
      setCpu(p.cpu || "");
    } catch {
      // Storage is optional.
    }
  }, []);
  const save = () => {
    try {
      if (gpu || cpu) localStorage.setItem("encodingdb-my-hardware", JSON.stringify({ gpu, cpu }));
      else localStorage.removeItem("encodingdb-my-hardware");
    } catch {
      // Storage is optional.
    }
    apply(gpu, cpu);
    close();
  };
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="hardware-title"><div className="modal"><header className="modal-header"><strong id="hardware-title">My Hardware</strong><button className="btn" onClick={close}>Close</button></header><div className={styles.hardwareForm}><p className="subtle">Stored only in this browser. Applying these values sends them as CPU and GPU filters before the server paginates V7 corpus results. Editing the manual CPU or GPU filters overrides this selection.</p><label>GPU<input className="input" value={gpu} onChange={e => setGpu(e.target.value)} placeholder="e.g. RTX 4070" /></label><label>CPU<input className="input" value={cpu} onChange={e => setCpu(e.target.value)} placeholder="e.g. Ryzen 7950X" /></label><button className="btn btn-primary" onClick={save}>{enabled ? "Update hardware filter" : "Filter to my hardware"}</button></div></div></div>;
}
