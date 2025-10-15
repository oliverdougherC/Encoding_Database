export const dynamic = "force-dynamic";

export default function PlovePage() {
  return (
    <div style={{ padding: 24, maxWidth: 900, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600 }}>PLOVE Score</h1>
      <p className="subtle" style={{ fontSize: 14 }}>
        PLOVE (Platinum Labs Objective Video Evaluation) is a single, tunable score that balances visual quality, output size, and encode speed to make row-to-row comparisons easy.
      </p>

      <section className="card" style={{ padding: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>How it’s calculated</h2>
        <p style={{ marginBottom: 12 }}>
          Each component is normalized to a 0–100 range within the currently filtered dataset, then combined with user-adjustable weights that sum to 1.00.
        </p>
        <ul style={{ paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
          <li><b>Quality</b>: uses VMAF (0–100), normalized upward. Higher VMAF → higher score.</li>
          <li><b>Size</b>: uses output file size, normalized downward. Smaller size → higher score.</li>
          <li><b>Speed</b>: uses FPS, normalized upward. Faster encodes → higher score.</li>
        </ul>
        <div className="kbd" style={{ paddingRight: 12 }}>
{`// PLOVE 4.0 component scores
// Quality (VMAF) with diminishing returns above 90 and harsh penalty below 90
function qualityScore(vmaf) {
  if (vmaf == null) return 100
  if (vmaf >= 90) return 50 + 50 * Math.sqrt((vmaf - 90) / 10)
  return 50 * Math.pow(vmaf / 90, 4)
}

// Relative size (fileSize / medianFileSize) — lower is better
function sizeScore(relSize, rsMin, rsMax) {
  if (!(rsMax > rsMin)) return 100
  return 100 * (rsMax - relSize) / (rsMax - rsMin)
}

// Speed uses logarithmic normalization
function speedScore(fps, fpsMin, fpsMax) {
  if (!(fpsMin > 0 && fpsMax > 0)) return 0
  if (fpsMax === fpsMin) return 100
  const lf = Math.log(Math.max(fps, fpsMin))
  return 100 * (lf - Math.log(fpsMin)) / (Math.log(fpsMax) - Math.log(fpsMin))
}

// Hard cutoff for inefficient encodes
if (relSize >= 1.0) plove = 0
else plove = clamp(wQ*qualityScore(vmaf) + wS*sizeScore(relSize, rsMin, rsMax) + wV*speedScore(fps, fpsMin, fpsMax), 0, 100)`}
        </div>
        <p className="subtle" style={{ fontSize: 12, marginTop: 8 }}>
          When a range collapses (e.g., all rows have identical values), that component defaults to 100 to avoid skewing results. PLOVE also applies strong penalties to oversized outputs (relative size &gt; 1.0) and to VMAF below 90.
        </p>
      </section>

      <section className="card" style={{ padding: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Why we use it</h2>
        <ul style={{ paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          <li><b>Balanced view</b>: captures the core trade‑offs between quality, size, and speed.</li>
          <li><b>Dataset‑relative</b>: normalization adapts to the current filter set for meaningful comparisons.</li>
          <li><b>Configurable</b>: adjust weights to reflect your priorities for a given task.</li>
        </ul>
      </section>

      <section className="card" style={{ padding: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Notes & limitations</h2>
        <ul style={{ paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          <li>VMAF is an automated metric; subjective quality may differ.</li>
          <li>Normalization is relative to visible rows; changing filters can change scores.</li>
          <li>PLOVE is a convenience score, not an industry standard benchmark.</li>
        </ul>
      </section>
    </div>
  );
}


