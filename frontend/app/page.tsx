import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
import styles from "./page.module.css";
import DataUnavailable from "./components/DataUnavailable";

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
    console.error("Unable to load benchmark results", cause);
    error = "unavailable";
  }
  const accepted = rows.reduce((sum, row) => sum + row.sampleCounts.accepted, 0);
  const suspect = rows.reduce((sum, row) => sum + row.sampleCounts.suspect, 0);
  return (
    <div className={`page ${styles.page}`}>
      <section className={styles.intro}>
        <p className={styles.kicker}>Community benchmark corpus</p>
        <h1>Compare encoding performance.</h1>
        <p className={styles.lede}>Real measurements of encoding speed, quality, and file size. Explore a result or contribute your own.</p>
        <div className={styles.ctaRow}>
          <a className="btn btn-primary" href="/run">Download &amp; run a benchmark</a>
          <a className="btn" href="/methodology">How scoring works</a>
        </div>
        {error
          ? <p className={styles.statusLine}>Corpus counts temporarily unavailable</p>
          : <p className={styles.statusLine}><strong>{accepted.toLocaleString()} accepted · {suspect.toLocaleString()} suspect</strong> runs on this page. Public scores stay blank until a public reference context is published.</p>}
      </section>
      <div className={styles.sectionHead} id="results">
        <div><h2>Browse results</h2><p>Select results to compare, or open a row for its measurements and evidence.</p></div>
      </div>
      {error
        ? <DataUnavailable href={buildWorkbenchSearchString(state) ? `/?${buildWorkbenchSearchString(state)}` : "/"} />
        : <BenchmarksTable initialData={rows} totalCount={totalCount} currentPage={state.page} />}
      <aside className={styles.note}>
        <strong>About this corpus</strong>
        <span>Each row combines repeated measurements of one recipe on one machine. Suspect runs remain visible for review.</span>
        <a href={`/methodology?${buildWorkbenchSearchString(state)}`}>Read methodology</a>
      </aside>
    </div>
  );
}
