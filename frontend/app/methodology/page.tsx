import { DEFAULT_PL_SCORE_V7_POLICY } from "../lib/plScore";
import FormulaExplorer from "./FormulaExplorer";
import KatexMath from "./KatexMath";
import styles from "./page.module.css";

const { qualityExponent, scoreFormulaVersion, speedCurveRate, speedSaturationRealtime } =
  DEFAULT_PL_SCORE_V7_POLICY;
const speedDenominatorExponent = speedCurveRate * speedSaturationRealtime;

const effectiveQuality = String.raw`V_{\mathrm{PL}} = 0.85\,V_{\mathrm{mean}} + 0.15\,V_{P5}`;
const qualityTerm = String.raw`Q = \left[\operatorname{clamp}\left(\frac{V_{\mathrm{PL}} - 20}{80}, 0, 1\right)\right]^{${qualityExponent}}`;
const bitrateTerm = String.raw`B = \frac{1}{1 + \frac{R_{\mathrm{enc}}}{R_{\mathrm{ref}}}}`;
const speedTerm = String.raw`S = \frac{1 - \exp\!\left(-${speedCurveRate}\,\frac{\mathrm{FPS}_{\mathrm{enc}}}{\mathrm{FPS}_{\mathrm{src}}}\right)}{1 - \exp\!\left(-${speedDenominatorExponent}\right)}`;
const generalPl7 = String.raw`100\exp\!\left(\frac{1}{n}\sum_{i=1}^{n}\ln\!\frac{\mathrm{PL7}_i}{100}\right)`;

const calculationRows = [
  ["Effective quality", effectiveQuality],
  ["Quality term", qualityTerm],
  ["Bitrate term", bitrateTerm],
  ["Speed term", speedTerm],
] as const;

const rules = [
  "Missing required measurements produce no canonical PL7 score.",
  "Bitrate is compared with a fixed reference for that workload, not the current leaderboard.",
  "PL Score, PL Fit, and confidence are separate concepts.",
  "Every score is tied to versioned benchmark and provenance data.",
] as const;

export default function MethodologyPage() {
  return (
    <div className={`page ${styles.page}`}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>PL Score v7</p>
          <h1>Methodology</h1>
          <p className={styles.intro}>
            PL Score v7 combines quality, bitrate efficiency, and encode speed into one fixed score for a single benchmark workload.
          </p>
        </div>
        <p className={styles.version}>v{scoreFormulaVersion} · pilot</p>
      </header>

      <FormulaExplorer />

      <section className={styles.section} aria-labelledby="calculation-heading">
        <h2 id="calculation-heading">Calculation</h2>
        <div className={styles.calculation}>
          {calculationRows.map(([label, expression]) => (
            <div className={styles.calculationRow} key={label}>
              <span>{label}</span>
              <KatexMath expression={expression} display />
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="general-heading">
        <h2 id="general-heading">General PL7</h2>
        <div className={styles.general}>
          <p>General PL7 requires complete, equal-class suite coverage.</p>
          <KatexMath expression={generalPl7} display />
        </div>
      </section>

      <section className={styles.section} aria-labelledby="rules-heading">
        <h2 id="rules-heading">Rules</h2>
        <ul className={styles.rules}>
          {rules.map((rule) => <li key={rule}>{rule}</li>)}
        </ul>
      </section>

      <details className={styles.notes}>
        <summary>
          <span>Technical notes</span>
          <small>provenance, limitations, and score semantics</small>
        </summary>
        <div className={styles.notesBody}>
          <p><strong>Required measurements:</strong> VMAF mean, VMAF P5, video bitrate, encode FPS, source FPS, and workload reference bitrate.</p>
          <p><strong>Provenance:</strong> formula version, benchmark protocol version, source suite version, workload ID, reference bitrate, and VMAF model ID.</p>
          <p>PL7 describes a workload under a benchmark protocol. It is not a universal statement about an encoder.</p>
          <p>PL Fit is the personalized ranking layer. Confidence describes evidence quality. Neither changes the public PL7 formula.</p>
        </div>
      </details>

      <p className={styles.epoch}><strong>Pre-epoch:</strong> the v7 formula is fixed, but calibration remains provisional. Pilot results are not recommendation-eligible.</p>
    </div>
  );
}
