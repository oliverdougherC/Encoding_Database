import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AnalyticsFilterBar from "./AnalyticsFilterBar";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/leaderboards",
  useRouter: () => ({ replace }),
}));

describe("AnalyticsFilterBar", () => {
  beforeEach(() => {
    replace.mockReset();
  });

  it("updates the URL when a filter changes", () => {
    render(
      <AnalyticsFilterBar
        filters={{ contentClass: "mixed", resolution: "1080p", crf: 24, minSamples: 3 }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Resolution"), { target: { value: "720p" } });
    expect(replace).toHaveBeenCalledWith("/leaderboards?resolution=720p", { scroll: false });
  });
});
