import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
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
  const accepted = rows.reduce((sum, row) => sum + row.sampleCounts.accepted, 0);
  const suspect = rows.reduce((sum, row) => sum + row.sampleCounts.suspect, 0);

  return (
    <div className={`page ${styles.page}`}>
      <section className={styles.intro}>
        <p className={styles.kicker}>Community benchmark corpus</p>
        <h1>Compare encoder speed and quality — then add your own numbers.</h1>
        <p className={styles.lede}>Every result here is a community run of the same canonical clips with a reproducible FFmpeg recipe, kept together with the evidence behind it. Download the client, pick a measurement sweep, and your accepted runs join this table.</p>
        <div className={styles.ctaRow}>
          <a className="btn btn-primary" href="/run">Download &amp; run a benchmark</a>
          <a className="btn" href="/methodology">How scoring works</a>
        </div>
        {error
          ? <p className={styles.statusLine}>Corpus counts temporarily unavailable</p>
          : <p className={styles.statusLine}><strong>{accepted.toLocaleString()} accepted · {suspect.toLocaleString()} suspect</strong> runs on this page. Public scores stay blank until a public reference context is published.</p>}
      </section>
      <div className={styles.sectionHead} id="results">
        <div><h2>Browse results</h2><p>Open a row to inspect recipe and environment identity, evidence tier, bitrate, confidence, and version lineage.</p></div>
      </div>
      {error
        ? <div className={styles.error}>Unable to load results: {error}</div>
        : <BenchmarksTable initialData={rows} totalCount={totalCount} currentPage={state.page} />}
      <aside className={styles.note}>
        <strong>About this corpus</strong>
        <span>Each row aggregates repeated measurements of one recipe on one machine. Suspect measurements remain visible for review, and submission-specific notes or personal media are never attached to a corpus row.</span>
        <a href={`/methodology?${buildWorkbenchSearchString(state)}`}>Read methodology</a>
      </aside>
    </div>
  );
}
