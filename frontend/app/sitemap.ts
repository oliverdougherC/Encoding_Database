import type { MetadataRoute } from "next";
import { SITE_URL } from "./lib/seo";

export default function sitemap(): MetadataRoute.Sitemap {
  // List canonical public pages, not filters, legacy redirects, or API endpoints.
  // Omit lastModified until an actual content modification date is available.
  return ["/", "/encoders", "/hardware", "/methodology", "/run", "/leaderboards"]
    .map((path) => ({ url: `${SITE_URL}${path}` }));
}
