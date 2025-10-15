import { NextRequest, NextResponse } from "next/server";

// Redirect helper that tries to resolve a direct TechPowerUp model page
// by scraping the first search result. Falls back to search when unknown.

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const kind = (searchParams.get("kind") || "").toLowerCase();
  const q = (searchParams.get("q") || "").trim();
  if (!q) {
    return NextResponse.redirect("https://www.techpowerup.com/");
  }

  const decoded = decodeURIComponent(q);
  const encoded = encodeURIComponent(decoded);

  const base = "https://www.techpowerup.com";
  const searchUrl = kind === "cpu"
    ? `${base}/cpu-specs/?q=${encoded}`
    : `${base}/gpu-specs/?q=${encoded}`;

  try {
    const res = await fetch(searchUrl, { headers: { "user-agent": "Mozilla/5.0" }, cache: "no-store" });
    if (!res.ok) throw new Error("search fetch failed");
    const html = await res.text();
    // Parse all model links with their visible names
    const linkRegex = kind === "cpu"
      ? /<a[^>]+href="(\/cpu-specs\/[^"#?]+)"[^>]*>([^<]+)<\/a>/gi
      : /<a[^>]+href="(\/gpu-specs\/[^"#?]+)"[^>]*>([^<]+)<\/a>/gi;
    const candidates: Array<{ href: string; name: string; score: number }> = [];
    const norm = (s: string) => s.toLowerCase().replace(/[®™]/g, "").replace(/[^a-z0-9+\.\- ]+/g, " ").replace(/\s+/g, " ").trim();
    const target = norm(decoded);
    let m: RegExpExecArray | null;
    while ((m = linkRegex.exec(html))) {
      const href = m[1];
      const name = (m[2] || "").trim();
      const n = norm(name);
      // Exact name match gets highest score, prefix/substring matches get lower
      let score = 0;
      if (n === target) score = 100;
      else if (n.startsWith(target)) score = 80;
      else if (target.startsWith(n)) score = 70;
      else if (n.includes(target)) score = 60;
      else continue;
      candidates.push({ href, name, score });
    }
    candidates.sort((a, b) => b.score - a.score);
    if (candidates[0]) {
      return NextResponse.redirect(base + candidates[0].href);
    }
  } catch {}

  return NextResponse.redirect(searchUrl);
}


