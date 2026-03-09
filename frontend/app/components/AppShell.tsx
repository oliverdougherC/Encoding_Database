"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";
import ThemeToggle from "./ThemeToggle";
import styles from "./AppShell.module.css";

type NavItem = { href: string; label: string };

const CORE_NAV: NavItem[] = [
  { href: "/", label: "Command Center" },
  { href: "/compare-encoders", label: "Compare" },
  { href: "/leaderboards", label: "Leaderboards" },
  { href: "/hardware", label: "Hardware" },
  { href: "/plove", label: "PL Reference" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [mobileOpen, setMobileOpen] = useState(false);
  const activePath = useMemo(() => pathname, [pathname]);

  return (
    <div className={styles.shell}>
      <button
        type="button"
        className={styles.mobileMenuBtn}
        aria-expanded={mobileOpen}
        aria-controls="workspace-nav"
        onClick={() => setMobileOpen((v) => !v)}
      >
        Workspace
      </button>

      {mobileOpen ? <button type="button" aria-label="Close navigation" className={styles.backdrop} onClick={() => setMobileOpen(false)} /> : null}

      <aside id="workspace-nav" className={`${styles.sidebar} ${mobileOpen ? styles.sidebarOpen : ""}`.trim()}>
        <div className={styles.brandRow}>
          <Link href="/" className={styles.brand} onClick={() => setMobileOpen(false)}>
            <span className={styles.brandMark} aria-hidden="true">EDB</span>
            <span className={styles.brandText}>Encoding Database</span>
          </Link>
          <ThemeToggle className={styles.themeToggle} />
        </div>

        <div className={styles.quickActions}>
          <a href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer" className={styles.quickAction}>
            Download Client
          </a>
        </div>

        <nav className={styles.navSection} aria-label="Core">
          <div className={styles.sectionTitle}>Core</div>
          <div className={styles.itemList}>
            {CORE_NAV.map((item) => {
              const active = item.href === "/" ? activePath === "/" : activePath.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={`${styles.navItem} ${active ? styles.navItemActive : ""}`.trim()}
                  aria-current={active ? "page" : undefined}
                >
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </nav>

      </aside>

      <main className={styles.workspace}>{children}</main>
    </div>
  );
}
