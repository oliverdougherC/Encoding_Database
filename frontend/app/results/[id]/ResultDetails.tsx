"use client";
import { useRouter } from "next/navigation";
import type { Benchmark } from "../../lib/types";
import { BenchmarkDetailsDialog } from "../../components/BenchmarksTable";

export default function ResultDetails({ row }: { row: Benchmark }) {
  const router = useRouter();
  return <BenchmarkDetailsDialog row={row} close={() => router.push("/")} />;
}
