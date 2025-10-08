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
{`// Normalization within current results
vmafNorm = normalizeUp(vmaf, vmafMin, vmafMax)
sizeNorm = normalizeDown(fileSizeBytes, sizeMin, sizeMax)
fpsNorm  = normalizeUp(fps, fpsMin, fpsMax)

// Weights from the UI controls (sum to 1.0)
plove = wQuality * vmafNorm
      + wSize    * sizeNorm
      + wSpeed   * fpsNorm`}
        </div>
        <p className="subtle" style={{ fontSize: 12, marginTop: 8 }}>
          When a range collapses (e.g., all rows have identical values), that component defaults to 100 to avoid skewing results.
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


