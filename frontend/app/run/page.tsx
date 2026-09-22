import styles from "./page.module.css";
import { cliTag, downloadModel, historicalTag, projectTag, repoReleases, supersededAssets, supersededTag } from "./releaseAssets";

export const dynamic = "force-dynamic";

const platformNotes: Record<string, string[]> = {
  "EncodingDB-macOS-arm64.dmg": ["Open the disk image and drag EncodingDB to Applications.", "Open EncodingDB from Applications; it launches the guided menu in Terminal.", "First launch blocked by macOS? Use the first-launch help under build details below."],
  "encodingdb-client-windows.exe": ["Run the downloaded file.", "Windows warns because the build is unsigned; verify the SHA-256 below before continuing.", "Choose a sweep size in the window and press Start."],
  "encodingdb-client-linux.tar.gz": ["Unpack the archive anywhere you can write.", "Open a terminal in the extracted folder and run ./start.sh.", "The guided Terminal menu asks for a sweep size, then runs."],
};

export default function RunPage() {
  const downloads = downloadModel(process.env);
  const historical = `${repoReleases}/download/${historicalTag}`;
  const superseded = `${repoReleases}/download/${supersededTag}`;
  const cliBase = `${repoReleases}/download/${cliTag}`;
  return <div className={`page ${styles.page}`}>
    <header className={styles.header}>
      <p className={styles.kicker}>Contribute results</p>
      <h1>Contribute your results.</h1>
      <p>Download the client and follow the launch steps for your system. Choose Small, Medium, Large, or Full; the client detects usable encoders and submits finished measurements automatically once you approve uploads.</p>
    </header>

    {downloads.published
      ? <p className={styles.callout}><strong>Version {projectTag} is published.</strong> The downloads below are the packaged builds for the current server (protocol 7.1). Verify each file against the SHA-256 listed on the release page before running.</p>
      : <p className={styles.callout}><strong>Version {projectTag} is being prepared.</strong> The packaged builds below are staged and their file names are final, but the download buttons activate only once they are published under tag {projectTag}. Checksums are published with the release, never before it.</p>}

    <section className={styles.platforms} aria-label="Primary downloads">
      {downloads.items.map((asset) => <article key={asset.file} className={styles.card}>
        <h2>{asset.label}</h2>
        {asset.href
          ? <a className="btn btn-primary" href={asset.href}>Download for {asset.label}</a>
          : <span className="btn" aria-disabled="true" title="Not published yet">Download for {asset.label} (pending publication)</span>}
        <p className={styles.fileName}><code>{asset.file}</code></p>
        <ol className={styles.steps}>{(platformNotes[asset.file] ?? []).map((line) => <li key={line}>{line}</li>)}</ol>
        <p className={styles.support}>{asset.support}</p>
        <p className={styles.sha}>{asset.sha256 ? <>SHA-256 <code>{asset.sha256}</code></> : "SHA-256 published with the release."}</p>
      </article>)}
    </section>

    <section className={styles.howto} aria-label="How a run works">
      <div><strong>1 · Choose a sweep</strong><span>Small, Medium, Large, or Full — increasing coverage of canonical clips and presets. The client prints the plan (time and disk budget) before it encodes anything.</span></div>
      <div><strong>2 · Press start</strong><span>Encoders are detected on your machine; only usable ones are measured. You can review the numbers locally before anything leaves your machine.</span></div>
      <div><strong>3 · Approve uploads once</strong><span>One consent, then finished measurements submit automatically. An upload receipt means analysis is pending; results may be accepted, suspect and awaiting review, or rejected.</span></div>
      <div><strong>4 · Continue after an interruption</strong><span>Sweeps checkpoint as they go and queued uploads retry, so resuming the run finishes the work without re-encoding.</span></div>
    </section>

    <aside className={styles.beforeRun}>
      <p className={styles.kicker}>Before running</p>
      <ul>
        <li>Leave room for the 1.5&nbsp;GB suite download, extracted references, and retained encodes.</li>
        <li>Close other demanding work during measurement; the numbers are only as clean as the machine.</li>
        <li>Publishing shares encoded canonical clips, hardware and software context, and an installation pseudonym — never your notes or personal footage.</li>
      </ul>
    </aside>

    <details className={styles.disclosure}>
      <summary>Build details, checksums, signing, and older releases</summary>
      <div className={styles.disclosureBody}>
        <h3>{projectTag} signing and support</h3>
        <p>Per the current build chain: the macOS app is ad-hoc signed (not Developer ID, not notarized) on native arm64 and requires macOS 27 or later; the Windows executable carries no Authenticode signature; the Linux build is unsigned. Encoders were exercised per platform where shown — VideoToolbox on the Apple Silicon Mac, NVIDIA NVENC plus software encoders on the Windows and Linux hosts; Intel macOS, Intel QSV, and AMD AMF remain unproven. {downloads.published
          ? <a href={`${repoReleases}/tag/${projectTag}`}>Release notes, checksums, and build evidence ({projectTag})</a>
          : <>Release notes and evidence will appear under tag <code>{projectTag}</code> once the release is published; this page does not link an unpublished tag.</>}</p>

        <h3>First-launch help</h3>
        <p>macOS: the app is ad-hoc signed and not notarized, so the first open may be blocked. If you trust this source, open System Settings → Privacy &amp; Security and choose “Open Anyway” — see <a href="https://support.apple.com/en-us/102445" target="_blank" rel="noreferrer">Apple’s instructions for opening a blocked app</a>. Nothing here asks you to disable Gatekeeper or clear the quarantine flag.</p>
        <p>Windows: SmartScreen warns because the executable is unsigned. Verify the SHA-256 above first, and continue only if you trust the source; the page gives no bypass tool or automation.</p>

        <h3>Superseded packaged builds ({supersededTag})</h3>
        <p>The {supersededTag} macOS build predates the preparation, retained-campaign storage, and resume repairs in {projectTag}. The verified Windows and Linux binaries are unchanged in this release.</p>
        <ul className={styles.assetList}>
          {supersededAssets.map((asset) => <li key={asset.file}>
            <a href={`${superseded}/${asset.file}`}>{asset.label}</a>{" "}
            <code>{asset.file}</code> · SHA-256 <code>{asset.sha256}</code>
          </li>)}
        </ul>

        <h3>Plain command-line builds ({cliTag})</h3>
        <p>Protocol-compatible executables that predate the packaged apps; the macOS file is a bare extensionless executable.</p>
        <ul className={styles.assetList}>
          <li><a href={`${cliBase}/encodingdb-client-windows.exe`}>Windows GUI (rc.1)</a> · <code>encodingdb-client-windows.exe</code></li>
          <li><a href={`${cliBase}/encodingdb-client-windows-console.exe`}>Windows console (rc.1)</a> · <code>encodingdb-client-windows-console.exe</code></li>
          <li><a href={`${cliBase}/encodingdb-client-linux`}>Linux (rc.1)</a> · <code>encodingdb-client-linux</code></li>
          <li><a href={`${cliBase}/encodingdb-client-macos`}>macOS (rc.1)</a> · <code>encodingdb-client-macos</code></li>
          <li><a href={`${repoReleases}/tag/${cliTag}`}>{cliTag} requirements, checksums, and release evidence</a></li>
        </ul>

        <h3>Historical 1.2.0 (cannot submit)</h3>
        <p>The 1.2.0 downloads (client/0.2.0, protocol 7.0) remain reachable for reference, but they cannot submit to the server version shipped with this page. Treat them as archived, not as recommended downloads.</p>
        <ul className={styles.assetList}>
          <li><a href={`${historical}/encodingdb-client-windows.exe`}>Windows GUI (0.2.0)</a> · <code>encodingdb-client-windows.exe</code></li>
          <li><a href={`${historical}/encodingdb-client-windows-console.exe`}>Windows console (0.2.0)</a> · <code>encodingdb-client-windows-console.exe</code></li>
          <li><a href={`${historical}/encodingdb-client-linux`}>Linux (0.2.0)</a> · <code>encodingdb-client-linux</code></li>
          <li><a href={`${historical}/encodingdb-client-macos`}>macOS (0.2.0)</a> · <code>encodingdb-client-macos</code></li>
          <li><a href={`${repoReleases}/tag/${historicalTag}`}>1.2.0 requirements, checksums, and release evidence</a></li>
        </ul>

        <h3>Advanced: source checkout and scripted CLI (optional)</h3>
        <p>Not the normal contribution path — the packaged apps do everything below. For automation or source builds, from a client checkout with its installed Python environment:</p>
        <pre>{`python -m client --codec libx264 --presets fast --no-submit`}</pre>
        <p>A seven-clip campaign with the same recipe:</p>
        <pre>{`python -m client --codec libx264 --presets fast --campaign full --no-submit`}</pre>
        <p>Publish a saved campaign without re-encoding, or measure and publish in one step:</p>
        <pre>{`python -m client --resume-campaign CAMPAIGN_ID --submit\npython -m client --codec libx264 --presets fast --submit`}</pre>
        <p>Resume unfinished measurements or retry queued uploads:</p>
        <pre>{`python -m client --resume-campaign CAMPAIGN_ID --no-submit\npython -m client --upload-only\npython -m client --queue-status`}</pre>
      </div>
    </details>
  </div>;
}
