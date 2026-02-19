import { NextRequest, NextResponse } from "next/server";

// Redirect helper that tries to resolve a direct TechPowerUp model page
// by scraping the first search result. Falls back to search when unknown.

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const kind = (searchParams.get("kind") || "").toLowerCase();
    const q = (searchParams.get("q") || "").trim();

    if (!q) {
      return NextResponse.redirect("https://www.techpowerup.com/");
    }

    const encoded = encodeURIComponent(q);

    const base = "https://www.techpowerup.com";
    const searchUrl = kind === "cpu"
      ? `${base}/cpu-specs/?q=${encoded}`
      : `${base}/gpu-specs/?q=${encoded}`;

    try {
      const res = await fetch(searchUrl, {
        headers: { "user-agent": "Mozilla/5.0" },
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });

      if (!res.ok) {
        console.error(`TechPowerUp search failed: ${res.status}`);
        return NextResponse.redirect(searchUrl);
      }

      const html = await res.text();

      // Parse all model links with their visible names using matchAll (safer than exec loop)
      const linkPattern = kind === "cpu"
        ? /<a[^>]+href="(\/cpu-specs\/[^"#?]+)"[^>]*>([^<]+)<\/a>/gi
        : /<a[^>]+href="(\/gpu-specs\/[^"#?]+)"[^>]*>([^<]+)<\/a>/gi;

      const matches = html.matchAll(linkPattern);

      const candidates: Array<{ href: string; name: string; score: number; index: number }> = [];
      const norm = (s: string) =>
        s.toLowerCase()
          .replace(/[®™]/g, "")
          .replace(/[^a-z0-9+.\- ]+/g, " ")
          .replace(/\s+/g, " ")
          .trim();
      const target = norm(q);

      let idx = 0;
      for (const m of matches) {
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

        candidates.push({ href, name, score, index: idx++ });
      }

      candidates.sort((a, b) => (b.score - a.score) || (a.index - b.index));

      // For GPUs, prefer the first result even if names are similar (e.g., 5090 vs 5090D)
      if (candidates[0]) {
        return NextResponse.redirect(base + candidates[0].href);
      }

      // No matching candidate found, redirect to search
      return NextResponse.redirect(searchUrl);
    } catch (fetchError) {
      console.error("Error fetching TechPowerUp:", fetchError);
      return NextResponse.redirect(searchUrl);
    }
  } catch (error) {
    // Top-level error handler for any unexpected errors
    console.error("hwlink route error:", error);
    return NextResponse.redirect("https://www.techpowerup.com/");
  }
}
