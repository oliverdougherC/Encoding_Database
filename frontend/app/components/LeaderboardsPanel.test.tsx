import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildMockLeaderboards } from "../api/_lib/mockData";
import LeaderboardsPanel from "./LeaderboardsPanel";
import type { LeaderboardAnalyticsResponse } from "../lib/types";

afterEach(() => {
  cleanup();
});

function payloadForMode(mode: "balanced" | "quality" | "storage" | "realtime") {
  const payload = structuredClone(buildMockLeaderboards()) as LeaderboardAnalyticsResponse;
  payload.selectedMode = mode;
  const recommendedByMode = {
    balanced: "row-balanced",
    quality: "row-quality",
    storage: "row-storage",
    realtime: "row-realtime",
  } as const;
  const labels = {
    "row-balanced": "hevc_videotoolbox medium",
    "row-quality": "libx265 slow",
    "row-storage": "av1_qsv balanced",
    "row-realtime": "h264_nvenc p6",
  } as const;
  payload.recommendation = {
    rowId: recommendedByMode[mode],
    label: labels[recommendedByMode[mode]],
    reason: "Best eligible PL Fit result after hard constraints, evidence gating, and Pareto ordering.",
  };
  for (const row of payload.rows) {
    row.fit.selectedMode = mode;
    row.fit.recommended = row.rowId === recommendedByMode[mode];
  }
  payload.rows.sort((left, right) => left.fit.modes[mode].rank - right.fit.modes[mode].rank);
  return payload;
}

describe("LeaderboardsPanel", () => {
  it.each([
    ["balanced", "hevc_videotoolbox medium", "hevc_videotoolbox"],
    ["quality", "libx265 slow", "libx265"],
    ["storage", "av1_qsv balanced", "av1_qsv"],
    ["realtime", "h264_nvenc p6", "h264_nvenc"],
  ] as const)("renders the %s recommendation flow", (mode, recommendation, _firstEncoder) => {
    render(<LeaderboardsPanel payload={payloadForMode(mode)} />);

    expect(screen.getByText(recommendation)).toBeInTheDocument();
    const activeMode = document.querySelector('nav[aria-label="PL Fit modes"] [aria-current="page"]');
    expect(activeMode?.textContent).toMatch(new RegExp(`^${mode}$`, "i"));
    expect(screen.getByText(/PL Score stays fixed/i)).toBeInTheDocument();
  });
});
