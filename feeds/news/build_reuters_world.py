#!/usr/bin/env python3
"""Build a curated, stable Reuters World RSS feed from official sitemap metadata.

Only headline, original URL and publication date are fetched, not article bodies.
See README.md for selection policy, limitations and reader-cache migration notes.
"""
from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from world_selection import POLICY_VERSION, FEED_HOURS, select

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reuters-world.xml"  # Keep existing subscriptions working.
DEBUG_OUTPUT = ROOT / "reuters-world-debug.json"
STATE_OUTPUT = ROOT / "reuters-world-state.json"
WORLD_URL = "https://www.reuters.com/world/"
NEWS_SITEMAP_INDEX = "https://www.reuters.com/arc/outboundfeeds/news-sitemap-index/?outputType=xml"
MAX_CHILD_SITEMAPS = 24
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
USER_AGENT = "MicasReutersWorldFeed/2.0 (+https://github.com/MicaLovesKPOP/micas-space)"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
ARTICLE_PATH = re.compile(r"^/world/(?:[^/?#]+/)*[^/?#]+-\d{4}-\d{2}-\d{2}/?$")


def is_reuters_url(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and p.hostname in {"reuters.com", "www.reuters.com"} and not p.username


def fetch(url: str) -> bytes:
    if not is_reuters_url(url):
        raise ValueError("Only HTTPS Reuters sitemap URLs may be fetched")
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=20) as response:
        if not is_reuters_url(response.url):
            raise ValueError("Unexpected sitemap redirect outside Reuters")
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Sitemap exceeded safe response size")
    return data


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
    except (ValueError, AttributeError):
        return None


def canonical_reuters_url(url: str) -> str:
    if not is_reuters_url(url):
        raise ValueError("Not a Reuters HTTPS URL")
    p = urlsplit(url)
    return urlunsplit(("https", "www.reuters.com", p.path.rstrip("/") + "/", "", ""))


def child_sitemaps(index_xml: bytes) -> list[str]:
    root = ET.fromstring(index_xml)
    entries = []
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    for i, sitemap in enumerate(root.findall("{*}sitemap")):
        loc = text(sitemap.find("{*}loc"))
        if is_reuters_url(loc):
            entries.append((parse_dt(text(sitemap.find("{*}lastmod"))) or minimum, -i, loc))
    if not entries:
        return list(dict.fromkeys(text(n) for n in root.findall(".//{*}loc")
                                  if is_reuters_url(text(n))))[:MAX_CHILD_SITEMAPS]
    entries.sort(reverse=True)
    return list(dict.fromkeys(e[2] for e in entries))[:MAX_CHILD_SITEMAPS]


def region_from_path(path: str) -> str:
    bits = path.strip("/").split("/")
    return bits[1].replace("-", " ").title() if len(bits) > 2 else "World"


def parse_news_sitemap(xml_data: bytes) -> list[dict]:
    root = ET.fromstring(xml_data)
    items = []
    for url_node in root.findall("{*}url"):
        loc = text(url_node.find("{*}loc"))
        if not is_reuters_url(loc) or not ARTICLE_PATH.match(urlsplit(loc).path):
            continue
        news = url_node.find(f"{{{NEWS_NS}}}news")
        if news is None:
            news = url_node.find("{*}news")
        if news is None:
            continue
        title = text(news.find("{*}title"))
        published = text(news.find("{*}publication_date"))
        if title:
            items.append({"title": title, "url": canonical_reuters_url(loc),
                          "published_dt": parse_dt(published),
                          "region": region_from_path(urlsplit(loc).path)})
    return items


def discover() -> tuple[list[dict], dict]:
    children = child_sitemaps(fetch(NEWS_SITEMAP_INDEX))
    debug = {"child_sitemaps_found": len(children), "child_sitemaps_checked": []}
    by_url = {}
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    for child in children:
        detail = {"url": child}
        try:
            rows = parse_news_sitemap(fetch(child))
            detail["world_items"] = len(rows)
            for item in rows:
                current = by_url.get(item["url"])
                if current is None or (item["published_dt"] or minimum) > (current["published_dt"] or minimum):
                    by_url[item["url"]] = item
        except Exception as exc:
            detail["error"] = str(exc)
        debug["child_sitemaps_checked"].append(detail)
    # Crucially: no newest-30 truncation BEFORE relevance selection. Inspect every
    # discovered candidate within the existing bounded sitemap request budget.
    return list(by_url.values()), debug


def load_history() -> list[dict]:
    if STATE_OUTPUT.exists():
        payload = json.loads(STATE_OUTPUT.read_text(encoding="utf-8"))
        if payload.get("version") != POLICY_VERSION or not isinstance(payload.get("items"), list):
            raise ValueError("Unsupported or corrupt Reuters state; refusing to reset publication history")
        history = []
        for raw in payload["items"]:
            s = dict(raw)
            s["published_dt"] = parse_dt(s.pop("published", ""))
            if not s["published_dt"] or not s.get("title") or not is_reuters_url(s.get("url", "")):
                raise ValueError("Invalid entry in Reuters publication history")
            history.append(s)
        return history
    # One-time migration: re-filter the old RSS, retaining original URLs/dates.
    # Old unwanted entries are NOT grandfathered into the curated feed.
    if not OUTPUT.exists():
        return []
    history = []
    for item in ET.parse(OUTPUT).getroot().findall("channel/item"):
        url, title = text(item.find("link")), text(item.find("title"))
        date = text(item.find("pubDate"))
        if not is_reuters_url(url) or not title or not date:
            continue
        try:
            dt = parsedate_to_datetime(date)
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        history.append({"url": canonical_reuters_url(url), "title": title,
                        "published_dt": dt, "region": text(item.find("category")) or "World"})
    return history


def rss_bytes(stories: list[dict], now: datetime) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Reuters World — Mica"
    ET.SubElement(channel, "link").text = WORLD_URL
    ET.SubElement(channel, "description").text = (
        "Consequential world developments, not the full Reuters wire. "
        "Headline-based selection; routine market news, commentary and repeated angles filtered. "
        "Original Reuters links; no Google News, Reddit or proxy reader.")
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now, usegmt=True)
    ET.SubElement(channel, "generator").text = "MicasReutersWorldFeed/2.0"
    for story in stories:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = story["title"]
        ET.SubElement(item, "link").text = story["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = story["url"]
        ET.SubElement(item, "pubDate").text = format_datetime(story["published_dt"], usegmt=True)
        ET.SubElement(item, "category").text = story.get("region") or "World"
        ET.SubElement(item, "source", {"url": WORLD_URL}).text = "Reuters"
        ET.SubElement(item, "description").text = (
            f"Reuters • World / {story.get('region', 'World')}\n\n"
            "Selected from Reuters' official headline metadata. "
            "Open the original Reuters story for the article.")
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def serialize(story: dict) -> dict:
    return {**{k: v for k, v in story.items() if k != "published_dt"},
            "published": story["published_dt"].isoformat()}


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    now = datetime.now(timezone.utc)
    debug = {"generated_at": now.isoformat(), "source": NEWS_SITEMAP_INDEX,
             "policy_version": POLICY_VERSION, "feed_hours": FEED_HOURS,
             "selection_basis": "headline_metadata_only", "daily_quota": None}
    try:
        stories, discovery_debug = discover()
        debug.update(discovery_debug)
        if not stories:
            raise RuntimeError("Reuters sitemaps yielded no /world/ articles; preserving the last good feed")
        current, history, audit = select(stories, load_history(), now)
        debug.update(candidates=len(stories), final_items=len(current),
                     kept_decisions=sum(a["kept"] for a in audit),
                     rejected_reasons=dict(Counter(a["reason"] for a in audit if not a["kept"])),
                     items=[serialize(s) for s in current], decisions=audit)
        # Zero qualifying new stories is a valid result. Never refill with noise.
        rss = rss_bytes(current, now)
        state = json_bytes({"version": POLICY_VERSION, "items": [serialize(s) for s in history]})
        atomic_write(OUTPUT, rss)
        atomic_write(STATE_OUTPUT, state)
        atomic_write(DEBUG_OUTPUT, json_bytes(debug))
    except Exception as exc:
        debug["fatal_error"] = str(exc)
        atomic_write(DEBUG_OUTPUT, json_bytes(debug))
        print(f"Reuters feed build failed: {exc}")
        return 1
    print(f"Examined {len(stories)} candidates; RSS retains {len(current)} selected stories over {FEED_HOURS}h.")
    print("Rejections:", json.dumps(debug["rejected_reasons"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
