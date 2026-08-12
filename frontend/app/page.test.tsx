import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Home from "./page";

vi.mock("./lib/api", () => ({
  fetchWorkbenchPage: vi.fn(async () => ({
    totalCount: 7,
    rows: [
      {
        id: "row-1",
        createdAt: "2026-08-12T00:00:00.000Z",
        cpuModel: "Apple M2",
        gpuModel: null,
        ramGB: 8,
        os: "macOS 15.6",
        codec: "hevc",
        codecFamily: "hevc",
        encoderName: "hevc_videotoolbox",
        preset: "medium",
        fps: 80.2,
        vmaf: 92.4,
        vmafP5: 91.7,
        fileSizeBytes: 70 * 1024 * 1024,
        videoBitrateBps: 3_950_000,
        sourceFps: 30,
        realTimeRatio: 2.67,
        samples: 3,
        workloadId: "mixed-1080p",
        recipe: {
          id: "recipe-1",
          fingerprint: "recipe-fingerprint-1",
          encoderVersion: "VideoToolbox 1.0",
          tune: null,
          profile: "main",
          level: "5.0",
          tier: "main",
          pixelFormat: "yuv420p10le",
          bitDepth: 10,
          chromaSubsampling: "4:2:0",
          rateControl: {
            requestedMode: "VBR",
            effectiveMode: "VBR",
            qualityValue: null,
            targetBitrateKbps: 3950,
            maxBitrateKbps: 4300,
            bufferSizeKbits: 7900,
            label: "VBR 3950 kbps (max 4300 kbps, buffer 7900 kbit)",
          },
        },
        environment: {
          id: "env-1",
          fingerprint: "env-fingerprint-1",
          cpuArchitecture: "arm64",
          physicalCoreCount: 8,
          logicalThreadCount: 8,
          physicalMemoryBytes: 8589934592,
          gpuModel: null,
          selectedAccelerator: "videotoolbox",
          driverVersion: null,
          osName: "macOS",
          osVersion: "15.6",
          ffmpegBuildFingerprint: "ffmpeg-build-fingerprint-1",
          ffmpegVersion: "7.1",
          clientVersion: "2.4.0",
        },
        versions: {
          aggregatorVersion: "derived-result-aggregation/v2-cluster-bootstrap",
          benchmarkProtocolId: "proto-1",
          benchmarkProtocolVersion: "EDB-2026.1",
          sourceSuiteVersion: "encodingdb-test-suite-v1",
          qualityModelId: "vmaf-v1-sdr-sd",
          formulaVersion: null,
          scoreContextId: null,
          referenceContextVersion: null,
        },
        status: {
          benchmarkProtocol: "ACTIVE",
          artifactState: "RETAINED",
          centerBasis: "accepted",
          scoring: "UNSCORED_NO_PUBLIC_DERIVED_RESULT",
          evidenceTier: "PROVISIONAL",
          eligibleForDefaultRecommendation: false,
        },
        sampleCounts: {
          accepted: 3,
          suspect: 1,
          rejected: 0,
          invalid: 0,
          repetitions: 4,
          independentSources: 2,
          machines: 1,
          contributors: 2,
        },
        performance: {
          encodeFps: 80.2,
          realTimeRatio: 2.67,
        },
        quality: {
          vmafMean: 92.4,
          vmafP5: 91.7,
          qualityModelId: "vmaf-v1-sdr-sd",
        },
        bitrate: {
          videoBitrateBps: 3_950_000,
          fileSizeBytes: 70 * 1024 * 1024,
          workloadReferenceBitrateBps: null,
        },
        confidence: {
          available: false,
          lower: null,
          upper: null,
          width: null,
          unavailableReason: "PL and PL confidence are withheld until a production-activatable reference context is published.",
        },
        pl: {
          total: null,
          components: null,
        },
      },
    ],
  })),
}));

vi.mock("./components/BenchmarksTable", () => ({
  default: ({ initialData, totalCount }: { initialData: Array<{ encoderName: string; status: { scoring: string } }>; totalCount: number }) => (
    <div>
      <div>table-count:{totalCount}</div>
      {initialData.map((row) => <div key={row.encoderName}>{row.encoderName} · {row.status.scoring === "PUBLIC" ? "PL public" : "PL unavailable"}</div>)}
    </div>
  ),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Home page", () => {
  it("renders V7 corpus counts and withheld scoring copy from the API payload", async () => {
    render(await Home({ searchParams: Promise.resolve({}) }));

    expect(screen.getByText("V7 public corpus")).toBeInTheDocument();
    expect(screen.getByText("Brevity is the soul of wit.")).toBeInTheDocument();
    expect(document.body).toHaveTextContent("7 V7 aggregates");
    expect(document.body).toHaveTextContent("1 environments on this page");
    expect(screen.getByText(/hevc_videotoolbox/)).toBeInTheDocument();
    expect(screen.getAllByText(/PL unavailable/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Legacy .*query.* aggregates remain separate; this surface is V7-only\./)).toBeInTheDocument();
  });
});
