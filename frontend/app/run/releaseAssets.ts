// rc.5 repairs macOS preparation, retained-campaign storage, checkpoint uploads,
// resume allowances, and failure reporting. Windows carries forward the verified
// rc.4 binaries; Linux retains its original accepted build. Publication still
// requires COLLECTION_DOWNLOAD_BASE to name this exact release tag.

export const projectTag = "1.3.0-rc.5";
export const supersededTag = "1.3.0-rc.4";
export const cliTag = "1.3.0-rc.1";
export const historicalTag = "1.2.0";
export const repoReleases = "https://github.com/oliverdougherC/Encoding_Database/releases";

// Single source of truth for the runtime variable name; docker-compose.prod.yml
// and deployment docs must use exactly this key (asserted by releaseConfig.test.ts).
export const downloadBaseEnvVar = "COLLECTION_DOWNLOAD_BASE";

export interface ReleaseAsset {
  file: string;
  label: string;
  // null until the packaged build exists and root stamps the verified digest.
  // Never invent one: the page renders "pending publication" honestly instead.
  sha256: string | null;
  support: string;
}

// Recommended primary downloads. Signing/support claims describe the current
// build chain; if the packaging lane changes them, root updates these lines at
// integration alongside the stamped digests.
export const primaryAssets: ReleaseAsset[] = [
  {
    file: "EncodingDB-macOS-arm64.dmg",
    label: "macOS (Apple Silicon)",
    sha256: "bfa37a2422b1c3ce187161c067ecf1d6984a471a818503ae6181caf4c01618b5",
    support: "Double-clickable app inside a disk image; opens the guided menu in Terminal. Ad-hoc signed (not Developer ID, not notarized), so the first launch may need “Open Anyway” in System Settings → Privacy & Security (see first-launch help below). Native arm64; the embedded runtime requires macOS 27 or later; Intel Macs remain unverified.",
  },
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows (GUI)",
    sha256: "2ec0a4bcb7d94af340e61a1837bfc9380b51b2dd60bbd1f48eb023dfa24c0379",
    support: "No Authenticode signature, so SmartScreen may warn at first launch. The window exposes the same Small/Medium/Large/Full sweeps as the guided interface and recovers automatically from a cache folder protected against the current user.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux (x86-64)",
    sha256: "b1a68a039ce78a6bc9718adbae99409865326ea8a8b3fc29e47aaa090ef0f4d8",
    support: "Unsigned archive; unpack it and run the launcher inside. Same guided flow; includes the command-line entry point for scripts.",
  },
];

// Preserve the actual published rc.4 asset identities for rollback and verification.
export const supersededAssets: ReleaseAsset[] = [
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows GUI (rc.4)",
    sha256: "2ec0a4bcb7d94af340e61a1837bfc9380b51b2dd60bbd1f48eb023dfa24c0379",
    support: "Verified rc.4 Windows repair, unchanged in the current release; no Authenticode signature.",
  },
  {
    file: "encodingdb-client-windows-console.exe",
    label: "Windows console (rc.4)",
    sha256: "05189da160c876f812cd16ae228b76df50bac8925d5763bb3d49ea9f0e42a60e",
    support: "Verified rc.4 Windows console, unchanged in the current release; no Authenticode signature.",
  },
  {
    file: "EncodingDB-macOS-arm64.dmg",
    label: "macOS DMG (rc.4)",
    sha256: "2ec29a38cf36920d8eb030de97113cd37c56373a277ddbd79e46d1b0336c36ef",
    support: "Earlier macOS build, superseded by the preparation, storage, and resume repairs in rc.5.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux archive (rc.4)",
    sha256: "b1a68a039ce78a6bc9718adbae99409865326ea8a8b3fc29e47aaa090ef0f4d8",
    support: "Byte-identical to the current Linux download; same file republished under the rc.5 tag.",
  },
];

export interface DownloadModel {
  published: boolean;
  base: string;
  items: Array<ReleaseAsset & { href: string | null }>;
}

// A missing/mismatched base means "assets staged, not yet published": hrefs
// stay null so the page can stage the plan without claiming an unpublished
// URL is live - and without ever resolving current asset names under another tag.
export function downloadModel(env: Record<string, string | undefined>): DownloadModel {
  const base = (env[downloadBaseEnvVar] ?? "").trim().replace(/\/+$/, "");
  const published = base.endsWith(`/download/${projectTag}`);
  return {
    published,
    base,
    items: primaryAssets.map((a) => ({ ...a, href: published ? `${base}/${a.file}` : null })),
  };
}
