// Release-aware download model for the collection client (target 1.3.0-rc.4).
//
// rc.4 is a Windows-focused repair of rc.3: a suite-cache extraction folder the
// normal user cannot read or replace (for example left by an
// administrator-privileged run) is now recovered automatically - the client
// installs a fully verified copy at a deterministic writable location beside
// the blocked folder, announces it in the preparation log and reuses it on
// later runs; nothing protected is deleted or taken over. The macOS and Linux
// binaries are byte-identical to the accepted rc.2 builds, republished under
// the new tag with their original source identity; the Windows GUI and console
// are rebuilt from the repair commit.
//
// COLLECTION_DOWNLOAD_BASE must be the full download base for the CURRENT tag,
// e.g. `https://github.com/<owner>/<repo>/releases/download/1.3.0-rc.4`.
// The model fails closed on any other value: publication is keyed to the
// exact tag segment, so asset names can never resolve under another tag.
//
// 1.3.0-rc.3 stays published but superseded (its Windows build fails on a
// protected cache folder until that folder is deleted with administrator
// rights). 1.3.0-rc.1 stays published as plain command-line builds (`cliTag`),
// never as the recommended download. 1.2.0 (client/0.2.0, protocol 7.0) is
// historical and cannot submit to the protocol 7.1 server.

export const projectTag = "1.3.0-rc.4";
export const supersededTag = "1.3.0-rc.3";
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
    sha256: "2ec29a38cf36920d8eb030de97113cd37c56373a277ddbd79e46d1b0336c36ef",
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

// Published but superseded packaged builds (1.3.0-rc.3, client/0.3.2, protocol 7.1).
// Digests are the published rc.3 release-asset digests (GitHub asset digests,
// re-read 2026-09-22). The Windows pair detects a cache folder protected
// against the current user but stops until that folder is deleted with
// administrator rights; rc.4 recovers without any manual repair. The
// macOS/Linux entries are byte-identical to the primary downloads above and
// are listed only for checksum continuity. Keep these as documentation; they
// must not be presented as recommended.
export const supersededAssets: ReleaseAsset[] = [
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows GUI (rc.3)",
    sha256: "a79e188706dd64fc9669b4df346808998079cfc1eb8df8705b5407af61fb4457",
    support: "No Authenticode signature; names every failure cause but needs a manual elevated folder delete on a protected cache - replaced by rc.4.",
  },
  {
    file: "encodingdb-client-windows-console.exe",
    label: "Windows console (rc.3)",
    sha256: "584cc0c5a2a91271e4167f937c4b7de0ecc23c6c25c7287f828845deb8a67155",
    support: "No Authenticode signature; same protected-cache limitation as the rc.3 GUI executable.",
  },
  {
    file: "EncodingDB-macOS-arm64.dmg",
    label: "macOS DMG (rc.3)",
    sha256: "2ec29a38cf36920d8eb030de97113cd37c56373a277ddbd79e46d1b0336c36ef",
    support: "Byte-identical to the current macOS download; same file republished under the rc.4 tag.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux archive (rc.3)",
    sha256: "b1a68a039ce78a6bc9718adbae99409865326ea8a8b3fc29e47aaa090ef0f4d8",
    support: "Byte-identical to the current Linux download; same file republished under the rc.4 tag.",
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
