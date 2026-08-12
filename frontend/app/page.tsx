import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
import HeroSearch from "./components/HeroSearch";
import styles from "./page.module.css";

export const revalidate = 60;
function toParams(raw: Record<string, string | string[] | undefined> | undefined) {
  const params = new URLSearchParams();
  Object.entries(raw || {}).forEach(([key, rawValue]) => {
    const value = Array.isArray(rawValue) ? rawValue[0] : rawValue;
    if (value) params.set(key, value);
  });
  return params;
}

export default async function Home({ searchParams }: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  const state = parseWorkbenchSearchParams(toParams(searchParams ? await searchParams : undefined));
  let rows: Benchmark[] = [];
  let totalCount = 0;
  let error: string | null = null;
  try {
    const data = await fetchWorkbenchPage(state);
    rows = data.rows;
    totalCount = data.totalCount;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "Unable to load benchmark results";
  }
  const systems = new Set(rows.map((row) => row.environment.fingerprint)).size;
  const encoders = new Set(rows.map((row) => row.encoderName)).size;
  const codecs = new Set(rows.map((row) => row.codecFamily || row.codec)).size;

  return (
    <div className={`page ${styles.page}`}>
      <section className={styles.hero}>
        <div className={styles.heroMain}>
          <p className={styles.kicker}>V7 public corpus</p>
          <h1>Brevity is the soul of wit.</h1>
          <p className={styles.lede}>Browse V7 workload results backed by retained evidence, clear hardware context, and canonical recipes. Public PL stays blank until a production reference context is published.</p>
          <HeroSearch className={styles.heroSearch} />
          {!error && <div className={styles.datasetLine}>
            <span><strong>{totalCount.toLocaleString()}</strong> V7 aggregates</span>
            <span><strong>{systems}</strong> environments on this page</span>
            <span><strong>{encoders}</strong> encoders on this page</span>
          </div>}
        </div>
        <aside className={styles.corpus}>
          <p className={styles.kicker}>Corpus status</p>
          <div className={styles.big}>{totalCount.toLocaleString()}</div>
          <p className={styles.corpusLabel}>accepted V7 workload aggregates available to inspect</p>
          <div className={styles.coverage}>
            <div><strong>{systems}</strong><span>environments shown</span></div>
            <div><strong>{encoders}</strong><span>encoders shown</span></div>
            <div><strong>{codecs}</strong><span>codec families</span></div>
            <div><strong>60s</strong><span>data refresh</span></div>
          </div>
          <p className={styles.callout}><strong>Transparent by design.</strong> Legacy `/query` aggregates remain separate; this surface is V7-only.</p>
        </aside>
      </section>
      <div className={styles.sectionHead} id="results">
        <div><h2>Browse corpus</h2><p>Open a row to inspect immutable recipe and environment identity, evidence tier, bitrate, confidence, and version lineage.</p></div>
      </div>
      {error
        ? <div className={styles.error}>Unable to load results: {error}</div>
        : <BenchmarksTable initialData={rows} totalCount={totalCount} currentPage={state.page} />}
      <aside className={styles.note}>
        <strong>About this V7 surface</strong>
        <span>Each row is a retained V7 workload aggregate. Test-only reference contexts never surface as public PL, and submission-specific notes or personal media are never attributed to a corpus row.</span>
        <a href={`/methodology?${buildWorkbenchSearchString(state)}`}>Read methodology</a>
      </aside>
    </div>
  );
}
