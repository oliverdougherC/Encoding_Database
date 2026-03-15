"use client";

import { usePathname, useRouter } from "next/navigation";
import type { AnalyticsFilters } from "../lib/types";
import { buildAnalyticsSearchString } from "../lib/queryState";
import styles from "./AnalyticsFilterBar.module.css";

const CONTENT_CLASSES = [
  { value: "mixed", label: "Mixed" },
  { value: "talkingHead", label: "Talking Head" },
  { value: "action", label: "Action" },
  { value: "animation", label: "Animation" },
  { value: "screen", label: "Screen" },
  { value: "nature", label: "Nature" },
  { value: "gaming", label: "Gaming" },
];

const RESOLUTIONS = ["480p", "720p", "1080p", "1440p", "4k"];
const CRF_OPTIONS = [18, 20, 22, 24, 26, 28, 30];

export default function AnalyticsFilterBar({
  filters,
  className = "",
}: {
  filters: AnalyticsFilters;
  className?: string;
}) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";

  function replace(next: AnalyticsFilters) {
    const query = buildAnalyticsSearchString(next);
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return (
    <div className={`${styles.bar} ${className}`.trim()}>
      <label className={styles.control}>
        <span className={styles.label}>Content</span>
        <select
          className={`input ${styles.select}`}
          value={filters.contentClass}
          onChange={(event) => replace({ ...filters, contentClass: event.target.value })}
        >
          {CONTENT_CLASSES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.control}>
        <span className={styles.label}>Resolution</span>
        <select
          className={`input ${styles.select}`}
          value={filters.resolution}
          onChange={(event) => replace({ ...filters, resolution: event.target.value })}
        >
          {RESOLUTIONS.map((resolution) => (
            <option key={resolution} value={resolution}>
              {resolution}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.control}>
        <span className={styles.label}>CRF</span>
        <select
          className={`input ${styles.select}`}
          value={String(filters.crf)}
          onChange={(event) => replace({ ...filters, crf: Number(event.target.value) })}
        >
          {CRF_OPTIONS.map((crf) => (
            <option key={crf} value={crf}>
              {crf}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.control}>
        <span className={styles.label}>Min Samples</span>
        <input
          type="number"
          min={1}
          step={1}
          className={`input ${styles.select}`}
          value={filters.minSamples}
          onChange={(event) => replace({ ...filters, minSamples: Math.max(1, Number(event.target.value) || 1) })}
        />
      </label>
    </div>
  );
}
