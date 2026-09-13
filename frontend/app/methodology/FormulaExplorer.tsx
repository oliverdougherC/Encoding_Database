"use client";

import { useState } from "react";
import { DEFAULT_PL_SCORE_V7_POLICY, PL_SCORE_V7_WEIGHTS } from "../lib/plScore";
import KatexMath from "./KatexMath";
import styles from "./page.module.css";

type ComponentKey = "quality" | "bitrate" | "speed";

const weights = {
  quality: PL_SCORE_V7_WEIGHTS.quality.toFixed(2),
  bitrate: PL_SCORE_V7_WEIGHTS.bitrate.toFixed(2),
  speed: PL_SCORE_V7_WEIGHTS.speed.toFixed(2),
};

const components = {
  quality: {
    symbol: "Q",
    title: "Quality",
    percentage: `${PL_SCORE_V7_WEIGHTS.quality * 100}%`,
    description: "Uses both average VMAF and the lower tail so short bad moments are not hidden by a strong mean.",
    equation: String.raw`0.85\,V_{\mathrm{mean}} + 0.15\,V_{P5}`,
  },
  bitrate: {
    symbol: "B",
    title: "Bitrate",
    percentage: `${PL_SCORE_V7_WEIGHTS.bitrate * 100}%`,
    description: "Compares encoded bitrate with a frozen reference bitrate for the same workload.",
    equation: String.raw`B = \frac{1}{1 + \frac{R_{\mathrm{enc}}}{R_{\mathrm{ref}}}}`,
  },
  speed: {
    symbol: "S",
    title: "Speed",
    percentage: `${PL_SCORE_V7_WEIGHTS.speed * 100}%`,
    description: `Measures encode speed relative to playback speed, with diminishing returns and a cap at ${DEFAULT_PL_SCORE_V7_POLICY.speedSaturationRealtime}× real-time.`,
    equation: String.raw`\frac{\mathrm{FPS}_{\mathrm{enc}}}{\mathrm{FPS}_{\mathrm{src}}}`,
  },
} as const;

const componentKeys = Object.keys(components) as ComponentKey[];

export default function FormulaExplorer() {
  const [activeKey, setActiveKey] = useState<ComponentKey>("quality");
  const active = components[activeKey];

  return (
    <section className={styles.explorer} aria-label="PL7 formula explorer">
      <div className={styles.formula} aria-label="PL7 equals 100 times quality to the 0.50 power times bitrate to the 0.30 power times speed to the 0.20 power">
        <KatexMath expression={String.raw`\mathrm{PL7} = 100 \times`} />
        {componentKeys.map((key, index) => {
          const component = components[key];
          return (
            <span className={styles.formulaTerm} key={key}>
              {index > 0 && <KatexMath expression={String.raw`\times`} />}
              <button
                type="button"
                aria-label={component.title}
                aria-pressed={activeKey === key}
                onClick={() => setActiveKey(key)}
              >
                <KatexMath expression={`${component.symbol}^{${weights[key]}}`} />
              </button>
            </span>
          );
        })}
      </div>

      <div className={styles.weightBar} aria-label="PL7 weights: Quality 50%, Bitrate 30%, Speed 20%">
        {componentKeys.map((key) => {
          const component = components[key];
          return <span className={styles[key]} key={key}>{component.title} {component.percentage}</span>;
        })}
      </div>

      <div className={styles.explanation} aria-live="polite">
        <div className={styles.explanationCopy}>
          <div className={styles.explanationTitle}>
            <h2>{active.title}</h2>
            <span>{active.percentage}</span>
          </div>
          <p>{active.description}</p>
        </div>
        <KatexMath expression={active.equation} display />
      </div>
    </section>
  );
}
