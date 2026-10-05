// Public rc.10 packages built from daa3e8e99e17e4cf99fb9440a90f96cbc25bdb2f.
// Anonymous public re-downloads verified all four hashes and sizes on 2026-10-05.
// COLLECTION_DOWNLOAD_BASE must still name the exact current release tag.

export const projectTag = "1.3.0-rc.10";
export const supersededTag = "1.3.0-rc.5";
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
  // Exact public download length; omitted for historical assets without a size stamp.
  byteSize?: number;
  support: string;
}

// Recommended primary downloads. Signing/support claims describe the current
// build chain; if the packaging lane changes them, root updates these lines at
// integration alongside the stamped digests.
export const primaryAssets: ReleaseAsset[] = [
  {
    file: "EncodingDB-macOS-arm64.dmg",
    label: "macOS (Apple Silicon)",
    sha256: "90dc77afbb208a0312595b63df76f9b647cb7110991ef8a9e5c46291ccb6f34c",
    byteSize: 129845535,
    support: "Double-clickable app inside a disk image; opens the guided menu in Terminal. Ad-hoc signed (not Developer ID, not notarized), so the first launch may need “Open Anyway” in System Settings → Privacy & Security (see first-launch help below). Native arm64; the embedded runtime requires macOS 27 or later; Intel Macs remain unverified.",
  },
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows (GUI)",
    sha256: "55f9c0ad6f874023395a0b9b7e99c90f30a0dc22fecab20268e336d52c2efc47",
    byteSize: 182728034,
    support: "Tested on Windows 11 x86-64; other Windows versions are unverified. No Authenticode signature, so SmartScreen may warn at first launch. The window exposes the same Small/Medium/Large/Full sweeps as the guided interface and recovers automatically from a cache folder protected against the current user.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux (x86-64)",
    sha256: "a774c16250ffd84b545a304e35c25be856fd3ef219d522d0f85cfd8be04b8777",
    byteSize: 201072452,
    support: "Tested on Ubuntu 24.04 x86-64; other Linux distributions are unverified. Unsigned archive; unpack it and run the launcher inside. Same guided flow; includes the command-line entry point for scripts.",
  },
];

export const currentWindowsConsole: ReleaseAsset = {
  file: "encodingdb-client-windows-console.exe",
  label: "Windows console",
  sha256: "ed7e18064ee99459301cf4c7c464827114b9d77e9d02543ce7f39fcbba6d2098",
  byteSize: 182731033,
  support: "Command-line entry point from the current release, built alongside the Windows GUI.",
};

// Preserve the actual published rc.5 asset identities for rollback and verification.
export const supersededAssets: ReleaseAsset[] = [
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows GUI (rc.5)",
    sha256: "2ec0a4bcb7d94af340e61a1837bfc9380b51b2dd60bbd1f48eb023dfa24c0379",
    support: "Earlier published rc.5 Windows GUI; no Authenticode signature.",
  },
  {
    file: "encodingdb-client-windows-console.exe",
    label: "Windows console (rc.5)",
    sha256: "05189da160c876f812cd16ae228b76df50bac8925d5763bb3d49ea9f0e42a60e",
    support: "Earlier published rc.5 Windows console; no Authenticode signature.",
  },
  {
    file: "EncodingDB-macOS-arm64.dmg",
    label: "macOS DMG (rc.5)",
    sha256: "cc6c6503293c8f01b223e1fac9a5da56888352d39c5e777cf90d23acec8aa8c6",
    support: "Earlier published rc.5 macOS disk image; ad-hoc signed and not notarized.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux archive (rc.5)",
    sha256: "b1a68a039ce78a6bc9718adbae99409865326ea8a8b3fc29e47aaa090ef0f4d8",
    support: "Earlier published rc.5 Linux archive; unsigned.",
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
