#!/usr/bin/env python3
"""Check crawlable, server-rendered SEO on a local build or public deployment."""
import argparse
from html.parser import HTMLParser
import json
import subprocess
import xml.etree.ElementTree as ET

CANONICAL = "https://encodingdb.platinumlabs.dev"
PAGES = ["/", "/encoders", "/hardware", "/methodology", "/run", "/leaderboards"]


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.meta, self.canonicals, self.links, self.schemas = {}, [], [], []
        self.title, self.h1 = "", ""
        self.in_title = self.in_h1 = self.in_schema = False
        self.schema = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("name", attrs.get("property"))] = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href"))
        if tag == "a":
            self.links.append(attrs.get("href"))
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.in_h1 = True
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.in_schema = True
            self.schema = ""

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_h1:
            self.h1 += data
        if self.in_schema:
            self.schema += data

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_h1 = False
        if tag == "script" and self.in_schema:
            self.schemas.append(json.loads(self.schema))
            self.in_schema = False


def fetch(base, path, status=200):
    result = subprocess.run([
        "curl", "-sS", "--max-time", "45", "--user-agent", "Googlebot",
        "--write-out", "\n%{http_code}", base + path,
    ], capture_output=True, text=True, check=True)
    body, actual = result.stdout.rsplit("\n", 1)
    assert int(actual) == status, f"{path}: expected HTTP {status}, got {actual}"
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=CANONICAL)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    titles, descriptions = set(), set()
    for path in PAGES:
        page = Page(fetch(base, path))
        assert page.title and "EncodingDB" in page.title, f"{path}: missing site title"
        assert page.h1, f"{path}: missing server-rendered heading"
        assert page.canonicals == [(CANONICAL + path).rstrip("/")], f"{path}: incorrect canonical"
        description = page.meta.get("description", "")
        assert description, f"{path}: missing description"
        assert "noindex" not in page.meta.get("robots", ""), f"{path}: noindex"
        assert page.meta.get("og:url") == (CANONICAL + path).rstrip("/"), f"{path}: incorrect sharing URL"
        assert page.meta.get("og:title") == page.title, f"{path}: sharing title mismatch"
        assert page.meta.get("twitter:description") == description, f"{path}: sharing description mismatch"
        assert page.title not in titles and description not in descriptions, f"{path}: duplicate metadata"
        titles.add(page.title)
        descriptions.add(description)
        if path == "/":
            assert "video codec database" in page.h1.lower()
            assert all(target in page.links for target in PAGES[1:]), "Missing crawlable homepage links"
            assert any(schema.get("@type") == "WebSite" and schema.get("url") == CANONICAL + "/" for schema in page.schemas), "Missing WebSite structured data"
            result_links = [href for href in page.links if href and href.startswith("/results/")]
            if result_links:
                result_path = result_links[0]
                result = Page(fetch(base, result_path))
                assert result.title != page.title and "benchmark" in result.title.lower(), "Result needs its own title"
                assert result.canonicals == [CANONICAL + result_path], "Result canonical mismatch"
                assert "noindex" not in result.meta.get("robots", ""), "Existing result must be indexable"
                print("PASS crawlable benchmark result with individual metadata")
        print(f"PASS {path}: title, description, canonical, heading, sharing metadata")
    filtered = Page(fetch(base, "/?search=av1&sort=fps"))
    assert filtered.canonicals == [CANONICAL], "Filter URLs must consolidate to the browse page"
    robots = fetch(base, "/robots.txt")
    assert f"Sitemap: {CANONICAL}/sitemap.xml" in robots, "Missing sitemap discovery"
    assert "Allow: /" in robots and "Disallow: /api/" in robots, "Missing crawler rules"
    root = ET.fromstring(fetch(base, "/sitemap.xml"))
    urls = [node.text for node in root.findall("{*}url/{*}loc")]
    assert sorted(urls) == sorted(CANONICAL + path for path in PAGES), "Sitemap canonical pages differ"
    missing = Page(fetch(base, "/seo-check-page-that-does-not-exist", status=404))
    assert "noindex" in missing.meta.get("robots", ""), "404 must not be indexed"
    print("PASS filtered canonical, robots.txt, sitemap.xml, and real noindex 404")


if __name__ == "__main__":
    main()
