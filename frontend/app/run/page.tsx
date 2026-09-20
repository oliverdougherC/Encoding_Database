import styles from "./page.module.css";
import { downloadModel, historicalTag, projectTag, repoReleases } from "./releaseAssets";

export const dynamic = "force-dynamic";

export default function RunPage() {
  const downloads = downloadModel(process.env);
  const historical = `${repoReleases}/download/${historicalTag}`;
  return <div className={`page ${styles.page}`}>
    <header><p className={styles.kicker}>Contribute results</p><h1>Run a benchmark</h1><p>Measure a canonical clip on your machine, review the result, then choose whether to publish.</p></header>
    {downloads.published
      ? <p className={styles.callout}><strong>Collection update published.</strong> The downloads below are the corrected client/0.3.0 builds (project {projectTag}) for the current server (protocol 7.1). Verify each file against its SHA-256 checksum before running.</p>
      : <p className={styles.callout}><strong>Collection update in preparation.</strong> The corrected measurement flow requires client/0.3.0 and a compatible server. The current server already requires client/0.3.0 (protocol 7.1); the 1.2.0 downloads below (client/0.2.0) can no longer submit. The tested {projectTag} builds are staged and listed with their verified checksums, but are not downloadable here until they are published as release assets. Use the source client below meanwhile.</p>}
    <div className={styles.grid}><main className={styles.panel}><ol>
      <li><span>1</span><div><h2>Get the client</h2>
        <p>{downloads.published
          ? <>Collection-capable builds (client/0.3.0, project {projectTag}):</>
          : <>Collection-capable builds (client/0.3.0, project {projectTag}) - staged for publication, checksums verified:</>}</p>
        <div className={styles.downloads}>
          {downloads.items.map((a) => a.href
            ? <a key={a.file} className="btn" href={a.href}>{a.label}</a>
            : <span key={a.file} className="btn" aria-disabled="true" title="Not published yet">{a.label} (pending publication)</span>)}
        </div>
        <ul>{downloads.items.map((a) => <li key={a.file}><code>{a.file}</code> · SHA-256 <code>{a.sha256}</code> · {a.support}</li>)}</ul>
        <p>All four builds are unsigned; the macOS build is not notarized. The macOS executable is a native Apple Silicon build with embedded arm64 FFmpeg helpers - no Rosetta. Windows GUI and console were measured on one physical Windows 11 / RTX 5090 host; Intel macOS and other GPU combinations (QSV, AMF, VideoToolbox) are not supported by the campaign and remain unproven.</p>
        <a href={`${repoReleases}/tag/${projectTag}`}>Release notes, checksums and build evidence ({projectTag})</a>
        <p>Historical {historicalTag} downloads (client/0.2.0, protocol 7.0) remain available for reference but cannot submit to the current server:</p>
        <div className={styles.downloads}>
          <a className="btn" href={`${historical}/encodingdb-client-windows.exe`}>Windows GUI (0.2.0)</a>
          <a className="btn" href={`${historical}/encodingdb-client-windows-console.exe`}>Windows console (0.2.0)</a>
          <a className="btn" href={`${historical}/encodingdb-client-linux`}>Linux (0.2.0)</a>
          <a className="btn" href={`${historical}/encodingdb-client-macos`}>macOS (0.2.0)</a>
        </div>
        <a href={`${repoReleases}/tag/${historicalTag}`}>{historicalTag} requirements, checksums and release evidence</a></div></li>
      <li><span>2</span><div><h2>Try the corrected source client</h2><p>From the client/0.3.0 source checkout and its installed Python environment, run one clip locally. The client downloads and verifies the suite, warms up the encoder, then measures repeated attempts.</p><pre>{`python -m client --codec libx264 --presets fast --no-submit`}</pre><p>For a seven-clip campaign using the same recipe:</p><pre>{`python -m client --codec libx264 --presets fast --campaign full --no-submit`}</pre><p>Keep the campaign ID printed by the client. A full campaign takes longer; the client reports its attempt and storage budget before encoding.</p></div></li>
      <li><span>3</span><div><h2>Publish the saved result</h2><p>Use the campaign ID to upload the completed measurements without encoding them again:</p><pre>{`python -m client --resume-campaign CAMPAIGN_ID --submit`}</pre><p>To measure and publish a new quick contribution in one command:</p><pre>{`python -m client --codec libx264 --presets fast --submit`}</pre><p>An upload receipt means analysis is pending. The result may then be accepted, suspect and awaiting review, or rejected. Public PL remains unavailable until calibration is approved.</p></div></li>
      <li><span>4</span><div><h2>Continue after an interruption</h2><p>Resume unfinished measurements or retry queued uploads. Offline results remain pending.</p><pre>{`python -m client --resume-campaign CAMPAIGN_ID --no-submit\npython -m client --upload-only\npython -m client --queue-status`}</pre></div></li>
    </ol></main><aside className={styles.aside}><p className={styles.kicker}>Before running</p><ul><li>Use a compatible server and the exact requested encoder. Unsupported encoders fail explicitly.</li><li>Leave room for the 1.5 GB suite download, extracted references and retained encodes.</li><li>Close other demanding work during measurement.</li><li>Publication includes encoded canonical clips, hardware and software context, and an installation pseudonym.</li></ul><p className={styles.callout}>Only publish canonical benchmark media. Keep credentials and personal footage out of runs and notes.</p></aside></div>
  </div>;
}
