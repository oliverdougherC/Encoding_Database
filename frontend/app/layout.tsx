import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import styles from "./layout.module.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

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
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <header className={styles.headerBar}>
          <nav className={styles.nav}>
            <Link href="/" className={`link ${styles.brandLink}`}>Encoding DB</Link>
            <div className={styles.navLinks}>
              <Link href="/" className={`btn ${styles.navBtn}`}>Home</Link>
              <Link href="/plove" className={`btn ${styles.navBtn}`}>PLOVE</Link>
              <a href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer" className={`btn ${styles.navBtn}`}>Download Client</a>
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
