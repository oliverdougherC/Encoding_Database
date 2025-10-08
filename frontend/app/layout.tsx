import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

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
        <header style={{ borderBottom: "1px solid var(--border)", padding: "12px 24px" }}>
          <nav style={{ display: "flex", alignItems: "center", justifyContent: "space-between", maxWidth: 1200, margin: "0 auto" }}>
            <div style={{ fontWeight: 600 }}>Encoding DB</div>
            <div style={{ display: "flex", gap: 12 }}>
              <a href="/" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>Home</a>
              <a href="/graphs" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>Graphs</a>
              <a href="/plove" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>PLOVE</a>
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
