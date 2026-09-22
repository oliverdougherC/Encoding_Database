import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import BenchmarksTable, { BenchmarkDetailsDialog } from "./BenchmarksTable";
import type { Benchmark } from "../lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

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
      suspect: 1,
      rejected: 0,
      invalid: 0,
      repetitions: 4,
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

describe("BenchmarkDetailsDialog", () => {
  it("shows repetition counts in the details panel", () => {
    render(<BenchmarkDetailsDialog row={makeRow()} close={() => undefined} />);

    expect(screen.getByText("Repetitions")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText(/Unavailable: no public production DerivedResult published/)).toBeInTheDocument();
  });
});

describe("evidence interpretation", () => {
  it.each([
    ["suspect", "VERIFIED", 0, 4, "Suspect · review required", "Awaiting retention"],
    ["accepted", "RETAINED", 3, 0, "Accepted measurements", "Retained"],
    ["accepted", "MIXED_VERIFIED_RETAINED", 2, 2, "Accepted measurements", "Partially retained"],
    ["eligible-stable-groups", "RETAINED", 12, 2, "Stable measurement groups", "Retained"],
  ] as const)("separates %s centers, integrity, retention and null PL", (centerBasis, artifactState, accepted, suspect, basis, retention) => {
    render(<BenchmarkDetailsDialog row={makeRow({ status: { ...makeRow().status, centerBasis, artifactState }, sampleCounts: { ...makeRow().sampleCounts, accepted, suspect } })} close={() => {}} />);
    expect(screen.getByText(basis)).toBeInTheDocument();
    expect(screen.getByText("Verified bytes")).toBeInTheDocument();
    expect(screen.getByText(retention)).toBeInTheDocument();
    expect(screen.getByText(`${accepted} / ${suspect} / 0 / 0`)).toBeInTheDocument();
    expect(screen.getByText("Unavailable", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("LOW · not recommendation-eligible")).toBeInTheDocument();
  });
  it("does not invent confidence for sparse accepted evidence", () => {
    render(<BenchmarkDetailsDialog row={makeRow({ sampleCounts: { ...makeRow().sampleCounts, accepted: 1, suspect: 0 }, confidence: { ...makeRow().confidence, unavailableReason: "Insufficient independent sources" } })} close={() => {}} />);
    expect(screen.getByText("Insufficient independent sources")).toBeInTheDocument();
  });
});

describe("results table structure", () => {
  const renderTable = (rows: Benchmark[]) => render(<BenchmarksTable initialData={rows} totalCount={rows.length} currentPage={1} />);

  it("drives colgroup, header, and body from one shared column definition", () => {
    const { container } = renderTable([makeRow(), makeRow({ id: "row-b", encoderName: "libx264" })]);
    const cols = container.querySelectorAll("table > colgroup > col");
    const heads = [...container.querySelectorAll("table thead tr th")];
    expect(cols.length).toBe(heads.length);
    expect(heads.length).toBeGreaterThan(0);
    for (const tr of container.querySelectorAll("table tbody tr")) {
      expect(tr.querySelectorAll("td").length).toBe(heads.length);
    }
    // The metric labels exist exactly once, in order - no duplicated or
    // drifted header row outside the table.
    expect(heads.map((th) => th.textContent?.trim()).slice(1)).toEqual(["Hardware", "Encoder", "Configuration", "FPS", "VMAF", "Bitrate", "Evidence", "Runs", "Details"]);
  });

  it("exposes sorting through real columnheaders with aria-sort", () => {
    renderTable([makeRow()]);
    const before = screen.getByRole("button", { name: "FPS" }).closest("th");
    expect(before).toHaveAttribute("aria-sort", "none");
    fireEvent.click(screen.getByRole("button", { name: "FPS" }));
    expect(screen.getByRole("button", { name: /FPS/ }).closest("th")).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(screen.getByRole("button", { name: /FPS/ }));
    expect(screen.getByRole("button", { name: /FPS/ }).closest("th")).toHaveAttribute("aria-sort", "ascending");
  });

  it("keeps the empty state a single spanning row inside the table flow", () => {
    const { container } = renderTable([]);
    expect(screen.getByText(/No benchmark results match these filters/)).toBeInTheDocument();
    const cells = container.querySelectorAll("table tbody td");
    expect(cells).toHaveLength(1);
    expect(cells[0]).toHaveAttribute("colspan", "10");
    expect(screen.getByRole("link", { name: "Run a benchmark" })).toHaveAttribute("href", "/run");
  });

  it("keeps a GPU-less hardware encoder honest: CPU primary, OS secondary, no CPU-only claim", () => {
    // hevc_videotoolbox on Apple silicon is hardware encoding even with no
    // named GPU; absence of a gpuModel must not read as "CPU-only".
    renderTable([makeRow({ id: "row-m2", encoderName: "hevc_videotoolbox", cpuModel: "Apple M2", gpuModel: "not-applicable", os: "macOS 15.6" })]);
    expect(screen.getByText("Apple M2")).toBeInTheDocument();
    expect(screen.getByText("macOS 15.6")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("not-applicable");
    expect(document.body).not.toHaveTextContent("CPU-only");
  });

  it("reports 'GPU not reported' in the details panel instead of a CPU-only inference", () => {
    render(<BenchmarkDetailsDialog row={makeRow({ encoderName: "hevc_videotoolbox", cpuModel: "Apple M2", gpuModel: "not-applicable" })} close={() => {}} />);
    expect(screen.getByText("GPU not reported · Apple M2")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("CPU-only");
  });
});
