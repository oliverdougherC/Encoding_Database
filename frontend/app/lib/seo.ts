import type { Metadata } from "next";

// Public identity must not inherit the internal API or local preview origin.
export const SITE_URL = "https://encodingdb.platinumlabs.dev";
export const HOME_TITLE = "Video Codec Database & Encoding Benchmarks | EncodingDB";
export const HOME_DESCRIPTION = "Compare video codec and FFmpeg encoder benchmarks: encoding speed, VMAF quality, bitrate, presets, and CPU/GPU hardware in a public, reproducible database.";

export function pageMetadata(path: string, title: string, description: string): Metadata {
  const url = `${SITE_URL}${path}`;
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { type: "website", siteName: "EncodingDB", locale: "en_US", url, title, description },
    twitter: { card: "summary", title, description },
  };
}

export const websiteSchema = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": `${SITE_URL}/#website`,
  name: "EncodingDB",
  alternateName: "Encoding Database",
  url: `${SITE_URL}/`,
  description: HOME_DESCRIPTION,
  inLanguage: "en",
  sameAs: ["https://github.com/oliverdougherC/Encoding_Database"],
};
