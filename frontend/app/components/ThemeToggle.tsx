"use client";

import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("theme");
      if (stored === "dark" || stored === "light") {
        setTheme(stored);
        document.documentElement.setAttribute("data-theme", stored);
      } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        setTheme("dark");
        document.documentElement.setAttribute("data-theme", "dark");
      } else {
        setTheme("light");
        document.documentElement.setAttribute("data-theme", "light");
      }
    } catch {
      setTheme("light");
    }
  }, []);

  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {}
    document.documentElement.setAttribute("data-theme", next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="btn"
      style={{ padding: "6px 10px", fontSize: 16, lineHeight: 1, cursor: "pointer" }}
      aria-label={theme ? `Switch to ${theme === "light" ? "dark" : "light"} mode` : "Toggle theme"}
      title={theme ? `Switch to ${theme === "light" ? "dark" : "light"} mode` : "Toggle theme"}
    >
      {theme === "dark" ? "\u2600" : "\u263E"}
    </button>
  );
}
