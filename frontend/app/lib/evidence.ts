import type { Benchmark } from "./types";

export function measurementBasis(row: Benchmark): string {
  if (row.status.centerBasis === "eligible-stable-groups") return "Stable measurement groups";
  if (row.status.centerBasis === "suspect") return "Suspect · review required";
  if (row.status.centerBasis === "accepted") return "Accepted measurements";
  return "Measurement basis unknown";
}

export function artifactIntegrity(row: Benchmark): string {
  return row.status.artifactState ? "Verified bytes" : "Unknown";
}

export function artifactRetention(row: Benchmark): string {
  switch (row.status.artifactState) {
    case "RETAINED": return "Retained";
    case "VERIFIED": return "Awaiting retention";
    case "MIXED_VERIFIED_RETAINED": return "Partially retained";
    default: return "Unknown";
  }
}

export const hasPublicPl = (row: Benchmark) => row.status.scoring === "PUBLIC" && row.pl.total != null;
