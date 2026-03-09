import type { Benchmark } from "../components/BenchmarksTable";
import { fetchBenchmarks } from "../lib/fetchBenchmarks";
import EncoderDashboardClient from "./EncoderDashboardClient";
import StatusBanner from "../components/ui/StatusBanner";
import PageHeader from "../components/ui/PageHeader";

export const revalidate = 60;

export default async function EncoderComparisonPage() {
  let data: Benchmark[] = [];
  let error: string | null = null;
  try {
    data = await fetchBenchmarks();
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  if (error) {
    return (
      <div className="page">
        <PageHeader title="Compare Workspace" subtitle="Select and benchmark encoder contenders side by side." />
        <StatusBanner kind="error">Failed to load data: {error}</StatusBanner>
      </div>
    );
  }

  return <EncoderDashboardClient data={data} />;
}
