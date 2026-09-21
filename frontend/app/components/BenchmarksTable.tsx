"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Benchmark } from "../lib/types";
import { WORKBENCH_PAGE_SIZE, buildWorkbenchSearchString, type EncoderTypeFilter, type WorkbenchSearchState, type WorkbenchSortKey } from "../lib/queryState";
import { measurementBasis, artifactIntegrity, artifactRetention, hasPublicPl } from "../lib/evidence";
import { realGpu } from "../lib/hardwareLabel";
import ComparePanel, { CompareStickyBar } from "./ComparePanel";
import styles from "./BenchmarksTable.module.css";

export type { Benchmark } from "../lib/types";

const formatSize = (n: number | null | undefined) => n == null ? "—" : n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
const formatBitrate = (n: number | null | undefined) => n == null ? "—" : `${(n / 1_000_000).toFixed(2)} Mbps`;
const value = (n: number | null | undefined, digits = 1) => n == null ? "—" : n.toFixed(digits);
const plStatus = (row: Benchmark) => hasPublicPl(row) ? "PL public" : "PL unavailable";

export const acceptedSamples = (row: Benchmark) => row.sampleCounts.accepted;

// One definition drives the colgroup, header cells, and body cells, so a
// header metric can never drift out of alignment with the column below it.
// Fixed px widths keep numeric columns stable; empty width means the fixed
// table layout splits the remaining space between the text columns.
type RowContext = { selected: boolean; canSelectMore: boolean; toggle: () => void; onDetails: () => void };
type Column = {
  head: string;
  headLabel?: string;
  sort?: WorkbenchSortKey;
  align?: "right";
  width: string;
  cell: (row: Benchmark, ctx: RowContext) => React.ReactNode;
};

const COLUMNS: Column[] = [
  {
    head: "", headLabel: "Select result for comparison", width: "42px",
    cell: (row, ctx) => <input type="checkbox" aria-label={`Select ${row.id} for comparison`} checked={ctx.selected} disabled={!ctx.selected && !ctx.canSelectMore} onChange={ctx.toggle} />,
  },
  {
    head: "Hardware", sort: "gpuModel", width: "",
    cell: (row) => { const gpu = realGpu(row.gpuModel); const secondary = gpu ? row.cpuModel : `CPU-only · ${row.os}`; return <><strong title={gpu ?? row.cpuModel}>{gpu ?? row.cpuModel}</strong><small title={secondary}>{secondary}</small></>; },
  },
  {
    head: "Encoder", sort: "codec", width: "",
    cell: (row) => <><strong title={row.encoderName}>{row.encoderName}</strong><small>{row.codecFamily.toUpperCase()} · FFmpeg {row.environment.ffmpegVersion}</small></>,
  },
  {
    head: "Configuration", sort: "preset", width: "",
    cell: (row) => <><span className="mono">{row.preset}</span><small title={`${row.recipe.rateControl.label} · ${row.workloadId}`}>{row.recipe.rateControl.label} · {row.workloadId}</small></>,
  },
  { head: "FPS", sort: "fps", align: "right", width: "84px", cell: (row) => value(row.performance.encodeFps ?? row.fps, 2) },
  { head: "VMAF", sort: "vmaf", align: "right", width: "84px", cell: (row) => value(row.quality.vmafMean ?? row.vmaf) },
  { head: "Bitrate", sort: "videoBitrateBps", align: "right", width: "110px", cell: (row) => formatBitrate(row.bitrate.videoBitrateBps ?? row.videoBitrateBps) },
  {
    head: "Evidence", sort: "samples", width: "160px",
    cell: (row) => <><strong>{row.status.centerBasis === "eligible-stable-groups" ? "Stable groups" : row.status.centerBasis === "suspect" ? "Suspect · review" : row.status.centerBasis === "accepted" ? "Accepted" : "Basis unknown"}</strong><small>{plStatus(row)} · {row.status.evidenceTier.toLowerCase()} evidence</small></>,
  },
  {
    head: "Runs", sort: "samples", align: "right", width: "104px",
    cell: (row) => <><strong>{acceptedSamples(row)} accepted</strong><small>{row.sampleCounts.suspect} suspect</small></>,
  },
  { head: "Details", width: "76px", cell: (_row, ctx) => <button className={styles.detail} onClick={ctx.onDetails}>View</button> },
];

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
  const searchInput = useRef<HTMLInputElement>(null);
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
  // "/" focuses the single results search field unless typing somewhere else.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes((document.activeElement?.tagName || ""))) {
        event.preventDefault();
        searchInput.current?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
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
      <label className={styles.search}><span className={styles.srOnly}>Search corpus results</span><input ref={searchInput} id="benchmark-search" className="input" placeholder="Search hardware, encoder, workload, preset, or context… (/)" value={state.search} onChange={e => update("search", e.target.value)} /></label>
      <select aria-label="Hardware vendor" className="input" value={state.encoderType} onChange={e => update("encoderType", e.target.value)}><option value="">All encoders</option><option value="hardware">Hardware encoders</option><option value="software">Software encoders</option></select>
      <input aria-label="Filter CPU" className="input" placeholder="CPU" value={state.cpu} onChange={e => update("cpu", e.target.value)} />
      <input aria-label="Filter GPU" className="input" placeholder="GPU" value={state.gpu} onChange={e => update("gpu", e.target.value)} />
      <input aria-label="Filter preset" className="input" placeholder="Preset" value={state.preset} onChange={e => update("preset", e.target.value)} />
      <div className={styles.controlButtons}>
        <button className="btn" onClick={() => setHardwareOpen(true)}>My Hardware{myHardware ? " · on" : ""}</button>
        <button className="btn" onClick={clearFilters}>Clear filters</button>
      </div>
    </div>
    <div className={styles.tableMeta}><span>{totalCount.toLocaleString()} benchmark results</span><span>Choose up to 4 recipe or environment identities to compare</span></div>
    <ResultTable rows={rows} selected={selected} toggle={toggle} onDetails={setDetails} sort={state.sort} dir={state.dir} setSort={setSort} />
    <div className={styles.pagination}><span>Page {state.page} of {Math.max(1, Math.ceil(totalCount / WORKBENCH_PAGE_SIZE))}</span><div><button className="btn" disabled={state.page <= 1} onClick={() => update("page", state.page - 1)}>Previous</button><button className="btn" disabled={state.page >= Math.ceil(totalCount / WORKBENCH_PAGE_SIZE)} onClick={() => update("page", state.page + 1)}>Next</button></div></div>
    <CompareStickyBar count={selected.size} onCompare={() => setCompare(true)} onClear={clear} />
    {details && <BenchmarkDetailsDialog row={details} close={() => setDetails(null)} />} {compare && selectedRows.length >= 2 && <ComparePanel rows={selectedRows} onClose={() => setCompare(false)} onClear={clear} />} {hardwareOpen && <MyHardware close={() => setHardwareOpen(false)} enabled={myHardware} apply={applyHardware} />}
  </section>;
}

function ResultTable({ rows, selected, toggle, onDetails, sort, dir, setSort }: { rows: Benchmark[]; selected: Set<string>; toggle: (id: string) => void; onDetails: (row: Benchmark) => void; sort: WorkbenchSortKey; dir: "asc" | "desc"; setSort: (key: WorkbenchSortKey) => void }) {
  const canSelectMore = selected.size < 4;
  return <div className={styles.tableWrap}>
    <table className={styles.table}>
      <colgroup>{COLUMNS.map((column, index) => <col key={`${column.head}-${index}`} style={column.width ? { width: column.width } : undefined} />)}</colgroup>
      <thead><tr>{COLUMNS.map((column, index) => <th key={`${column.head}-${index}`} scope="col" className={column.align === "right" ? styles.right : undefined} aria-sort={column.sort ? (sort === column.sort ? (dir === "asc" ? "ascending" : "descending") : "none") : undefined}>
        {column.sort
          ? <button className={styles.headButton} onClick={() => setSort(column.sort!)}>{column.head}{sort === column.sort ? (dir === "asc" ? " ↑" : " ↓") : ""}</button>
          : column.headLabel ? <span className={styles.srOnly}>{column.headLabel}</span> : column.head}
      </th>)}</tr></thead>
      <tbody>
        {rows.map((row) => <tr key={row.id} className={selected.has(row.id) ? styles.selected : undefined}>
          {COLUMNS.map((column, index) => <td key={`${column.head}-${index}`} className={column.align === "right" ? styles.right : undefined}>{column.cell(row, { selected: selected.has(row.id), canSelectMore, toggle: () => toggle(row.id), onDetails: () => onDetails(row) })}</td>)}
        </tr>)}
        {rows.length === 0 && <tr><td colSpan={COLUMNS.length} className={styles.empty}>No benchmark results match these filters. <a className={styles.inlineLink} href="/run">Run a benchmark</a></td></tr>}
      </tbody>
    </table>
  </div>;
}

export function BenchmarkDetailsDialog({ row, close }: { row: Benchmark; close: () => void }) {
  const sampleTotal = acceptedSamples(row);
  const publicPl = hasPublicPl(row);
  const qualityModel = row.quality.qualityModelId ?? row.versions.qualityModelId ?? "Unknown model";
  const confidence = row.confidence.available
    ? `${value(row.confidence.lower, 3)} to ${value(row.confidence.upper, 3)}`
    : row.confidence.unavailableReason;
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="result-title" onMouseDown={e => e.target === e.currentTarget && close()}><article className="modal"><header className="modal-header"><div><strong id="result-title">Benchmark result details</strong><div className="subtle">{row.workloadId} · {row.encoderName}</div></div><div className={styles.detailActions}><a className="btn" href={`/results/${encodeURIComponent(row.id)}`}>Result link</a><button className="btn" onClick={close}>Close</button></div></header><div className={styles.detailBody}><div className={styles.metricGrid}><Metric n="Encode FPS" v={value(row.performance.encodeFps ?? row.fps, 2)} /><Metric n="VMAF mean / p5" v={`${value(row.quality.vmafMean ?? row.vmaf)} / ${value(row.quality.vmafP5 ?? row.vmafP5)}`} /><Metric n="Video bitrate" v={formatBitrate(row.bitrate.videoBitrateBps ?? row.videoBitrateBps)} /><Metric n="Realtime ratio" v={row.performance.realTimeRatio == null ? "—" : `${row.performance.realTimeRatio.toFixed(2)}x`} /></div><dl className={styles.provenance}><Dt n="Measurement basis" v={measurementBasis(row)} /><Dt n="Artifact integrity" v={artifactIntegrity(row)} /><Dt n="Artifact retention" v={artifactRetention(row)} /><Dt n="Hardware identity" v={`${realGpu(row.gpuModel) ?? "CPU-only"} · ${row.cpuModel}`} /><Dt n="Encoder recipe" v={`${row.encoderName} · ${row.preset} · ${row.recipe.rateControl.label}`} /><Dt n="Recipe fingerprint" v={row.recipe.fingerprint} /><Dt n="Environment fingerprint" v={row.environment.fingerprint} /><Dt n="Environment" v={`${row.environment.osName} ${row.environment.osVersion} · ${row.environment.cpuArchitecture} · FFmpeg ${row.environment.ffmpegVersion}`} /><Dt n="Bit depth / chroma" v={`${row.recipe.bitDepth}-bit · ${row.recipe.chromaSubsampling} · ${row.recipe.pixelFormat}`} /><Dt n="Workload" v={row.workloadId} /><Dt n="Aggregate file size" v={formatSize(row.bitrate.fileSizeBytes ?? row.fileSizeBytes)} /><Dt n="Accepted runs" v={String(sampleTotal)} /><Dt n="Repetitions" v={String(row.sampleCounts.repetitions)} /><Dt n="Evidence tier" v={`${row.status.evidenceTier} · ${row.status.eligibleForDefaultRecommendation ? "recommendation-eligible" : "not recommendation-eligible"}`} /><Dt n="Accepted / suspect / rejected / invalid" v={`${row.sampleCounts.accepted} / ${row.sampleCounts.suspect} / ${row.sampleCounts.rejected} / ${row.sampleCounts.invalid}`} /><Dt n="Independent sources / machines / contributors" v={`${row.sampleCounts.independentSources ?? "—"} / ${row.sampleCounts.machines ?? "—"} / ${row.sampleCounts.contributors ?? "—"}`} /><Dt n="Benchmark protocol / suite" v={`${row.versions.benchmarkProtocolVersion} / ${row.versions.sourceSuiteVersion}`} /><Dt n="Score context" v={row.versions.referenceContextVersion == null ? "Unavailable: no public production DerivedResult published" : `${row.versions.referenceContextVersion} / ${row.versions.scoreContextId}`} /><Dt n="PL status" v={publicPl ? `${value(row.pl.total, 2)} total (${value(row.pl.components?.quality, 3)} / ${value(row.pl.components?.bitrate, 3)} / ${value(row.pl.components?.speed, 3)})` : "Unavailable"} /><Dt n="Confidence" v={confidence ?? "Unavailable"} /><Dt n="Quality model" v={qualityModel} /><Dt n="Reference bitrate" v={formatBitrate(row.bitrate.workloadReferenceBitrateBps)} /><Dt n="Aggregator version" v={row.versions.aggregatorVersion} /><Dt n="Created" v={new Date(row.createdAt).toLocaleString()} /></dl></div></article></div>;
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
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="hardware-title"><div className="modal"><header className="modal-header"><strong id="hardware-title">My Hardware</strong><button className="btn" onClick={close}>Close</button></header><div className={styles.hardwareForm}><p className="subtle">Stored only in this browser. Applying these values sends them as CPU and GPU filters before the server paginates corpus results. Editing the manual CPU or GPU filters overrides this selection.</p><label>GPU<input className="input" value={gpu} onChange={e => setGpu(e.target.value)} placeholder="e.g. RTX 4070" /></label><label>CPU<input className="input" value={cpu} onChange={e => setCpu(e.target.value)} placeholder="e.g. Ryzen 7950X" /></label><button className="btn btn-primary" onClick={save}>{enabled ? "Update hardware filter" : "Filter to my hardware"}</button></div></div></div>;
}
