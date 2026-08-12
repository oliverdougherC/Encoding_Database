import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MethodologyPage from "./page";

describe("MethodologyPage", () => {
  it("renders the concise v7 reference and KaTeX equations", () => {
    const { container } = render(<MethodologyPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Methodology" })).toBeInTheDocument();
    expect(screen.getByText("PL Score v7")).toBeInTheDocument();
    expect(screen.getByText("PL Score v7 combines quality, bitrate efficiency, and encode speed into one fixed score for a single benchmark workload.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Calculation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "General PL7" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rules" })).toBeInTheDocument();
    expect(screen.getByText("Technical notes")).toBeInTheDocument();
    expect(screen.getByText(/the v7 formula is fixed, but calibration remains provisional/i)).toBeInTheDocument();
    expect(container.querySelectorAll(".katex").length).toBeGreaterThan(8);
  });

  it("selects one formula component at a time", () => {
    const { container } = render(<MethodologyPage />);
    const view = within(container);

    const quality = view.getByRole("button", { name: "Quality" });
    const bitrate = view.getByRole("button", { name: "Bitrate" });
    const speed = view.getByRole("button", { name: "Speed" });

    expect(quality).toHaveAttribute("aria-pressed", "true");
    expect(bitrate).toHaveAttribute("aria-pressed", "false");
    expect(speed).toHaveAttribute("aria-pressed", "false");
    expect(view.getByText(/short bad moments are not hidden/i)).toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Quality" }).nextElementSibling).toHaveTextContent("50%");

    fireEvent.click(bitrate);
    expect(bitrate).toHaveAttribute("aria-pressed", "true");
    expect(quality).toHaveAttribute("aria-pressed", "false");
    expect(view.getByText(/frozen reference bitrate/i)).toBeInTheDocument();

    fireEvent.click(speed);
    expect(speed).toHaveAttribute("aria-pressed", "true");
    expect(bitrate).toHaveAttribute("aria-pressed", "false");
    expect(view.getByText(/cap at 4× real-time/i)).toBeInTheDocument();
  });
});
