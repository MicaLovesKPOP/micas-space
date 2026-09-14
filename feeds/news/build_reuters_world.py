#!/usr/bin/env python3
"""Build a lightweight RSS feed from Reuters' public World section.

Reuters no longer offers the old public RSS endpoints. This script reads the
public World landing page, keeps the stories Reuters itself places there, and
writes a normal RSS 2.0 feed for Inoreader. It stores only headline, a short
publisher-provided description, timestamp and original Reuters URL; it never
copies article bodies.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reuters-world.xml"
DEBUG_OUTPUT = ROOT / "reuters-world-debug.json"
WORLD_URL = "https://www.reuters.com/world/"
BASE_URL = "https://www.reuters.com"
MAX_ITEMS = 30
USER_AGENT = (
    "Mozilla/5.0 (compatible; MicasReutersWorldFeed/1.0; "
    "+https://github.com/MicaLovesKPOP/micas-space)"
)
ARTICLE_PATH = re.compile(r"^/world(?:/[^/?#]+)+/[^/?#]+-\d{4}-\d{2}-\d{2}/?$")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def trim(value: str, limit: int = 520) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rsplit(" ", 1)[0] + "…"


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", "www.reuters.com", path, "", ""))


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()


def discover_world_stories() -> list[dict]:
    soup = BeautifulSoup(fetch(WORLD_URL), "html.parser")
    by_url: dict[str, dict] = {}

    for a in soup.find_all("a", href=True):
        href = urljoin(WORLD_URL, a.get("href", ""))
        parts = urlsplit(href)
        if parts.hostname not in {"reuters.com", "www.reuters.com"}:
            continue
        if not ARTICLE_PATH.match(parts.path):
            continue

        url = canonical_url(href)
        text = clean_text(a.get_text(" ", strip=True))
        current = by_url.get(url)
        if current is None:
            by_url[url] = {"url": url, "title": text}
        elif len(text) > len(current.get("title", "")):
            current["title"] = text

    stories = []
    for item in by_url.values():
        title = item.get("title", "")
        # Image-only and tiny utility links are not useful RSS entries.
        if len(title) < 12:
            continue
        stories.append(item)
        if len(stories) >= MAX_ITEMS:
            break

    if not stories:
        raise RuntimeError("Reuters World page yielded no article links")
    return stories


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def article_metadata(story: dict) -> dict:
    result = dict(story)
    try:
        soup = BeautifulSoup(fetch(story["url"]), "html.parser")

        def meta(*, name: str | None = None, prop: str | None = None) -> str:
            attrs = {"name": name} if name else {"property": prop}
            node = soup.find("meta", attrs=attrs)
            return clean_text(node.get("content", "")) if node else ""

        headline = meta(prop="og:title") or meta(name="twitter:title")
        description = (
            meta(prop="og:description")
            or meta(name="description")
            or meta(name="twitter:description")
        )
        published = (
            meta(prop="article:published_time")
            or meta(name="article:published_time")
            or meta(name="date")
        )

        if headline:
            # Reuters sometimes appends " | Reuters" to page metadata.
            headline = re.sub(r"\s*\|\s*Reuters\s*$", "", headline, flags=re.I)
            result["title"] = headline
        result["description"] = trim(description)
        result["published"] = published or None
        result["published_dt"] = parse_datetime(published)
        result["status"] = "ok"
    except Exception as exc:  # keep the headline/link even if article enrichment fails
        result["description"] = ""
        result["published"] = None
        result["published_dt"] = None
        result["status"] = "metadata_error"
        result["error"] = str(exc)
    return result


def enrich(stories: list[dict]) -> list[dict]:
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(article_metadata, item): item["url"] for item in stories}
        for future in as_completed(futures):
            item = future.result()
            results[item["url"]] = item
    # Preserve Reuters' own World-page ordering instead of sorting by timestamps.
    return [results[item["url"]] for item in stories if item["url"] in results]


def build_rss(stories: list[dict]) -> None:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Reuters World — Mica"
    ET.SubElement(channel, "link").text = WORLD_URL
    ET.SubElement(channel, "description").text = (
        "Reuters World headlines in RSS form. Direct Reuters links; no Google, Reddit or proxy reader."
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
        ET.SubElement(item, "category").text = "World"
        source = ET.SubElement(item, "source", {"url": WORLD_URL})
        source.text = "Reuters"
        description = story.get("description") or "Open the original Reuters story for details."
        ET.SubElement(item, "description").text = f"Reuters • World\n\n{description}"

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT, encoding="utf-8", xml_declaration=True)


def main() -> int:
    debug = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": WORLD_URL,
        "max_items": MAX_ITEMS,
    }
    try:
        discovered = discover_world_stories()
        stories = enrich(discovered)
        build_rss(stories)
        debug["discovered_items"] = len(discovered)
        debug["final_items"] = len(stories)
        debug["metadata_errors"] = [
            {"title": s["title"], "url": s["url"], "error": s.get("error")}
            for s in stories
            if s.get("status") != "ok"
        ]
        debug["items"] = [
            {
                "title": s["title"],
                "url": s["url"],
                "published": s.get("published"),
                "status": s.get("status"),
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
