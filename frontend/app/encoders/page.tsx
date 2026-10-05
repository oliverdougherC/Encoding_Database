import { fetchEncoderDirectory } from "../lib/api";
import type { EncoderDirectory } from "../lib/types";
import DataUnavailable from "../components/DataUnavailable";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function EncodersPage(_props: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  let directory: EncoderDirectory | null = null;
  try { directory = await fetchEncoderDirectory(); }
  catch (error) { console.error("Unable to load encoder coverage", error); }
  return <div className={`page ${styles.page}`}>
    <header><p className={styles.kicker}>Community coverage</p><h1>Encoders</h1><p>Encoder implementations represented in the corpus. Open an encoder to explore its settings and measurements.</p></header>
    {directory ? <>
      {directory.truncated && <p className={styles.note}>Showing a limited directory. <a href="/">Browse all results</a> to find more encoders.</p>}
      <section className={styles.grid} aria-label="Encoder coverage">
        {directory.items.map(item => <article className={styles.card} key={item.id}>
          <p className={styles.codec}>{item.codecFamily.toUpperCase()}</p><h2>{item.encoderName}</h2>
          <p className={styles.meta}>{item.configurationCount.toLocaleString()} configuration{item.configurationCount === 1 ? "" : "s"}</p>
          <div className={styles.counts}><span><strong>{item.acceptedCount.toLocaleString()}</strong> accepted</span><span><strong>{item.suspectCount.toLocaleString()}</strong> suspect</span></div>
          <a className="btn" href={`/?${new URLSearchParams(item.browseFilters).toString()}`} aria-label={`Browse results for ${item.encoderName}`}>Browse results</a>
        </article>)}
        {directory.items.length === 0 && <p className={styles.empty}>No encoder measurements are available yet. <a href="/run">Contribute a benchmark</a>.</p>}
      </section>
      <aside className={styles.note}>Coverage is not a quality ranking. Match workload, hardware, and settings before comparing performance.</aside>
    </> : <DataUnavailable href="/encoders" subject="Encoder results" />}
  </div>;
}
