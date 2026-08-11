import { describe, expect, it } from "vitest";
import type { Benchmark } from "../lib/types";
import { acceptedSamples } from "./BenchmarksTable";
import { hasIncompatibleWorkloads } from "./ComparePanel";

const benchmark = (overrides: Partial<Benchmark> = {}): Benchmark => ({
  id: "row",
  createdAt: "2026-08-11T00:00:00Z",
  cpuModel: "CPU",
  gpuModel: "GPU",
  ramGB: 32,
  os: "Linux",
  codec: "av1",
  preset: "fast",
  fps: 100,
  vmaf: 95,
  ssim: 0.99,
  psnr: 42,
  fileSizeBytes: 1_000_000,
  notes: null,
  samples: 1,
  contentClass: "mixed",
  resolution: "1080p",
  passes: 1,
  inputHash: "canonical-input",
  ...overrides,
});

describe("workbench aggregate semantics", () => {
  it("uses accepted submissions rather than telemetry samples", () => {
    expect(acceptedSamples(benchmark({ samples: 1, sampleCount: 150 }))).toBe(1);
  });

  it("treats identical configurations and workload identities as compatible", () => {
    expect(hasIncompatibleWorkloads([benchmark({ id: "a" }), benchmark({ id: "b" })])).toBe(false);
  });

  it.each([
    ["codec", { codec: "hevc" }],
    ["preset", { preset: "slow" }],
    ["CRF", { crf: 28 }],
    ["content class", { contentClass: "animation" }],
    ["resolution", { resolution: "4k" }],
    ["pass count", { passes: 2 }],
    ["canonical input", { inputHash: "different-input" }],
  ])("warns when %s differs", (_label, difference) => {
    expect(hasIncompatibleWorkloads([benchmark({ id: "a" }), benchmark({ id: "b", ...difference })])).toBe(true);
  });
});
