import { describe, expect, it } from "vitest";
import {
  buildAnalyticsSearchString,
  buildWorkbenchSearchString,
  parseAnalyticsSearchParams,
  parseWorkbenchSearchParams,
} from "./queryState";

describe("queryState", () => {
  it("builds stable workbench search strings", () => {
    const search = buildWorkbenchSearchString({
      page: 2,
      cpu: "Ryzen",
      gpu: "",
      codec: "nvenc",
      preset: "p6",
      sort: "codec",
      dir: "asc",
      encoderType: "hardware",
    });
    expect(search).toBe("page=2&cpu=Ryzen&codec=nvenc&preset=p6&sort=codec&dir=asc&encoderType=hardware");
  });

  it("parses workbench defaults and analytics overrides", () => {
    const workbench = parseWorkbenchSearchParams(new URLSearchParams("cpu=Intel&encoderType=software"));
    expect(workbench).toEqual({
      page: 1,
      cpu: "Intel",
      gpu: "",
      codec: "",
      preset: "",
      sort: "",
      dir: "desc",
      encoderType: "software",
    });

    const analytics = parseAnalyticsSearchParams(new URLSearchParams("resolution=720p&crf=26&minSamples=5"));
    expect(analytics).toEqual({
      contentClass: "mixed",
      resolution: "720p",
      crf: 26,
      minSamples: 5,
    });
  });

  it("omits default analytics filters from the query string", () => {
    expect(buildAnalyticsSearchString({
      contentClass: "mixed",
      resolution: "1080p",
      crf: 24,
      minSamples: 3,
    })).toBe("");
    expect(buildAnalyticsSearchString({
      contentClass: "action",
      resolution: "1080p",
      crf: 24,
      minSamples: 3,
    })).toBe("contentClass=action");
  });
});
