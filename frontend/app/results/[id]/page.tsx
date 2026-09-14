import { notFound } from "next/navigation";
import { fetchCorpusResult } from "../../lib/api";
import ResultDetails from "./ResultDetails";

export const dynamic = "force-dynamic";

export default async function ResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let row;
  try {
    row = await fetchCorpusResult(id);
  } catch {
    return <div className="page"><h1>Unable to load this result</h1><p>The corpus service is unavailable. Try again shortly.</p><a href="/">Browse corpus</a></div>;
  }
  if (!row) notFound();
  return <ResultDetails row={row} />;
}
