import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import StatsCards from "./components/StatsCards";
import ErrorBoundary from "./components/ErrorBoundary";
import CommandWorkbench from "./components/CommandWorkbench";
import PageHeader from "./components/ui/PageHeader";
import SectionCard from "./components/ui/SectionCard";
import ActionStrip from "./components/ui/ActionStrip";
import StatusBanner from "./components/ui/StatusBanner";
import styles from "./page.module.css";

export const revalidate = 60;

function computeSystemSnapshot(data: Benchmark[]) {
  const withVmaf = data.filter((d) => typeof d.vmaf === "number").length;
  const withPower = data.filter((d) => typeof d.gpuPowerAvgW === "number" && (d.gpuPowerAvgW ?? 0) > 0).length;
  const withCpuUtil = data.filter((d) => typeof d.cpuUtilAvg === "number").length;
  const hardwareRows = data.filter((d) => (d.encoderName ?? d.codec ?? "").toLowerCase().match(/(_videotoolbox|_nvenc|_qsv|_amf|_vaapi)$/)).length;
  return {
    qualityCoverage: data.length > 0 ? Math.round((withVmaf / data.length) * 100) : 0,
    powerCoverage: data.length > 0 ? Math.round((withPower / data.length) * 100) : 0,
    telemetryCoverage: data.length > 0 ? Math.round((withCpuUtil / data.length) * 100) : 0,
    hardwareShare: data.length > 0 ? Math.round((hardwareRows / data.length) * 100) : 0,
  };
}

function toUrlSearchParams(raw: Record<string, string | string[] | undefined> | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (!raw) return params;
  for (const [key, value] of Object.entries(raw)) {
    if (Array.isArray(value)) {
      if (value[0]) params.set(key, value[0]);
      continue;
    }
    if (value) params.set(key, value);
  }
  return params;
}

export default async function Home({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  let data: Benchmark[] = [];
  let totalCount = 0;
  let error: string | null = null;
  const params = toUrlSearchParams(searchParams ? await searchParams : undefined);
  const workbenchState = parseWorkbenchSearchParams(params);
  const queryKey = buildWorkbenchSearchString(workbenchState);
  try {
    const result = await fetchWorkbenchPage(workbenchState);
    data = result.rows;
    totalCount = result.totalCount;
  } catch (e: unknown) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  const snapshot = computeSystemSnapshot(data);

  return (
    <div className={`page ${styles.layout}`}>
      <PageHeader
        title="Command Center"
        subtitle="Prioritize your next encoding decision: compare contenders, inspect benchmark evidence, and move straight to action."
      />

      <SectionCard title="Quick Actions" subtitle="Jump directly into high-value workflows.">
        <ActionStrip
          actions={[
            { label: "Open Compare Workspace", href: "/compare-encoders", tone: "primary" },
            { label: "View Leaderboards", href: "/leaderboards", tone: "secondary" },
            { label: "Hardware Recommendations", href: "/hardware", tone: "secondary" },
            { label: "Download Client", href: "https://github.com/oliverdougherC/Encoding_Database/releases", tone: "secondary" },
          ]}
        />
      </SectionCard>

      {error ? (
        <StatusBanner kind="error" className={styles.errorState}>
          Failed to load data: {error}
        </StatusBanner>
      ) : (
        <>
          <div className={styles.topGrid}>
            <SectionCard title="Key Metrics" subtitle="Current benchmark inventory and breadth.">
              <StatsCards data={data} totalCount={totalCount} />
            </SectionCard>

            <SectionCard title="System Snapshot" subtitle="Current page coverage across the active benchmark slice.">
              <div className={styles.snapshotGrid}>
                <SnapshotStat label="Quality coverage" value={`${snapshot.qualityCoverage}%`} />
                <SnapshotStat label="Power coverage" value={`${snapshot.powerCoverage}%`} />
                <SnapshotStat label="Telemetry coverage" value={`${snapshot.telemetryCoverage}%`} />
                <SnapshotStat label="Hardware-encoder share" value={`${snapshot.hardwareShare}%`} />
              </div>
              <div className={styles.snapshotNotes}>
                <span className="subtle">Snapshot metrics reflect the currently loaded page, not the full dataset.</span>
              </div>
            </SectionCard>
          </div>

          <ErrorBoundary>
            <CommandWorkbench data={data} totalCount={totalCount} queryKey={queryKey} currentPage={workbenchState.page} />
          </ErrorBoundary>

          <SectionCard title="Test Clip" subtitle="Reference baseline used by submissions for consistency.">
            <p className={styles.testClipText}>
              Recorded in ProRes 4:2:2, 10-bit, 3840x2160, 30FPS SDR. Transcoded baseline: x264 4:2:0, 8-bit, 1920x1080,
              RF 0, profile main, level 4.0, preset veryslow, VFR 30FPS SDR.
            </p>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function SnapshotStat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.snapshotCard}>
      <div className={styles.snapshotLabel}>{label}</div>
      <div className={styles.snapshotValue}>{value}</div>
    </div>
  );
}
