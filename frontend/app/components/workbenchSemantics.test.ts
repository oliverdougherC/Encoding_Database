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
  codecFamily: "av1",
  encoderName: "svtav1",
  preset: "fast",
  fps: 100,
  vmaf: 95,
  vmafP5: 93,
  fileSizeBytes: 1_000_000,
  videoBitrateBps: 3_000_000,
  sourceFps: 30,
  realTimeRatio: 3.33,
  samples: 1,
  workloadId: "mixed-1080p",
  recipe: {
    id: "recipe",
    fingerprint: "recipe-fingerprint",
    encoderVersion: "1.0",
    tune: null,
    profile: null,
    level: null,
    tier: null,
    pixelFormat: "yuv420p",
    bitDepth: 8,
    chromaSubsampling: "4:2:0",
    rateControl: {
      requestedMode: "CQ",
      effectiveMode: "CQ",
      qualityValue: 24,
      targetBitrateKbps: null,
      maxBitrateKbps: null,
      bufferSizeKbits: null,
      label: "CQ 24",
    },
  },
  environment: {
    id: "env",
    fingerprint: "env-fingerprint",
    cpuArchitecture: "x86_64",
    physicalCoreCount: 16,
    logicalThreadCount: 32,
    gpuModel: "GPU",
    selectedAccelerator: "cuda",
    driverVersion: "1",
    osName: "Linux",
    osVersion: "1",
    ffmpegBuildFingerprint: "ffmpeg-fp",
    ffmpegVersion: "7.1",
    clientVersion: "2.4.0",
  },
  versions: {
    aggregatorVersion: "derived-result-aggregation/v2-cluster-bootstrap",
    benchmarkProtocolId: "proto",
    benchmarkProtocolVersion: "EDB-2026.1",
    sourceSuiteVersion: "encodingdb-test-suite-v1",
    qualityModelId: "vmaf-v1-sdr-sd",
    formulaVersion: null,
    scoreContextId: null,
    referenceContextVersion: null,
    analysisWorkerVersion: "authoritative-analysis/v1",
  },
  status: {
    benchmarkProtocol: "ACTIVE",
    artifactState: "RETAINED",
    centerBasis: "accepted",
    scoring: "UNSCORED_NO_PUBLIC_DERIVED_RESULT",
    evidenceTier: "LOW",
    eligibleForDefaultRecommendation: false,
  },
  sampleCounts: {
    accepted: 1,
    suspect: 0,
    rejected: 0,
    invalid: 0,
    repetitions: 1,
    independentSources: 1,
    machines: 1,
    contributors: 1,
  },
  performance: {
    encodeFps: 100,
    realTimeRatio: 3.33,
  },
  quality: {
    vmafMean: 95,
    vmafP5: 93,
    qualityModelId: "vmaf-v1-sdr-sd",
  },
  bitrate: {
    videoBitrateBps: 3_000_000,
    fileSizeBytes: 1_000_000,
    workloadReferenceBitrateBps: null,
  },
  confidence: {
    available: false,
    lower: null,
    upper: null,
    width: null,
    unavailableReason: "Withheld",
  },
  pl: {
    total: null,
    components: null,
  },
  ...overrides,
});

describe("workbench aggregate semantics", () => {
  it("uses accepted benchmark runs rather than telemetry-style counters", () => {
    expect(acceptedSamples(benchmark({ samples: 1, sampleCounts: { accepted: 4, suspect: 2, rejected: 0, invalid: 0, repetitions: 6, independentSources: 2, machines: 2, contributors: 2 } }))).toBe(4);
  });

  it("treats identical workload, recipe, environment, and protocol identities as compatible", () => {
    expect(hasIncompatibleWorkloads([benchmark({ id: "a" }), benchmark({ id: "b" })])).toBe(false);
  });

  it.each([
    ["workload", { workloadId: "animation-1080p" }],
    ["recipe fingerprint", { recipe: { ...benchmark().recipe, fingerprint: "different-recipe" } }],
    ["environment fingerprint", { environment: { ...benchmark().environment, fingerprint: "different-env" } }],
    ["reference context lineage", { versions: { ...benchmark().versions, referenceContextVersion: "public-context-v1" } }],
    ["benchmark protocol", { versions: { ...benchmark().versions, benchmarkProtocolVersion: "EDB-2026.2" } }],
  ])("warns when %s differs", (_label, difference) => {
    expect(hasIncompatibleWorkloads([benchmark({ id: "a" }), benchmark({ id: "b", ...difference })])).toBe(true);
  });
});
