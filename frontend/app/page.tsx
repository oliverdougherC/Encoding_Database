import { Suspense } from "react";
import BenchmarksTable, { Benchmark } from "./components/BenchmarksTable";
import ErrorBoundary from "./components/ErrorBoundary";
import StatsCards from "./components/StatsCards";
import { fetchBenchmarks } from "./lib/fetchBenchmarks";
import styles from "./page.module.css";

export const revalidate = 60;

export default async function Home() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Encoding Benchmarks</h1>
      <p className={styles.sourceLink}>
        Source Code: <a href="https://github.com/oliverdougherC/Encoding_Database" target="_blank" rel="noreferrer" className={styles.sourceLinkAnchor}>github.com/oliverdougherC/Encoding_Database</a>
      </p>
      <div className={`card ${styles.clientCard}`}>
        <div>
          <div className={styles.clientCardTitle}>Get the Client</div>
          <div className={`subtle ${styles.clientCardDesc}`}>Download the prebuilt client from GitHub Releases.</div>
        </div>
        <a className={`btn ${styles.releasesBtn}`} href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer">Open Releases</a>
      </div>
      {error ? (
        <div className={styles.errorBox}>
          Failed to load data: {error}
        </div>
      ) : (
        <>
          <StatsCards data={data} />
          <ErrorBoundary>
            <Suspense fallback={<div style={{ padding: 16, color: "var(--muted)" }}>Loading filters...</div>}>
              <BenchmarksTable initialData={data} />
            </Suspense>
          </ErrorBoundary>
          <div className={`card ${styles.aboutCard}`}>
            <div className={styles.aboutTitle}>About the test video (sample.mp4)</div>
            <div className={`subtle ${styles.aboutDesc}`}>
              Recorded in ProRes 4:2:2, 10-bit, 3840x2160, 30FPS SDR. <br />
              Transcoded to x264 4:2:0, 8-bit, 1920x1080, RF 0, profile main, level 4.0, tune none, preset veryslow, VFR 30FPS SDR.
            </div>
          </div>

        </>
      )}
    </div>
  );
}
