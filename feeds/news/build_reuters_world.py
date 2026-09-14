#!/usr/bin/env python3
"""Build a lightweight Reuters World RSS feed from Reuters' public news sitemaps.

Reuters' normal site blocks cloud scrapers, but its robots.txt explicitly
publishes news-sitemap endpoints for machine discovery. We use only those
metadata feeds: headline, publication time and original Reuters URL. Article
bodies are never fetched or copied.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reuters-world.xml"
DEBUG_OUTPUT = ROOT / "reuters-world-debug.json"
WORLD_URL = "https://www.reuters.com/world/"
NEWS_SITEMAP_INDEX = "https://www.reuters.com/arc/outboundfeeds/news-sitemap-index/?outputType=xml"
MAX_ITEMS = 30
MAX_CHILD_SITEMAPS = 24
USER_AGENT = "MicasReutersWorldFeed/1.1 (+https://github.com/MicaLovesKPOP/micas-space)"

NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
ARTICLE_PATH = re.compile(r"^/world(?:/[^/?#]+)+/[^/?#]+-\d{4}-\d{2}-\d{2}/?$")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()


def text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def canonical_reuters_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", "www.reuters.com", path, "", ""))


def child_sitemaps(index_xml: bytes) -> list[str]:
    root = ET.fromstring(index_xml)
    entries: list[tuple[datetime | None, int, str]] = []
    for i, sitemap in enumerate(root.findall("{*}sitemap")):
        loc = text(sitemap.find("{*}loc"))
        if not loc:
            continue
        lastmod = parse_dt(text(sitemap.find("{*}lastmod")))
        entries.append((lastmod, i, loc))

    if not entries:
        # Some sitemap indexes use nested loc elements without conventional wrappers.
        locs = [text(n) for n in root.findall(".//{*}loc") if text(n)]
        return locs[:MAX_CHILD_SITEMAPS]

    # Prefer the most recently modified child maps. Entries without lastmod retain
    # their original order after the dated maps.
    dated = [e for e in entries if e[0] is not None]
    undated = [e for e in entries if e[0] is None]
    dated.sort(key=lambda e: e[0], reverse=True)
    ordered = dated + undated
    return [e[2] for e in ordered[:MAX_CHILD_SITEMAPS]]


def region_from_path(path: str) -> str:
    bits = [b for b in path.split("/") if b]
    if len(bits) >= 2 and bits[0] == "world":
        return bits[1].replace("-", " ").title()
    return "World"


def parse_news_sitemap(xml_data: bytes) -> list[dict]:
    root = ET.fromstring(xml_data)
    items: list[dict] = []
    for url_node in root.findall("{*}url"):
        loc = text(url_node.find("{*}loc"))
        if not loc:
            continue
        parts = urlsplit(loc)
        if parts.hostname not in {"reuters.com", "www.reuters.com"}:
            continue
        if not ARTICLE_PATH.match(parts.path):
            continue

        news = url_node.find(f"{{{NEWS_NS}}}news")
        if news is None:
            # Be liberal about namespaces if Reuters changes the prefix/namespace.
            news = url_node.find("{*}news")
        title = ""
        published_raw = ""
        if news is not None:
            title = text(news.find(f"{{{NEWS_NS}}}title")) or text(news.find("{*}title"))
            published_raw = (
                text(news.find(f"{{{NEWS_NS}}}publication_date"))
                or text(news.find("{*}publication_date"))
            )
        if not title:
            continue

        canonical = canonical_reuters_url(loc)
        items.append(
            {
                "title": title,
                "url": canonical,
                "published_raw": published_raw,
                "published_dt": parse_dt(published_raw),
                "region": region_from_path(parts.path),
            }
        )
    return items


def discover() -> tuple[list[dict], dict]:
    index_xml = fetch(NEWS_SITEMAP_INDEX)
    children = child_sitemaps(index_xml)
    debug = {"child_sitemaps_found": len(children), "child_sitemaps_checked": []}

    by_url: dict[str, dict] = {}
    for child in children:
        child_debug = {"url": child}
        try:
            rows = parse_news_sitemap(fetch(child))
            child_debug["world_items"] = len(rows)
            for item in rows:
                current = by_url.get(item["url"])
                if current is None:
                    by_url[item["url"]] = item
                else:
                    a = item.get("published_dt")
                    b = current.get("published_dt")
                    if a and (not b or a > b):
                        by_url[item["url"]] = item
        except Exception as exc:
            child_debug["error"] = str(exc)
        debug["child_sitemaps_checked"].append(child_debug)

        # Current Google News sitemaps normally cover only a short recency window.
        # Once we have a healthy buffer there is no need to fetch older maps.
        if len(by_url) >= MAX_ITEMS * 3:
            break

    stories = list(by_url.values())
    stories.sort(
        key=lambda x: x.get("published_dt") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return stories[:MAX_ITEMS], debug


def build_rss(stories: list[dict]) -> None:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Reuters World — Mica"
    ET.SubElement(channel, "link").text = WORLD_URL
    ET.SubElement(channel, "description").text = (
        "Latest Reuters World stories rebuilt from Reuters' official news-sitemap metadata. "
        "Every item links directly to Reuters; no Google News, Reddit or proxy reader."
    )
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(channel, "generator").text = "MicasReutersWorldFeed"

    for story in stories:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = story["title"]
        ET.SubElement(item, "link").text = story["url"]
        guid = ET.SubElement(item, "guid", {"isPermaLink": "true"})
        guid.text = story["url"]
        if story.get("published_dt"):
            ET.SubElement(item, "pubDate").text = format_datetime(story["published_dt"])
        ET.SubElement(item, "category").text = story.get("region") or "World"
        source = ET.SubElement(item, "source", {"url": WORLD_URL})
        source.text = "Reuters"
        ET.SubElement(item, "description").text = (
            f"Reuters • World / {story.get('region', 'World')}\n\n"
            "Headline from Reuters' official news sitemap. Open the original Reuters story for the article."
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


def main() -> int:
    debug: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": NEWS_SITEMAP_INDEX,
        "max_items": MAX_ITEMS,
    }
    try:
        stories, discovery_debug = discover()
        debug.update(discovery_debug)
        if not stories:
            raise RuntimeError("Reuters news sitemaps yielded no /world/ articles")
        build_rss(stories)
        debug["final_items"] = len(stories)
        debug["items"] = [
            {
                "title": s["title"],
                "url": s["url"],
                "published": s.get("published_raw"),
                "region": s.get("region"),
            }
            for s in stories
        ]
    except Exception as exc:
        debug["fatal_error"] = str(exc)
        DEBUG_OUTPUT.write_text(json.dumps(debug, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Reuters feed build failed: {exc}")
        return 1

    DEBUG_OUTPUT.write_text(json.dumps(debug, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(stories)} Reuters World items to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
