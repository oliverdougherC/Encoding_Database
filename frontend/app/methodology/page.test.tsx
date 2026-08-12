import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MethodologyPage from "./page";

describe("MethodologyPage", () => {
  it("documents the fixed v7 score, separate fit/confidence semantics, and rollout limits", () => {
    render(<MethodologyPage />);

    expect(screen.getByRole("heading", { name: "Methodology" })).toBeInTheDocument();
    expect(screen.getByText("Pre-epoch status")).toBeInTheDocument();
    expect(screen.getByText(/public v7 epoch is not open/i)).toBeInTheDocument();
    expect(screen.getByText(/provisional, recommendation-ineligible policy/i)).toBeInTheDocument();
    expect(screen.getByText(/PL7 = 100 x Q\^0\.50 x B\^0\.30 x S\^0\.20/)).toBeInTheDocument();
    expect(screen.getByText(/V_PL = 0\.85 x VMAF mean \+ 0\.15 x VMAF P5/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "PL Fit" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Confidence" })).toBeInTheDocument();
    expect(screen.getByText(/General PL7 = geometric mean of equal-class PL7 scores/)).toBeInTheDocument();
    expect(screen.getByText(/older or incomplete evidence remains visible without being mislabeled as final PL Score v7/i)).toBeInTheDocument();
  });
});
