// Release-aware download model for the collection client (target 1.3.0-rc.2).
//
// The packaged rc.2 builds - macOS DMG with a double-clickable app, Windows
// GUI executable, Linux archive with a launcher - are being produced on the
// client lane. They become downloadable only when the operator publishes them
// as GitHub release assets under tag `1.3.0-rc.2` and stamps the verified
// SHA-256 digests into `primaryAssets` during integration.
//
// COLLECTION_DOWNLOAD_BASE must be the full download base for the CURRENT tag,
// e.g. `https://github.com/<owner>/<repo>/releases/download/1.3.0-rc.2`.
// The model fails closed on any other value: the currently deployed base
// still points at the published 1.3.0-rc.1 assets, and rc.2 file names must
// never be concatenated onto that path. Publication is therefore keyed to the
// exact tag segment, not merely to a non-empty variable.
//
// 1.3.0-rc.1 stays published as plain command-line builds (the macOS asset is
// a bare extensionless executable); it is listed as superseded, never as the
// recommended download. 1.2.0 (client/0.2.0, protocol 7.0) is historical and
// cannot submit to the protocol 7.1 server.

export const projectTag = "1.3.0-rc.2";
export const supersededTag = "1.3.0-rc.1";
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
    sha256: null,
    support: "Double-clickable app inside a disk image; opens the guided menu in Terminal. Ad-hoc signed (not Developer ID, not notarized), so the first launch may need “Open Anyway” in System Settings → Privacy & Security (see first-launch help below). Native arm64; the embedded runtime requires macOS 27 or later; Intel Macs remain unverified.",
  },
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows (GUI)",
    sha256: null,
    support: "No Authenticode signature, so SmartScreen may warn at first launch. The window exposes the same Small/Medium/Large/Full sweeps as the guided interface.",
  },
  {
    file: "encodingdb-client-linux.tar.gz",
    label: "Linux (x86-64)",
    sha256: null,
    support: "Unsigned archive; unpack it and run the launcher inside. Same guided flow; includes the command-line entry point for scripts.",
  },
];

// Published but superseded command-line builds (client/0.3.0, protocol 7.1).
// Checksums are the accepted release-executable identities recorded in
// docs/operations/evidence/integration-recovery-20260920/package-acceptance.json
// and each build's SHA256SUMS receipt (all four re-hashed on-disk 2026-09-20).
// Keep these as documentation; they must not be presented as recommended.
export const supersededAssets: ReleaseAsset[] = [
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows GUI (rc.1)",
    sha256: "9af36d251e94f7c261f163775db286eaf4c5988ea0d3a30f0346ba9719670cd0",
    support: "No Authenticode signature; measured on one physical Windows 11 / RTX 5090 host (GUI acceptance r9).",
  },
  {
    file: "encodingdb-client-windows-console.exe",
    label: "Windows console (rc.1)",
    sha256: "0637ad12e31fd20adfeb4d26ea1b377d8e21c26fde1db341ead6fca0a7b4ee97",
    support: "No Authenticode signature; same physical host and build session as the GUI executable.",
  },
  {
    file: "encodingdb-client-linux",
    label: "Linux x86-64 (rc.1)",
    sha256: "e8927096799fc4c7592a375b0318bb2313f36fe00f950cfeb555ac93c29d5a9e",
    support: "Unsigned; built and replay-accepted on Ubuntu 24.04 (NVIDIA NVENC host).",
  },
  {
    file: "encodingdb-client-macos",
    label: "macOS Apple Silicon (rc.1)",
    sha256: "93339fda368d9285e8ba7d6c79d40de1a1069ca638839c126e8d5cb88f1e9a89",
    support: "Bare extensionless executable (no app bundle) - superseded by the DMG. Ad-hoc signed (not Developer ID, not notarized); native arm64 with an embedded runtime requiring macOS 27 or later (tested on macOS 27.0 build 26A428); older macOS and Intel Macs unverified. No Rosetta.",
  },
];

export interface DownloadModel {
  published: boolean;
  base: string;
  items: Array<ReleaseAsset & { href: string | null }>;
}

// A missing/mismatched base means "assets staged, not yet published": hrefs
// stay null so the page can stage the plan without claiming an unpublished
// URL is live - and without ever resolving rc.2 names under another tag.
export function downloadModel(env: Record<string, string | undefined>): DownloadModel {
  const base = (env[downloadBaseEnvVar] ?? "").trim().replace(/\/+$/, "");
  const published = base.endsWith(`/download/${projectTag}`);
  return {
    published,
    base,
    items: primaryAssets.map((a) => ({ ...a, href: published ? `${base}/${a.file}` : null })),
  };
}
