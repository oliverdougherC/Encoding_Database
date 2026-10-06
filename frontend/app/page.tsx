import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
import styles from "./page.module.css";
import DataUnavailable from "./components/DataUnavailable";
import { HOME_DESCRIPTION, HOME_TITLE, pageMetadata, websiteSchema } from "./lib/seo";

export const metadata = pageMetadata("/", HOME_TITLE, HOME_DESCRIPTION);

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
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteSchema).replace(/</g, "\\u003c") }} />
      <section className={styles.intro}>
        <p className={styles.kicker}>Community benchmark corpus</p>
        <h1>Video codec database &amp; encoding benchmarks.</h1>
        <p className={styles.lede}>Compare encoding performance with EncodingDB, a public database of FFmpeg video benchmarks. Explore encoding speed, VMAF quality, and bitrate across encoders, presets, and CPU or GPU hardware — then contribute your own measurements.</p>
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
      <section className={styles.intro} aria-labelledby="codec-comparison-heading">
        <h2 id="codec-comparison-heading">Compare video codecs, encoders, and hardware</h2>
        <p className={styles.lede}>A video codec defines a compression format, such as H.264 (AVC), H.265 (HEVC), or AV1. An encoder is an implementation of that format, such as x264, x265, or SVT-AV1. Encoder settings and hardware affect the balance between speed, visual quality, and file size.</p>
        <p className={styles.lede}>Browse the <a href="/encoders">encoder benchmark index</a> for measured implementations and the <a href="/hardware">hardware benchmark index</a> for CPU and GPU coverage. Results report frames per second (FPS), VMAF perceptual quality, and video bitrate alongside the exact recipe and environment.</p>
        <p className={styles.lede}>Match source workload and settings before comparing results. Read the <a href="/methodology">benchmark methodology</a> to understand scoring and evidence limits, or explore <a href="/leaderboards">encoder leaderboards</a> where eligible results are available.</p>
      </section>
    </div>
  );
}
