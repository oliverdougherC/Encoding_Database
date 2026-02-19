import styles from "./plove.module.css";

// Static page — no data fetching, renders at build time (F-08)
export const dynamic = "force-static";

export default function PlovePage() {
  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>PL Score v6.0</h1>
      <p className={`subtle ${styles.intro}`}>
        PL Score (Platinum Labs) is a weighted ranking system for encoder runs. Version 6.0 expands beyond quality/size/speed to include efficiency and runtime reliability from hardware telemetry.
      </p>

      <section className={`card ${styles.section}`}>
        <h2 className={styles.sectionTitle}>How it&apos;s calculated</h2>
        <p className={styles.sectionDesc}>
          Scores are normalized inside the current filtered dataset, which keeps comparisons relevant to the rows you are actually viewing.
        </p>
        <ul className={styles.list}>
          <li><b>Core (user-tunable)</b>: Quality + Size + Speed, where your sliders set relative importance.</li>
          <li><b>Quality</b>: weighted blend of VMAF, SSIM, and PSNR with non-linear curves that reward strong quality and penalize weak outliers.</li>
          <li><b>Efficiency</b>: FPS/Watt, Quality/Watt, GPU power draw, and utilization behavior.</li>
          <li><b>Reliability</b>: CPU utilization spread, peak memory, and thermal throttling penalties.</li>
        </ul>
        <pre className={`kbd ${styles.codeBlock}`}><code>{`// PL Score v6.0 (simplified)
components = {
  quality: f(vmaf, ssim, psnr),
  size: inverseNormLog(fileSize / medianFileSize),
  speed: normLog(fps),
  efficiency: f(fpsPerWatt, qualityPerWatt, gpuPower, gpuUtil),
  reliability: f(cpuUtilSpread, peakMemory, thermalThrottle),
}

core = normalize(wQ, wS, wV) · [quality, size, speed]
plScore = clamp(
  core*0.78 + efficiency*0.14 + reliability*0.08 + confidenceAdjustment,
  0, 100
)`}</code></pre>
        <p className={`subtle ${styles.footnote}`}>
          The same encoder can score differently under different filters, because normalization is contextual to the visible cohort.
        </p>
      </section>

      <section className={`card ${styles.section}`}>
        <h2 className={styles.sectionTitle}>Why we use it</h2>
        <ul className={styles.listNoMargin}>
          <li><b>Production-minded</b>: factors in efficiency and thermal/runtime stability, not just pure throughput.</li>
          <li><b>Actionable</b>: reveals which rows are fast but power-hungry vs. balanced and reliable.</li>
          <li><b>Configurable core</b>: quality/size/speed priorities remain user-controlled.</li>
        </ul>
      </section>

      <section className={`card ${styles.section}`}>
        <h2 className={styles.sectionTitle}>Notes &amp; limitations</h2>
        <ul className={styles.listNoMargin}>
          <li>Automated quality metrics can disagree with human perception on edge content.</li>
          <li>Normalization is relative to visible rows; changing filters can change scores.</li>
          <li>PL Score is a ranking aid, not a replacement for detailed metric review.</li>
        </ul>
      </section>
    </div>
  );
}
