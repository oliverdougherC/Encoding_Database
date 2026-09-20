// Release-aware download model for the collection client.
//
// The four verified collection builds are packaged from source revision
// a350d45 (application candidate b3ef24a plus the recorded upload-only
// client tip deltas) and carry project version 1.3.0-rc.1 / client
// protocol 0.3.0. They become downloadable only when the operator publishes
// them as GitHub release assets for that tag and verifies the checksums;
// the deployment then sets COLLECTION_DOWNLOAD_BASE. While the variable is
// unset the page must NOT advertise the new URLs as live - it stages the
// exact file names and verified checksums instead. Historical 1.2.0
// (client/0.2.0) assets stay reachable but cannot submit to a server that
// requires protocol 7.1.

export const projectTag = "1.3.0-rc.1";
export const historicalTag = "1.2.0";
export const repoReleases = "https://github.com/oliverdougherC/Encoding_Database/releases";

export interface ReleaseAsset {
  file: string;
  label: string;
  sha256: string;
  support: string;
}

// Checksums are the accepted release-executable identities recorded in
// docs/operations/evidence/integration-recovery-20260920/package-acceptance.json
// and each build's SHA256SUMS receipt. These are release artifacts, distinct
// from the frozen b3ef24a calibration binary (443e293e...).
export const collectionAssets: ReleaseAsset[] = [
  {
    file: "encodingdb-client-windows.exe",
    label: "Windows GUI",
    sha256: "9af36d251e94f7c261f163775db286eaf4c5988ea0d3a30f0346ba9719670cd0",
    support: "Unsigned; measured on a physical Windows 11 / RTX 5090 host (GUI acceptance r9).",
  },
  {
    file: "encodingdb-client-windows-console.exe",
    label: "Windows console",
    sha256: "0637ad12e31fd20adfeb4d26ea1b377d8e21c26fde1db341ead6fca0a7b4ee97",
    support: "Unsigned; same physical host build as the GUI executable.",
  },
  {
    file: "encodingdb-client-linux",
    label: "Linux (x86-64)",
    sha256: "e8927096799fc4c7592a375b0318bb2313f36fe00f950cfeb555ac93c29d5a9e",
    support: "Unsigned; built and replay-accepted on Ubuntu 24.04 (NVENC host).",
  },
  {
    file: "encodingdb-client-macos",
    label: "macOS (Apple Silicon)",
    sha256: "93339fda368d9285e8ba7d6c79d40de1a1069ca638839c126e8d5cb88f1e9a89",
    support: "Unsigned and not notarized; native arm64 build with embedded arm64 FFmpeg helpers (no Rosetta). Expect a Gatekeeper prompt at first launch.",
  },
];

export interface DownloadModel {
  published: boolean;
  base: string;
  items: Array<ReleaseAsset & { href: string | null }>;
}

// Empty/absent COLLECTION_DOWNLOAD_BASE means "assets staged, not yet
// published": hrefs stay null so the page can show the plan without
// claiming an unpublished URL is live.
export function downloadModel(env: Record<string, string | undefined>): DownloadModel {
  const base = (env.COLLECTION_DOWNLOAD_BASE ?? "").trim().replace(/\/+$/, "");
  const published = base.length > 0;
  return {
    published,
    base,
    items: collectionAssets.map((a) => ({ ...a, href: published ? `${base}/${a.file}` : null })),
  };
}
