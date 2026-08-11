import { describe, expect, it } from "vitest";
import { computeGeneralPlV7, scorePlBenchmarkV7, type PlScoreV7Context } from "./plScore";

const context: PlScoreV7Context = {
  scoreFormulaVersion: "7.0",
  benchmarkProtocolVersion: "7.0",
  sourceSuiteVersion: "encodingdb-suite-v1",
  workloadId: "sports-1080p",
  workloadReferenceBitrateBps: 4_000_000,
  vmafModelId: "vmaf-v1-sdr-1080p",
  qualityExponent: 2.4,
  speedCurveRate: 1.2,
  speedSaturationRealtime: 4,
};
const input = { vmafMean: 94, vmafP5: 88, videoBitrateBps: 4_000_000, encodeFps: 60, sourceFps: 30 };

describe("PL Score v7", () => {
  it("is deterministic and exposes fixed Q/B/S components", () => {
    expect(scorePlBenchmarkV7(input, context)).toEqual(scorePlBenchmarkV7(input, context));
    expect(scorePlBenchmarkV7(input, context)?.components.bitrate).toBe(0.5);
  });

  it.each([
    [{ ...input, vmafMean: 95 }, "quality"],
    [{ ...input, videoBitrateBps: 3_000_000 }, "bitrate"],
    [{ ...input, encodeFps: 90 }, "speed"],
  ] as const)("is monotonic when %s improves", (better, _dimension) => {
    expect(scorePlBenchmarkV7(better, context)!.total).toBeGreaterThan(scorePlBenchmarkV7(input, context)!.total);
  });

  it("does not accept partial v6-era evidence", () => {
    expect(scorePlBenchmarkV7({ ...input, vmafP5: null }, context)).toBeNull();
    expect(scorePlBenchmarkV7({ ...input, sourceFps: 0 }, context)).toBeNull();
  });

  it("keeps scores bounded and makes a dominator rank higher", () => {
    const dominated = scorePlBenchmarkV7(input, context)!;
    const dominator = scorePlBenchmarkV7({ ...input, vmafMean: 96, videoBitrateBps: 3_000_000, encodeFps: 75 }, context)!;
    expect(dominator.total).toBeGreaterThan(dominated.total);
    expect(dominator.total).toBeLessThanOrEqual(100);
  });

  it("requires complete equal-class coverage for General PL", () => {
    expect(computeGeneralPlV7([80, 90], 2)).toBeCloseTo(Math.sqrt(80 * 90));
    expect(computeGeneralPlV7([80], 2)).toBeNull();
  });
});
