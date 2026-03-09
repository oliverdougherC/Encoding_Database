import PageHeader from "../components/ui/PageHeader";
import SectionCard from "../components/ui/SectionCard";
import styles from "./plove.module.css";

export const dynamic = "force-static";

export default function PlovePage() {
  return (
    <div className={`page ${styles.layout}`}>
      <PageHeader
        title="PL Score Reference"
        subtitle="Understand how PL Score v6.0 ranks encoder runs across quality, efficiency, and reliability."
      />

      <div className={styles.weightGrid}>
        <div className={styles.weightCard}>
          <div className={styles.weightValue}>78%</div>
          <div className={styles.weightLabel}>Core</div>
          <div className={styles.weightDesc}>Quality + Size + Speed</div>
        </div>
        <div className={styles.weightCard}>
          <div className={styles.weightValue}>14%</div>
          <div className={styles.weightLabel}>Efficiency</div>
          <div className={styles.weightDesc}>FPS/Watt + GPU utilization</div>
        </div>
        <div className={styles.weightCard}>
          <div className={styles.weightValue}>8%</div>
          <div className={styles.weightLabel}>Reliability</div>
          <div className={styles.weightDesc}>CPU stability + thermals</div>
        </div>
      </div>

      <SectionCard title="How It Is Calculated">
        <p className={styles.paragraph}>
          PL Score (Platinum Labs) is a weighted ranking system for encoder runs. Version 6.0 expands beyond
          quality/size/speed to include efficiency and runtime reliability from hardware telemetry.
        </p>
        <pre className={`kbd ${styles.codeBlock}`}><code>{`// PL Score v6.0 (simplified)
components = {
  quality: f(vmaf, ssim, psnr),
  size: inverseNormLog(fileSize / medianFileSize),
  speed: normLog(fps),
  efficiency: f(fpsPerWatt, qualityPerWatt, gpuPower, gpuUtil),
  reliability: f(cpuUtilSpread, peakMemory, thermalThrottle),
}

core = normalize(wQ, wS, wV) · [quality, size, speed]
plScore = clamp(core*0.78 + efficiency*0.14 + reliability*0.08 + confidenceAdjustment, 0, 100)`}</code></pre>
      </SectionCard>

      <SectionCard title="Why We Use It">
        <ul className={styles.list}>
          <li><b>Production-minded</b>: includes efficiency and runtime stability.</li>
          <li><b>Actionable</b>: separates speed-only winners from balanced profiles.</li>
          <li><b>Configurable</b>: quality/size/speed priority remains user-controlled.</li>
        </ul>
      </SectionCard>

      <SectionCard title="Limits">
        <ul className={styles.list}>
          <li>Automated quality metrics can diverge from human perception in edge content.</li>
          <li>Normalization is contextual to visible rows and active filters.</li>
          <li>Use PL Score as a ranking aid, not as sole decision criteria.</li>
        </ul>
      </SectionCard>
    </div>
  );
}
