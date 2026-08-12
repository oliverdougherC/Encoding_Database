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
      search: "nvenc",
      preset: "p6",
      sort: "codec",
      dir: "asc",
      encoderType: "hardware",
    });
    expect(search).toBe("page=2&cpu=Ryzen&search=nvenc&preset=p6&sort=codec&dir=asc&encoderType=hardware");
  });

  it("parses workbench defaults and analytics overrides", () => {
    const workbench = parseWorkbenchSearchParams(new URLSearchParams("cpu=Intel&encoderType=software"));
    expect(workbench).toEqual({
      page: 1,
      cpu: "Intel",
      gpu: "",
      search: "",
      preset: "",
      sort: "",
      dir: "desc",
      encoderType: "software",
    });

    const analytics = parseAnalyticsSearchParams(new URLSearchParams("resolution=720p&crf=26&minSamples=5&scoreContextId=context-1"));
    expect(analytics).toEqual({
      workloadId: "",
      environmentId: "",
      environmentFingerprint: "",
      scoreContextId: "context-1",
      contentClass: "mixed",
      resolution: "720p",
      minSamples: 5,
      fitMode: "balanced",
      customQualityWeight: null,
      customBitrateWeight: null,
      customSpeedWeight: null,
      minimumQuality: null,
      minimumRealtimeRatio: null,
      maximumBitrateMbps: null,
      compatibleCodecFamilies: null,
      requireRecommendationEligibility: false,
    });
  });

  it("accepts aggregate sample sorting and rejects telemetry sample sorting", () => {
    expect(parseWorkbenchSearchParams(new URLSearchParams("sort=samples"))).toMatchObject({ sort: "samples" });
    expect(parseWorkbenchSearchParams(new URLSearchParams("sort=sampleCount"))).toMatchObject({ sort: "" });
  });

  it("omits default analytics filters from the query string", () => {
    expect(buildAnalyticsSearchString({
      contentClass: "mixed",
      resolution: "1080p",
      minSamples: 3,
      fitMode: "balanced",
    })).toBe("");
    expect(buildAnalyticsSearchString({
      contentClass: "action",
      resolution: "1080p",
      minSamples: 3,
      fitMode: "balanced",
    })).toBe("contentClass=action");
  });
});
