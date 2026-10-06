import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { fetchCorpusResult } from "../../lib/api";
import type { Benchmark } from "../../lib/types";
import { SITE_URL } from "../../lib/seo";
import ResultPage, { generateMetadata } from "./page";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../lib/api")>(),
  fetchCorpusResult: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_HTTP_ERROR_FALLBACK;404"); },
}));
vi.mock("./ResultDetails", () => ({ default: ({ row }: { row: Benchmark }) => <p>{row.encoderName} result</p> }));

// Only metadata fields are needed; ResultDetails is tested with complete rows elsewhere.
const row = {
  id: "protocol::workload/a + b",
  encoderName: "hevc_nvenc",
  preset: "p7",
  codecFamily: "hevc",
  gpuModel: "NVIDIA GeForce RTX 4070",
  cpuModel: "AMD Ryzen 9 7950X",
  workloadId: "mixed-1080p",
} as Benchmark;
const props = { params: Promise.resolve({ id: row.id }) };

beforeEach(() => { vi.mocked(fetchCorpusResult).mockReset(); });
afterEach(cleanup);

describe("result page metadata", () => {
  it("uses the result's encoder, preset, hardware, and canonical identity for search and sharing", async () => {
    vi.mocked(fetchCorpusResult).mockResolvedValue(row);
    const metadata = await generateMetadata(props);
    const canonical = `${SITE_URL}/results/${encodeURIComponent(row.id)}`;
    expect(metadata.title).toBe("hevc_nvenc p7 benchmark on NVIDIA GeForce RTX 4070 | EncodingDB");
    expect(metadata.description).toContain("HEVC video encoding benchmark");
    expect(metadata.description).toContain("NVIDIA GeForce RTX 4070 with AMD Ryzen 9 7950X");
    expect(metadata.description).toContain("mixed-1080p");
    expect(metadata.alternates?.canonical).toBe(canonical);
    expect(metadata.openGraph).toMatchObject({ url: canonical, title: metadata.title, description: metadata.description });
    expect(metadata.twitter).toMatchObject({ title: metadata.title, description: metadata.description });
  });

  it("uses CPU identity when no named GPU is reported", async () => {
    vi.mocked(fetchCorpusResult).mockResolvedValue({ ...row, encoderName: "libx265", preset: "slow", gpuModel: "not-applicable" });
    const metadata = await generateMetadata(props);
    expect(metadata.title).toBe("libx265 slow benchmark on AMD Ryzen 9 7950X | EncodingDB");
    expect(metadata.description).not.toContain("not-applicable");
  });

  it("keeps missing results as not-found pages during metadata and page rendering", async () => {
    vi.mocked(fetchCorpusResult).mockResolvedValue(null);
    await expect(generateMetadata(props)).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
    await expect(ResultPage(props)).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
  });

  it("prevents indexing transient failures and retains the graceful page error", async () => {
    vi.mocked(fetchCorpusResult).mockRejectedValue(new Error("Service unavailable"));
    const encodedProps = { params: Promise.resolve({ id: encodeURIComponent(row.id) }) };
    const metadata = await generateMetadata(encodedProps);
    expect(metadata.robots).toEqual({ index: false, follow: true });
    expect(metadata.title).toBe("Benchmark temporarily unavailable | EncodingDB");
    expect(metadata.alternates?.canonical).toBe(`${SITE_URL}/results/${encodeURIComponent(row.id)}`);
    expect(metadata.openGraph).toMatchObject({ title: metadata.title, description: metadata.description });
    render(await ResultPage(encodedProps));
    expect(screen.getByRole("heading", { name: "Unable to load this result" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse corpus" })).toHaveAttribute("href", "/");
  });
});
