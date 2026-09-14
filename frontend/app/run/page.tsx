import styles from "./page.module.css";

const release = "https://github.com/oliverdougherC/Encoding_Database/releases/download/1.2.0";

export default function RunPage() {
  return <div className={`page ${styles.page}`}>
    <header><p className={styles.kicker}>Contribute results</p><h1>Run a benchmark</h1><p>Measure a canonical clip on your machine, review the result, then choose whether to publish.</p></header>
    <p className={styles.callout}><strong>Collection update in preparation.</strong> The corrected measurement flow requires client/0.3.0 and a compatible server. The downloads below are still release 1.2.0 (client/0.2.0); they do not support the new campaign commands. Final platform and hardware certification is pending.</p>
    <div className={styles.grid}><main className={styles.panel}><ol>
      <li><span>1</span><div><h2>Get the client</h2><p>Published 1.2.0 downloads:</p><div className={styles.downloads}>
        <a className="btn" href={`${release}/encodingdb-client-windows.exe`}>Windows GUI</a>
        <a className="btn" href={`${release}/encodingdb-client-windows-console.exe`}>Windows console</a>
        <a className="btn" href={`${release}/encodingdb-client-linux`}>Linux</a>
        <a className="btn" href={`${release}/encodingdb-client-macos`}>macOS</a>
      </div><p>These builds are unsigned. macOS is not notarized; Apple Silicon requires Rosetta for the Intel FFmpeg helper. Windows GUI and additional GPU combinations are not certified.</p><a href="https://github.com/oliverdougherC/Encoding_Database/releases/tag/1.2.0">Requirements, checksums and release evidence</a></div></li>
      <li><span>2</span><div><h2>Try the corrected source client</h2><p>From the client/0.3.0 source checkout and its installed Python environment, run one clip locally. The client downloads and verifies the suite, warms up the encoder, then measures repeated attempts.</p><pre>{`python -m client --codec libx264 --presets fast --no-submit`}</pre><p>For a seven-clip campaign using the same recipe:</p><pre>{`python -m client --codec libx264 --presets fast --campaign full --no-submit`}</pre><p>Keep the campaign ID printed by the client. A full campaign takes longer; the client reports its attempt and storage budget before encoding.</p></div></li>
      <li><span>3</span><div><h2>Publish the saved result</h2><p>Use the campaign ID to upload the completed measurements without encoding them again:</p><pre>{`python -m client --resume-campaign CAMPAIGN_ID --submit`}</pre><p>To measure and publish a new quick contribution in one command:</p><pre>{`python -m client --codec libx264 --presets fast --submit`}</pre><p>An upload receipt means analysis is pending. The result may then be accepted, suspect and awaiting review, or rejected. Public PL remains unavailable until calibration is approved.</p></div></li>
      <li><span>4</span><div><h2>Continue after an interruption</h2><p>Resume unfinished measurements or retry queued uploads. Offline results remain pending.</p><pre>{`python -m client --resume-campaign CAMPAIGN_ID --no-submit\npython -m client --upload-only\npython -m client --queue-status`}</pre></div></li>
    </ol></main><aside className={styles.aside}><p className={styles.kicker}>Before running</p><ul><li>Use a compatible server and the exact requested encoder. Unsupported encoders fail explicitly.</li><li>Leave room for the 1.5 GB suite download, extracted references and retained encodes.</li><li>Close other demanding work during measurement.</li><li>Publication includes encoded canonical clips, hardware and software context, and an installation pseudonym.</li></ul><p className={styles.callout}>Only publish canonical benchmark media. Keep credentials and personal footage out of runs and notes.</p></aside></div>
  </div>;
}
