import type { MetadataRoute } from "next";
import { SITE_URL } from "./lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/api/", "/v7/", "/analytics/", "/submit", "/query", "/health", "/corpus", "/test-videos"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
