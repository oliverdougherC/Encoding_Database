import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RunPage from "./page";

describe("RunPage", () => {
  it("distinguishes published downloads from corrected source commands and resumes publication", () => {
    render(<RunPage />);
    expect(screen.getByText(/do not support the new campaign commands/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Linux" })).toHaveAttribute("href", expect.stringContaining("/1.2.0/encodingdb-client-linux"));
    expect(screen.getByText("python -m client --resume-campaign CAMPAIGN_ID --submit")).toBeInTheDocument();
    expect(screen.getByText(/python -m client --upload-only/)).toBeInTheDocument();
    expect(document.body).toHaveTextContent("--campaign full");
    expect(document.body).not.toHaveTextContent("--suite-mode");
    expect(document.body).toHaveTextContent("An upload receipt means analysis is pending");
  });
});
