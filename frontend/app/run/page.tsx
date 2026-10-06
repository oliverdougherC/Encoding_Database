import { pageMetadata } from "../lib/seo";
import styles from "./page.module.css";
import { cliTag, currentWindowsConsole, downloadModel, historicalTag, projectTag, repoReleases, supersededAssets, supersededTag } from "./releaseAssets";

export const metadata = pageMetadata("/run", "Download the Video Encoding Benchmark Client | EncodingDB", "Run reproducible FFmpeg video encoding benchmarks on Windows, macOS, or Linux and contribute hardware, speed, bitrate, and quality measurements to EncodingDB.");

export const dynamic = "force-dynamic";

const platformSummary: Record<string, string> = {
  "EncodingDB-macOS-arm64.dmg": "Apple Silicon · requires macOS 27 or later. Guided Terminal app; not notarized.",
  "encodingdb-client-windows.exe": "Windows 11 x86-64 · desktop app. Unsigned; SmartScreen may warn.",
  "encodingdb-client-linux.tar.gz": "Ubuntu 24.04 x86-64 · guided Terminal client. Other distributions unverified.",
};
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
  const currentBase = `${repoReleases}/download/${projectTag}`;
  return <div className={`page ${styles.page}`}>
    <header className={styles.header}>
      <p className={styles.kicker}>Contribute results</p>
      <h1>Contribute your results.</h1>
      <p>Choose your platform. The client detects available encoders, guides your benchmark, and retries interrupted uploads.</p>
    </header>

    {downloads.published
      ? <p className={styles.callout}><strong>Version {projectTag} is published.</strong> Packaged clients for protocol 7.1. Check system requirements below.</p>
      : <p className={styles.callout}><strong>Downloads are temporarily unavailable on this site.</strong> Version {projectTag} is selected, but its download configuration has not been enabled.</p>}

    <section className={styles.platforms} aria-label="Primary downloads">
      {downloads.items.map((asset) => <article key={asset.file} className={styles.card}>
        <h2>{asset.label}</h2>
        <p className={styles.summary}>{platformSummary[asset.file]}</p>
        {asset.href
          ? <a className="btn btn-primary" href={asset.href}>Download for {asset.label}</a>
          : <span className="btn" aria-disabled="true" title="Downloads not enabled">Download unavailable</span>}

        <ol className={styles.steps}>{(platformNotes[asset.file] ?? []).map((line) => <li key={line}>{line}</li>)}</ol>
        <details className={styles.platformDetails}><summary>Compatibility &amp; checksum</summary><div><p className={styles.support}>{asset.support}</p><p className={styles.fileName}><code>{asset.file}</code></p><p className={styles.sha}>{asset.sha256 ? <>SHA-256 <code>{asset.sha256}</code></> : "SHA-256 published with the release."}</p></div></details>
      </article>)}
    </section>

    <section className={styles.howto} aria-label="How a run works">
      <div><strong>1 · Choose a sweep</strong><span>Small, Medium, Large, or Full. Review the time and disk estimate before starting.</span></div>
      <div><strong>2 · Press start</strong><span>Only usable encoders are measured. Review results locally before sharing.</span></div>
      <div><strong>3 · Approve uploads once</strong><span>Finished measurements submit automatically after your consent. A receipt confirms upload; server analysis follows.</span></div>
      <div><strong>4 · Continue after an interruption</strong><span>Resume a saved run. Completed encodes are kept and queued uploads retry.</span></div>
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
        <p>Earlier published builds are retained for rollback and verification; use current packages for contribution.</p>
        <ul className={styles.assetList}>
          {supersededAssets.map((asset) => <li key={asset.file}>
            <a href={`${superseded}/${asset.file}`}>{asset.label}</a>{" "}
            <code>{asset.file}</code> · SHA-256 <code>{asset.sha256}</code>
          </li>)}
        </ul>

        <h3>Current command-line access ({projectTag})</h3>
        <p>For Windows scripts, use the console executable from the current release. The current macOS and Linux command-line entry points are inside their packages above.</p>
        <p>{downloads.published
          ? <a href={`${currentBase}/${currentWindowsConsole.file}`}>Windows console ({projectTag})</a>
          : <span>Windows console ({projectTag}) available when current downloads are enabled</span>} · <code>{currentWindowsConsole.file}</code> · SHA-256 <code>{currentWindowsConsole.sha256}</code></p>

        <h3>Historical plain executables ({cliTag})</h3>
        <p>These protocol-compatible files predate the packaged apps and current shared-core repairs. The macOS file is a bare extensionless executable. Use the current packages above for contribution.</p>
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
