#!/usr/bin/env python3
"""Small policy/cleanup layer around curated_feed.py.

Keeping this separate makes it easy to tune the editorial rules without
rewriting the main feed builder.
"""

from __future__ import annotations

from urllib.parse import urlparse

import curated_feed as base


# Autoblog list/features are editorial rather than daily news and fit the feed.
for term in ("lijstje:", "lijstje "):
    if term not in base.AUTOBLOG_FEATURE_TERMS:
        base.AUTOBLOG_FEATURE_TERMS.append(term)


# Autovisie uses singular `sjoerd-weetjes` in the actual URL. Redirect the old
# spelling transparently so the base source list remains backwards-compatible.
_original_parse_feed = base.parse_feed


def parse_feed(name: str, url: str):
    if "sjoerds-weetjes" in url:
        url = url.replace("sjoerds-weetjes", "sjoerd-weetjes")
    return _original_parse_feed(name, url)


base.parse_feed = parse_feed


# Scraped section pages sometimes expose navigation links as if they were
# articles. Remove those and keep the extras deliberately small so the main
# AutoWeek news feed is not drowned out by historical feature pages.
_original_scrape_listing = base.scrape_listing
_GENERIC_TITLES = {
    "all articles",
    "newsletters",
    "newsletter",
    "ph heroes",
    "buying guides",
    "used buying guides",
    "six of the best",
    "shed of the week",
    "spotted",
}
_GENERIC_PATH_PARTS = (
    "/author/",
    "/newsletter/",
    "/all-articles/",
    "/category/",
    "/tags/",
)


def clean_scrape_listing(name, url, host_suffix, accept, reason, max_items=20):
    # Pull a few extra candidates first so deleting navigation junk does not
    # unnecessarily starve the useful results.
    items = _original_scrape_listing(
        name,
        url,
        host_suffix,
        accept,
        reason,
        max_items=min(max(max_items, 12), 16),
    )

    source_url = url.rstrip("/")
    kept = []
    for item in items:
        path = urlparse(item.link).path.lower()
        title = base.lower(item.title)
        reject = (
            item.link.rstrip("/") == source_url
            or title in _GENERIC_TITLES
            or any(part in path for part in _GENERIC_PATH_PARTS)
        )
        if reject:
            # Correct the earlier optimistic scraper decision in debug output.
            for row in reversed(base.debug["decisions"]):
                if row.get("link") == item.link and row.get("keep") is True:
                    row["keep"] = False
                    row["reason"] = "navigatie/sectielink, geen artikel"
                    break
            continue
        kept.append(item)
        if len(kept) >= 8:
            break

    return kept


base.scrape_listing = clean_scrape_listing


if __name__ == "__main__":
    raise SystemExit(base.main())
