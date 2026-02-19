"use client";
import { useEffect, useState } from "react";

export type ChartTheme = {
  fg: string;
  surface: string;
  border: string;
  muted: string;
  accent: string;
};

const DEFAULTS: ChartTheme = {
  fg: "#173B34",
  surface: "#ffffff",
  border: "#CDDBCD",
  muted: "#6b7a6e",
  accent: "#6C8FD5",
};

function readTheme(): ChartTheme {
  if (typeof window === "undefined") return DEFAULTS;
  const s = getComputedStyle(document.documentElement);
  const g = (v: string) => s.getPropertyValue(v).trim();
  return {
    fg: g("--foreground") || DEFAULTS.fg,
    surface: g("--surface") || DEFAULTS.surface,
    border: g("--border") || DEFAULTS.border,
    muted: g("--muted") || DEFAULTS.muted,
    accent: g("--accent") || DEFAULTS.accent,
  };
}

export function useChartTheme(): ChartTheme {
  // Lazy initializer avoids light-theme flash on dark-mode first paint
  const [theme, setTheme] = useState<ChartTheme>(() =>
    typeof window !== "undefined" ? readTheme() : DEFAULTS,
  );
  useEffect(() => {
    setTheme(readTheme());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    // Re-read after the CSS transition settles
    const handler = () => setTimeout(() => setTheme(readTheme()), 50);
    mq.addEventListener("change", handler);
    // Also watch data-theme attribute changes
    const mo = new MutationObserver(handler);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", handler);
      mo.disconnect();
    };
  }, []);
  return theme;
}
