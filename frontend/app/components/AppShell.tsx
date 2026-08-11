"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import ThemeToggle from "./ThemeToggle";
import styles from "./AppShell.module.css";

const NAV = [
  { href: "/", label: "Browse" },
  { href: "/hardware", label: "Hardware" },
  { href: "/encoders", label: "Encoders" },
  { href: "/methodology", label: "Methodology" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [menuOpen, setMenuOpen] = useState(false);
  const active = (href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.bar}>
          <Link className={styles.brand} href="/" onClick={() => setMenuOpen(false)} aria-label="EncodingDB home">
            <span className={styles.brandMark}>EDB</span><span>EncodingDB</span>
          </Link>
          <button className={styles.menuButton} type="button" aria-label="Toggle navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>Menu</button>
          <nav className={`${styles.nav} ${menuOpen ? styles.navOpen : ""}`} aria-label="Primary navigation">
            {NAV.map((item) => <Link key={item.href} href={item.href} onClick={() => setMenuOpen(false)} aria-current={active(item.href) ? "page" : undefined} className={active(item.href) ? styles.active : ""}>{item.label}</Link>)}
          </nav>
          <div className={styles.actions}>
            <a href="https://github.com/oliverdougherC/Encoding_Database" target="_blank" rel="noreferrer">GitHub</a>
            <ThemeToggle />
            <a className={styles.runButton} href="/run">Run a benchmark</a>
          </div>
        </div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
