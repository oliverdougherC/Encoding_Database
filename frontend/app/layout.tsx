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
            <a href="/" className="link" style={{ fontWeight: 600, textDecoration: "none" }}>Encoding DB</a>
            <div style={{ display: "flex", gap: 12 }}>
              <a href="/" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>Home</a>
              
              <a href="/plove" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>PLOVE</a>
              <a href="https://github.com/oliverdougherC/Encoding_Database/releases" target="_blank" rel="noreferrer" className="btn" style={{ textDecoration: "none", padding: "6px 10px" }}>Download Client</a>
            </div>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
