import { fetchHardwareDirectory } from "../lib/api";
import type { HardwareDirectory } from "../lib/types";
import { realGpu } from "../lib/hardwareLabel";
import DataUnavailable from "../components/DataUnavailable";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function HardwarePage(_props: { searchParams?: Promise<Record<string, string | string[] | undefined>> }) {
  let directory: HardwareDirectory | null = null;
  try { directory = await fetchHardwareDirectory(); }
  catch (error) { console.error("Unable to load hardware coverage", error); }
  return <div className={`page ${styles.page}`}>
    <header className={styles.header}><div><p className={styles.kicker}>Community coverage</p><h1>Hardware</h1><p>Explore the machines behind the measurements. Open a hardware group to inspect its results.</p></div></header>
    {directory ? <>
      <section className={styles.stats} aria-label="Hardware corpus summary">
        <span className={styles.stat}><strong>{directory.items.length.toLocaleString()}</strong> hardware groups{directory.truncated ? " shown" : ""}</span>
        <span className={styles.stat}>Accepted and suspect runs are counted separately.</span>
      </section>
      {directory.truncated && <p className={styles.note}>Showing a limited directory. <a href="/">Browse all results</a> to find more hardware.</p>}
      <section className={styles.list} aria-label="Hardware groups">
        {directory.items.map(item => {
          const gpu = realGpu(item.gpuModel);
          const name = gpu || item.cpuModel;
          const subtitle = gpu
            ? gpu === item.cpuModel ? "GPU / accelerator" : item.cpuModel
            : item.gpuModel?.trim().toLowerCase() === "not-applicable" ? "GPU not applicable" : "GPU not reported";
          const href = `/?${new URLSearchParams(item.browseFilters).toString()}`;
          return <article key={item.id} className={styles.item}>
            <div className={styles.entityMain}><h2>{name}</h2><p>{subtitle}</p><p>{item.encoderCount} encoder{item.encoderCount === 1 ? "" : "s"} · {item.codecFamilies.map(codec => codec.toUpperCase()).join(", ")}</p></div>
            <div className={styles.counts}><span><strong>{item.acceptedCount.toLocaleString()}</strong> accepted</span><span><strong>{item.suspectCount.toLocaleString()}</strong> suspect</span><span>{item.configurationCount.toLocaleString()} configuration{item.configurationCount === 1 ? "" : "s"}</span></div>
            <a className="btn" href={href} aria-label={`Browse results for ${name}`}>Browse results</a>
          </article>;
        })}
        {directory.items.length === 0 && <p className={styles.empty}>No hardware measurements are available yet. <a href="/run">Contribute a benchmark</a>.</p>}
      </section>
      <aside className={styles.note}>These counts describe corpus coverage, not hardware rankings. Compare measurements only within a matching workload and environment.</aside>
    </> : <DataUnavailable href="/hardware" subject="Hardware results" />}
  </div>;
}
