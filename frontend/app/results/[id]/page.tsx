import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { encodeCorpusIdPathSegment, fetchCorpusResult } from "../../lib/api";
import { realGpu } from "../../lib/hardwareLabel";
import { pageMetadata } from "../../lib/seo";
import ResultDetails from "./ResultDetails";

export const dynamic = "force-dynamic";

// Metadata and the page share a single lookup during a server render.
const getResult = cache(fetchCorpusResult);
type ResultPageProps = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: ResultPageProps): Promise<Metadata> {
  const { id } = await params;
  let row;
  try {
    row = await getResult(id);
  } catch {
    return {
      ...pageMetadata(`/results/${encodeCorpusIdPathSegment(id)}`, "Benchmark temporarily unavailable | EncodingDB", "This video encoding benchmark is temporarily unavailable. Please try again shortly."),
      robots: { index: false, follow: true },
    };
  }
  if (!row) notFound();
  const gpu = realGpu(row.gpuModel);
  const hardware = gpu ? `${gpu} with ${row.cpuModel}` : row.cpuModel;
  return pageMetadata(
    `/results/${encodeURIComponent(row.id)}`,
    `${row.encoderName} ${row.preset} benchmark on ${gpu ?? row.cpuModel} | EncodingDB`,
    `${row.codecFamily.toUpperCase()} video encoding benchmark: ${row.encoderName}, ${row.preset} preset, ${hardware}. Explore encoding speed, VMAF quality, bitrate, and evidence for ${row.workloadId}.`,
  );
}

export default async function ResultPage({ params }: ResultPageProps) {
  const { id } = await params;
  let row;
  try {
    row = await getResult(id);
  } catch {
    return <div className="page"><h1>Unable to load this result</h1><p>The corpus service is unavailable. Try again shortly.</p><a href="/">Browse corpus</a></div>;
  }
  if (!row) notFound();
  return <ResultDetails row={row} />;
}
