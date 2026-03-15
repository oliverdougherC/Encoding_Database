"use client";

import { useState } from "react";
import type { Benchmark } from "../lib/types";
import BenchmarksTable from "./BenchmarksTable";
import SectionCard from "./ui/SectionCard";
import Button from "./ui/Button";
import styles from "./CommandWorkbench.module.css";

export default function CommandWorkbench({
  data,
  totalCount,
  queryKey,
  currentPage,
}: {
  data: Benchmark[];
  totalCount: number;
  queryKey: string;
  currentPage: number;
}) {
  const [open, setOpen] = useState(true);

  return (
    <SectionCard
      title="Active Workbench"
      subtitle="Filter, rank, and inspect benchmark rows."
      rightSlot={
        <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="workbench-grid">
          {open ? "Collapse" : "Expand"}
        </Button>
      }
    >
      {open ? (
        <div id="workbench-grid" className={styles.workbenchBody}>
          <BenchmarksTable key={queryKey} initialData={data} totalCount={totalCount} currentPage={currentPage} />
        </div>
      ) : (
        <div className={styles.collapsed}>Workbench collapsed. Expand to continue interactive filtering.</div>
      )}
    </SectionCard>
  );
}
