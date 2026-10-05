import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";
import HardwarePage from "./hardware/page";
import EncodersPage from "./encoders/page";
import LeaderboardsPage from "./leaderboards/page";
vi.mock("./lib/api", () => {
  const unavailable = () => Promise.reject(new Error("Failed http://internal:3000/private: 503"));
  return { fetchWorkbenchPage: unavailable, fetchHardwareDirectory: unavailable, fetchEncoderDirectory: unavailable, fetchLeaderboards: unavailable };
});
afterEach(cleanup);
describe("unavailable data", () => {
  it.each([
    ["browse", Home, "/"], ["hardware", HardwarePage, "/hardware"],
    ["encoders", EncodersPage, "/encoders"], ["leaderboards", LeaderboardsPage, "/leaderboards"],
  ] as const)("keeps %s navigable with a safe retry and no fabricated counts", async (_name, Page, href) => {
    render(await Page({}));
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", href);
    expect(document.body).not.toHaveTextContent("http://internal");
    expect(document.body).not.toHaveTextContent("503");
    expect(screen.queryByLabelText("Hardware corpus summary")).not.toBeInTheDocument();
  });
});
