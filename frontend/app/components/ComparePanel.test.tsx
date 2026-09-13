import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import ComparePanel from "./ComparePanel";
import type { Benchmark } from "../lib/types";

function makeRow(overrides: Partial<Benchmark> = {}): Benchmark {
  return {
    id: "row-a",
    createdAt: "2026-08-12T00:00:00.000Z",
    cpuModel: "CPU",
    gpuModel: "GPU",
    ramGB: 32,
    os: "Linux",
    codec: "hevc",
    codecFamily: "hevc",
    encoderName: "libx265",
    preset: "slow",
    fps: 120,
    vmaf: 95,
    vmafP5: 93,
    fileSizeBytes: 80_000_000,
    videoBitrateBps: 4_500_000,
    sourceFps: 30,
    realTimeRatio: 4,
    samples: 2,
    workloadId: "mixed-1080p",
    recipe: {
      id: "recipe-1",
      fingerprint: "recipe-fingerprint",
      encoderVersion: "7.1",
      tune: null,
      profile: "main",
      level: "5.1",
      tier: null,
      pixelFormat: "yuv420p10le",
      bitDepth: 10,
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
      id: "env-1",
      fingerprint: "environment-fingerprint",
      cpuArchitecture: "x86_64",
      physicalCoreCount: 16,
      logicalThreadCount: 32,
      physicalMemoryBytes: 34359738368,
      gpuModel: "GPU",
      selectedAccelerator: "cuda",
      driverVersion: "555.12",
      osName: "Linux",
      osVersion: "6.10",
      ffmpegBuildFingerprint: "ffmpeg-build-fingerprint",
      ffmpegVersion: "7.1",
      clientVersion: "client/0.2.0",
    },
    versions: {
      aggregatorVersion: "v7-public-corpus-direct-read-model/v3",
      benchmarkProtocolId: "protocol-1",
      benchmarkProtocolVersion: "benchmark-protocol-v1",
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
      accepted: 2,
      suspect: 0,
      rejected: 0,
      invalid: 0,
      repetitions: 3,
      independentSources: 2,
      machines: 1,
      contributors: null,
    },
    performance: {
      encodeFps: 120,
      realTimeRatio: 4,
    },
    quality: {
      vmafMean: 95,
      vmafP5: 93,
      qualityModelId: "vmaf-v1-sdr-sd",
    },
    bitrate: {
      videoBitrateBps: 4_500_000,
      fileSizeBytes: 80_000_000,
      workloadReferenceBitrateBps: null,
    },
    confidence: {
      available: false,
      lower: null,
      upper: null,
      width: null,
      unavailableReason: "No matching production-activatable DerivedResult has been published for this workload identity.",
    },
    pl: {
      total: null,
      components: null,
    },
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("ComparePanel", () => {
  it("shows repetition counts in the comparison matrix", () => {
    render(<ComparePanel rows={[
      makeRow({ id: "row-a", sampleCounts: { ...makeRow().sampleCounts, repetitions: 3 } }),
      makeRow({ id: "row-b", environment: { ...makeRow().environment, fingerprint: "env-2" }, sampleCounts: { ...makeRow().sampleCounts, repetitions: 5 } }),
    ]} onClose={() => undefined} onClear={() => undefined} />);

    expect(screen.getByText("Repetitions")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });
});
