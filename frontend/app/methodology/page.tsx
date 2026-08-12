import type { ReactNode } from "react";
import { DEFAULT_PL_SCORE_V7_POLICY, PL_SCORE_V7_WEIGHTS } from "../lib/plScore";
import styles from "./page.module.css";

const formula=`PL7 = 100 x Q^${PL_SCORE_V7_WEIGHTS.quality.toFixed(2)} x B^${PL_SCORE_V7_WEIGHTS.bitrate.toFixed(2)} x S^${PL_SCORE_V7_WEIGHTS.speed.toFixed(2)}`;
const effectiveVmaf=`V_PL = 0.85 x VMAF mean + 0.15 x VMAF P5`;
const speedCurve=`S = (1 - e^(-${DEFAULT_PL_SCORE_V7_POLICY.speedCurveRate} x realtime ratio)) / (1 - e^(-${DEFAULT_PL_SCORE_V7_POLICY.speedCurveRate} x ${DEFAULT_PL_SCORE_V7_POLICY.speedSaturationRealtime}))`;
const generalFormula="General PL7 = geometric mean of equal-class PL7 scores";

export default function MethodologyPage() {
  return <div className={`page ${styles.page}`}>
    <header className={styles.hero}>
      <div className={styles.heroMain}>
        <p className={styles.kicker}>PL Score v7</p>
        <h1>Methodology</h1>
        <p className={styles.lede}>PL Score v7 is a fixed public score for one benchmark workload: how good the picture looks, how much bitrate it used, and how fast it ran. The goal is not to replace human judgment. The goal is to make tradeoffs legible, reproducible, and comparable without hiding the math.</p>
      </div>
      <aside className={styles.statusCard} aria-label="Methodology status">
        <p className={styles.kicker}>Pre-epoch status</p>
        <div className={styles.big}>v7.0 pilot</div>
        <p className={styles.statusCopy}>The formula and measurement contract are versioned, but calibration is still provisional. The public v7 epoch is not open, and pilot results are not recommendation-eligible.</p>
        <div className={styles.statusGrid}>
          <div><strong>4x</strong><span>real-time speed saturation</span></div>
          <div><strong>P5</strong><span>guards against ugly low points</span></div>
          <div><strong>Null</strong><span>when required evidence is missing</span></div>
          <div><strong>Separate</strong><span>confidence and fit stay outside the score</span></div>
        </div>
      </aside>
    </header>

    <section className={styles.summary} aria-label="PL7 summary">
      <StatCard label="Public formula" value="Fixed" note="No dataset-relative reweighting in the public score." />
      <StatCard label="Bitrate reference" value="Pilot only" note="Production frontiers remain blocked on calibration evidence." />
      <StatCard label="General score" value="Multi-class" note="Only valid with complete equal-class suite coverage." />
    </section>

    <article className={styles.article}>
      <Section eyebrow="Overview" title="What PL Score v7 is actually scoring">
        <p>PL Score v7 is a content-specific benchmark score. It asks a narrow question: for this exact workload, did an encode preserve quality, stay reasonably compact, and finish at a useful speed?</p>
        <p>That narrowness is a feature. Public scores become unreliable when they quietly adapt to whichever rows happen to be in the dataset that week. v7 keeps the public score fixed and pushes anything user-specific into a different concept: PL Fit.</p>
      </Section>

      <Section eyebrow="Formula" title="The public formula is fixed and easy to audit">
        <div className={styles.panel}>
          <pre>{formula}</pre>
          <p>Quality carries the most weight, bitrate comes next, and speed matters without dominating the ranking.</p>
        </div>
        <div className={styles.definitions}>
          <Definition term="Q">Quality term derived from a blended VMAF signal and a fixed quality curve.</Definition>
          <Definition term="B">Bitrate term measured against a workload-specific reference bitrate that does not move when new submissions arrive.</Definition>
          <Definition term="S">Speed term based on encode speed relative to source playback speed, with diminishing returns.</Definition>
        </div>
      </Section>

      <Section eyebrow="Quality" title="Quality uses the average picture and the bad moments">
        <div className={styles.twoCol}>
          <div>
            <div className={styles.panel}>
              <pre>{effectiveVmaf}</pre>
            </div>
            <p>VMAF mean tells you how the encode looked overall. VMAF P5 adds a small but important penalty for weak moments by looking near the lower tail instead of only the average.</p>
          </div>
          <div>
            <p>After that blend, v7 normalizes the result to a fixed range and raises it to a quality exponent of {DEFAULT_PL_SCORE_V7_POLICY.qualityExponent}. That curve is deliberately unforgiving in the low-quality region and more discriminating near the top, where small losses matter more to viewers.</p>
            <p>This is one of the main reasons v7 is better than earlier attempts: it rewards genuinely clean encodes without pretending that all VMAF points are equally important.</p>
          </div>
        </div>
      </Section>

      <Section eyebrow="Bitrate" title="Bitrate is judged against a frozen workload reference">
        <p>The bitrate term is not relative to the current leaderboard. It is measured against a workload reference bitrate recorded with the scoring context. If the same workload is rescored later, the reference stays the same, so old and new submissions still mean the same thing.</p>
        <div className={styles.panel}>
          <pre>B = 1 / (1 + encoded bitrate / workload reference bitrate)</pre>
        </div>
        <p>That makes compression efficiency interpretable. A row is not rewarded just because weaker rows entered the database later.</p>
      </Section>

      <Section eyebrow="Speed" title="Speed matters up to usefulness, then it saturates">
        <div className={styles.twoCol}>
          <div>
            <p>v7 scores speed in real-time terms: encode FPS divided by source FPS. A 2x real-time encode is twice playback speed. A 0.5x real-time encode is half playback speed.</p>
            <p>Past a point, more speed is nice but less important than quality or bitrate. v7 therefore uses a saturation curve instead of rewarding unlimited FPS linearly.</p>
          </div>
          <div className={styles.panel}>
            <pre>{speedCurve}</pre>
            <p>The default policy saturates at {DEFAULT_PL_SCORE_V7_POLICY.speedSaturationRealtime}x real-time. Faster than that can still help a little, but it does not overwhelm the score.</p>
          </div>
        </div>
      </Section>

      <Section eyebrow="Semantics" title="Score, fit, and confidence are different things">
        <div className={styles.comparison}>
          <article>
            <h3>PL Score v7</h3>
            <p>A fixed public score for one workload. Everyone should get the same answer from the same evidence.</p>
          </article>
          <article>
            <h3>PL Fit</h3>
            <p>A personalized ranking layer for a specific user or use case. Fit can prefer speed, filesize, hardware limits, or latency tolerance without corrupting the public benchmark score.</p>
          </article>
          <article>
            <h3>Confidence</h3>
            <p>A separate trust signal about evidence quality and completeness. Confidence should explain how much to trust a score, not secretly change the score itself.</p>
          </article>
        </div>
        <p>Keeping those ideas separate removes a common source of confusion: a public benchmark should not quietly turn into a recommendation engine.</p>
      </Section>

      <Section eyebrow="Scope" title="Content-specific PL7 and General PL7 solve different problems">
        <p>A single workload score is useful, but it only tells you how a configuration behaved on that workload. General claims need broader evidence.</p>
        <div className={styles.panel}>
          <pre>{generalFormula}</pre>
        </div>
        <p>General PL7 uses an equal-class geometric mean across a required set of content classes. The geometric mean is intentional: one excellent score cannot fully hide one weak class, and missing class coverage should yield no General PL7 at all.</p>
        <p>That makes the general score stricter and more honest than a loose average. If a configuration has only sports or only animation results, it can still have a content-specific PL7, but it should not claim broad superiority.</p>
      </Section>

      <Section eyebrow="Provenance" title="Every score should carry its own provenance and version labels">
        <ul className={styles.list}>
          <li><strong>Score formula version</strong> identifies the public math, such as {DEFAULT_PL_SCORE_V7_POLICY.scoreFormulaVersion}.</li>
          <li><strong>Benchmark protocol version</strong> identifies how the run was captured and validated.</li>
          <li><strong>Source suite version</strong> identifies the content set used for the benchmark.</li>
          <li><strong>Workload ID and reference bitrate</strong> identify which content-specific score is being discussed.</li>
          <li><strong>VMAF model ID</strong> identifies the quality model behind the quality term.</li>
        </ul>
        <p>Without those fields, a score can look precise while being historically ambiguous. v7 treats provenance as part of the result, not extra paperwork.</p>
      </Section>

      <Section eyebrow="Limitations" title="What the score does not promise">
        <ul className={styles.list}>
          <li>It is not a universal truth about an encoder. It is a score for a specific workload under a specific benchmark protocol.</li>
          <li>It does not rescue missing data. If mean VMAF, VMAF P5, bitrate, encode FPS, or source FPS are absent, a canonical v7 score should be unavailable.</li>
          <li>It does not replace viewing tests, rate-distortion analysis, or workload-specific engineering judgment.</li>
          <li>It does not make personalized decisions on behalf of the user. That belongs to PL Fit.</li>
        </ul>
      </Section>
    </article>

    <aside className={styles.note}>
      <strong>Rollout note</strong>
      <span>This page documents the v7 methodology and its guardrails before the public epoch opens. Current evidence uses a provisional, recommendation-ineligible policy. Production scores require a retained calibration corpus, expert review, holdouts, and a frozen production reference context; older or incomplete evidence remains visible without being mislabeled as final PL Score v7.</span>
    </aside>
  </div>;
}

function Section({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return <section className={styles.section}>
    <div className={styles.sectionHead}>
      <p>{eyebrow}</p>
      <h2>{title}</h2>
    </div>
    <div className={styles.sectionBody}>{children}</div>
  </section>;
}

function StatCard({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className={styles.stat}>
    <span>{label}</span>
    <strong>{value}</strong>
    <small>{note}</small>
  </div>;
}

function Definition({ term, children }: { term: string; children: ReactNode }) {
  return <article className={styles.definition}>
    <h3>{term}</h3>
    <p>{children}</p>
  </article>;
}
