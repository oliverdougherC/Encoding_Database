import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import styles from "./layout.module.css";
import ThemeToggle from "./components/ThemeToggle";

export const metadata: Metadata = {
  title: "Encoding Benchmarks",
  description: "Community-Submitted Encoding Benchmarks",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light"){document.documentElement.setAttribute("data-theme",t)}else if(window.matchMedia("(prefers-color-scheme:dark)").matches){document.documentElement.setAttribute("data-theme","dark")}}catch(e){}})()`,
          }}
        />
      </head>
      <body>
        <header className={styles.headerBar}>
          <nav className={styles.nav}>
            <Link href="/" className={`link ${styles.brandLink}`}>Encoding DB</Link>
            <div className={styles.navLinks}>
              <Link href="/" className={styles.navBtn}>Home</Link>
              <Link href="/plove" className={styles.navBtn}>PL Score</Link>
              <Link href="/compare-encoders" className={styles.navBtn}>Encoders</Link>
              <Link href="/leaderboards" className={styles.navBtn}>Leaderboards</Link>
              <Link href="/hardware" className={styles.navBtn}>Hardware</Link>
              <a href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer" className={styles.navBtn}>Download Client</a>
              <ThemeToggle />
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
