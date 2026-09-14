#!/usr/bin/env python3
"""Build Mica's curated car RSS feed.

AutoWeek is the main news source (already filtered separately). Other sources are
only allowed to contribute enthusiast/editorial material: classics, youngtimers,
owner cars, retrospectives, buying guides, history, maintenance and similar.
Routine news and EV-only content from those extra sources is intentionally
excluded.
"""

from __future__ import annotations

import calendar
import html
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import feedparser
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
AUTOWEEK_FEED = ROOT.parent / "autoweek" / "autoweek-filtered.xml"
OUTPUT = ROOT / "micas-autofeed.xml"
DEBUG_OUTPUT = ROOT / "curated-debug.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; MicasCuratedCarFeed/1.0; "
    "+https://github.com/MicaLovesKPOP/micas-space)"
)

# Extras are stricter than the AutoWeek core feed: if an extra article is
# clearly about an EV, it is omitted. AutoWeek remains responsible for any
# genuinely important EV industry news that is worth seeing.
EV_TERMS = [
    "elektrisch",
    "electric",
    "battery electric",
    "bev",
    "ev-only",
    "ev only",
    "actieradius",
    "rijbereik",
    "laadsnelheid",
    "snelladen",
    "laadpaal",
    "thuisladen",
    "wallbox",
    "tesla",
    "polestar",
    "rivian",
    "lucid",
    "zeekr",
    "xpeng",
    "leapmotor",
    "byd",
    "nio ",
    "e-tron",
    "e tron",
    "id.2",
    "id.3",
    "id.4",
    "id.5",
    "id.7",
    "ioniq 5",
    "ioniq 6",
    "ioniq 9",
    "inster",
    "ex30",
    "ex40",
    "ec40",
    "ev2",
    "ev3",
    "ev4",
    "ev5",
    "ev6",
    "ev9",
    "bmw ix",
    "ix1",
    "ix2",
    "ix3",
    "mercedes eq",
    "eqa",
    "eqb",
    "eqe",
    "eqs",
    "taycan",
    "macan electric",
    "cayenne electric",
]

# Obvious current-affairs/policy/auction-news signals. These are used only for
# extra sources where we want evergreen enthusiast material, not daily news.
NEWSISH_TERMS = [
    "kabinet",
    "tweede kamer",
    "eerste kamer",
    "motie",
    "regeling",
    "bijtelling",
    "belasting",
    "wegenbelasting",
    "wetgeving",
    "verbod",
    "subsidie",
    "accijns",
    "geveild voor",
    "veilingrecord",
    "recordbedrag",
    "duikt op na",
    "nieuw record",
    "verkoopcijfers",
    "marktaandeel",
    "fabriek sluit",
    "failliet",
    "recall",
    "terugroep",
]

AUTOBLOG_FEATURE_TERMS = [
    "#mijnauto",
    "mijn auto",
    "foto van de maand",
    "aankoopadvies",
    "autoblog garage",
    "terugblik",
    "moderne klassieker",
    "toekomstige klassieker",
    "klassieker?",
    "youngtimer voor",
    "oldtimer voor",
    "vergeten auto",
    "vergeten model",
    "hoe zat het ook alweer",
]

AUTOBLOG_FEATURE_TAGS = {
    "mijn auto",
    "foto van de maand",
    "youngtimers",
    "oldtimers",
}

AUTOVISIE_ALLOWED_TYPES = {
    "klassiekers",
    "youngtimers",
    "occasions",
    "occasion battle",
    "uw garage",
    "reportage",
    "sjoerds weetjes",
    "video",
    "extra",
}


@dataclass
class Item:
    title: str
    link: str
    guid: str
    summary: str
    source: str
    reason: str
    published: str | None = None
    sort_ts: float = 0.0


debug: dict = {
    "generated_at": None,
    "sources": [],
    "decisions": [],
    "duplicates": [],
}


def normalize(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def lower(value: str) -> str:
    return normalize(value).lower()


def has_ev_signal(text: str) -> tuple[bool, list[str]]:
    text_l = lower(text)
    hits = [term for term in EV_TERMS if term in text_l]
    if re.search(r"(?:^|\W)ev(?:$|\W)", text_l):
        hits.append("ev")
    return bool(hits), sorted(set(hits))


def entry_tags(entry) -> set[str]:
    result = set()
    for tag in entry.get("tags", []) or []:
        term = normalize(tag.get("term", ""))
        if term:
            result.add(term.lower())
    return result


def published_info(entry) -> tuple[str | None, float]:
    published = entry.get("published") or entry.get("updated")
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return published, float(calendar.timegm(parsed))
        except Exception:
            pass
    return published, 0.0


def short_summary(entry, limit: int = 450) -> str:
    value = normalize(entry.get("summary", "") or entry.get("description", ""))
    if len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()


def log_source(name: str, url: str, status: str, count: int = 0, error: str | None = None):
    row = {"name": name, "url": url, "status": status, "items": count}
    if error:
        row["error"] = error
    debug["sources"].append(row)


def log_decision(source: str, title: str, link: str, keep: bool, reason: str, details=None):
    row = {
        "source": source,
        "keep": keep,
        "reason": reason,
        "title": title,
        "link": link,
    }
    if details:
        row["details"] = details
    debug["decisions"].append(row)


def parse_feed(name: str, url: str):
    try:
        raw = fetch_bytes(url)
        parsed = feedparser.parse(raw)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(str(parsed.bozo_exception))
        log_source(name, url, "ok", len(parsed.entries))
        return parsed.entries
    except Exception as exc:
        log_source(name, url, "error", error=str(exc))
        print(f"{name}: {exc}", file=sys.stderr)
        return []


def core_autoweek_items() -> list[Item]:
    if not AUTOWEEK_FEED.exists():
        log_source("AutoWeek core", str(AUTOWEEK_FEED), "missing")
        return []

    parsed = feedparser.parse(AUTOWEEK_FEED.read_bytes())
    result = []
    for entry in parsed.entries:
        published, ts = published_info(entry)
        result.append(
            Item(
                title=normalize(entry.get("title", "")),
                link=entry.get("link", ""),
                guid=entry.get("id") or entry.get("link", "") or entry.get("title", ""),
                summary=short_summary(entry),
                source="AutoWeek",
                reason="gefilterd hoofdnieuws",
                published=published,
                sort_ts=ts,
            )
        )
    log_source("AutoWeek core", str(AUTOWEEK_FEED), "ok", len(result))
    return result


def autoblog_items() -> list[Item]:
    name = "Autoblog"
    url = "https://www.autoblog.nl/feed/news.xml"
    result = []

    for entry in parse_feed(name, url):
        title = normalize(entry.get("title", ""))
        summary = short_summary(entry)
        text = f"{title} {summary}"
        tags = entry_tags(entry)
        ev, ev_hits = has_ev_signal(text)

        if ev:
            log_decision(name, title, entry.get("link", ""), False, "EV-extra", {"ev": ev_hits})
            continue

        text_l = lower(text)
        news_hits = [term for term in NEWSISH_TERMS if term in text_l]
        feature_hits = [term for term in AUTOBLOG_FEATURE_TERMS if term in text_l]
        tag_hits = sorted(tags & AUTOBLOG_FEATURE_TAGS)

        # A year-based retrospective is useful even if the word "klassieker"
        # is absent, e.g. "25 jaar MINI".
        anniversary = bool(
            re.search(r"\b(?:20|25|30|35|40|45|50|60|70|75|80|90|100)\s+jaar\b", text_l)
        )

        # Youngtimer/oldtimer tags by themselves can contain daily policy/news
        # posts, so require either no news signal plus some enthusiast context,
        # or one of the strong recurring feature markers above.
        enthusiast_context = any(
            term in text_l
            for term in (
                "klassieker",
                "youngtimer",
                "oldtimer",
                "restomod",
                "historie",
                "geschiedenis",
                "icoon",
                "iconisch",
                "uit de jaren",
                "jaren 80",
                "jaren 90",
                "jaren '80",
                "jaren '90",
            )
        )

        keep = bool(feature_hits or anniversary or (tag_hits and enthusiast_context and not news_hits))
        if not keep:
            log_decision(
                name,
                title,
                entry.get("link", ""),
                False,
                "geen unieke Autoblog-feature",
                {"feature": feature_hits, "tags": tag_hits, "news": news_hits},
            )
            continue

        if news_hits and not (feature_hits or anniversary):
            log_decision(
                name,
                title,
                entry.get("link", ""),
                False,
                "dagelijks/politiek nieuws",
                {"news": news_hits},
            )
            continue

        reason_bits = feature_hits[:1] or tag_hits[:1] or (["jubileum/terugblik"] if anniversary else [])
        reason = "Autoblog " + (reason_bits[0] if reason_bits else "liefhebbersfeature")
        published, ts = published_info(entry)
        item = Item(
            title=title,
            link=entry.get("link", ""),
            guid=entry.get("id") or entry.get("link", "") or title,
            summary=summary,
            source=name,
            reason=reason,
            published=published,
            sort_ts=ts,
        )
        result.append(item)
        log_decision(name, title, item.link, True, reason)

    return result


def autovisie_items() -> list[Item]:
    feeds = [
        ("Autovisie Klassiekers", "https://www.autovisie.nl/klassiekers/feed/"),
        ("Autovisie Youngtimers", "https://www.autovisie.nl/youngtimers/feed/"),
        ("Autovisie Uw Garage", "https://www.autovisie.nl/video/uw-garage/feed/"),
        ("Autovisie Sjoerds Weetjes", "https://www.autovisie.nl/video/sjoerds-weetjes/feed/"),
        ("Autovisie Occasion Battle", "https://www.autovisie.nl/video/occasion-battle/feed/"),
    ]
    result = []

    for name, url in feeds:
        for entry in parse_feed(name, url):
            title = normalize(entry.get("title", ""))
            summary = short_summary(entry)
            text = f"{title} {summary}"
            tags = entry_tags(entry)
            ev, ev_hits = has_ev_signal(text)

            if ev:
                log_decision(name, title, entry.get("link", ""), False, "EV-extra", {"ev": ev_hits})
                continue

            if "nieuws" in tags or "news" in tags:
                log_decision(name, title, entry.get("link", ""), False, "Autovisie-nieuws", {"tags": sorted(tags)})
                continue

            news_hits = [term for term in NEWSISH_TERMS if term in lower(text)]
            if news_hits:
                log_decision(
                    name,
                    title,
                    entry.get("link", ""),
                    False,
                    "dagelijks/politiek/veilingnieuws",
                    {"news": news_hits},
                )
                continue

            type_hits = sorted(tags & AUTOVISIE_ALLOWED_TYPES)
            # The dedicated Uw Garage / Sjoerds / Occasion Battle feeds are
            # already feature-only even if WordPress omits the category tag.
            dedicated = any(
                marker in name
                for marker in ("Uw Garage", "Sjoerds Weetjes", "Occasion Battle")
            )
            if not type_hits and not dedicated:
                log_decision(
                    name,
                    title,
                    entry.get("link", ""),
                    False,
                    "onduidelijk contenttype",
                    {"tags": sorted(tags)},
                )
                continue

            reason = type_hits[0] if type_hits else name.replace("Autovisie ", "")
            published, ts = published_info(entry)
            item = Item(
                title=title,
                link=entry.get("link", ""),
                guid=entry.get("id") or entry.get("link", "") or title,
                summary=summary,
                source="Autovisie",
                reason=reason,
                published=published,
                sort_ts=ts,
            )
            result.append(item)
            log_decision(name, title, item.link, True, reason)

    return result


def anchor_title(anchor) -> str:
    heading = anchor.find(["h1", "h2", "h3", "h4", "h5"])
    if heading:
        return normalize(heading.get_text(" ", strip=True))
    text = normalize(anchor.get_text(" ", strip=True))
    # Avoid swallowing a whole card including long teaser/byline text.
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0] + "…"
    return text


def scrape_listing(
    name: str,
    url: str,
    host_suffix: str,
    accept: Callable[[str, str], bool],
    reason: str,
    max_items: int = 20,
) -> list[Item]:
    try:
        raw = fetch_bytes(url)
        soup = BeautifulSoup(raw, "html.parser")
    except Exception as exc:
        log_source(name, url, "error", error=str(exc))
        print(f"{name}: {exc}", file=sys.stderr)
        return []

    seen = set()
    result = []
    now = datetime.now(timezone.utc).timestamp()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor.get("href", ""))
        parsed = urlparse(href)
        if not parsed.hostname or not parsed.hostname.endswith(host_suffix):
            continue
        href = href.split("#", 1)[0]
        if href in seen:
            continue

        title = anchor_title(anchor)
        if len(title) < 8 or not accept(title, href):
            continue
        seen.add(href)

        ev, ev_hits = has_ev_signal(title)
        if ev:
            log_decision(name, title, href, False, "EV-extra", {"ev": ev_hits})
            continue

        item = Item(
            title=title,
            link=href,
            guid=href,
            summary="",
            source=name,
            reason=reason,
            published=None,
            # Keep page order stable without publishing a fake date.
            sort_ts=now - len(result),
        )
        result.append(item)
        log_decision(name, title, href, True, reason)
        if len(result) >= max_items:
            break

    log_source(name, url, "ok", len(result))
    return result


def pistonheads_items() -> list[Item]:
    sources = [
        (
            "PistonHeads PH Heroes",
            "https://www.pistonheads.com/news/heroes",
            lambda t, u: "ph heroes" in lower(t) or "features-heroes" in u,
            "PH Heroes / terugblik",
        ),
        (
            "PistonHeads Buying Guides",
            "https://www.pistonheads.com/news/guides",
            lambda t, u: "buying guide" in lower(t) or "buying-guides" in u,
            "Used Buying Guide",
        ),
        (
            "PistonHeads Six of the Best",
            "https://www.pistonheads.com/news/six-of-the-best",
            lambda t, u: "six of the best" in lower(t) or "six-of-the-best" in u,
            "Six of the Best",
        ),
        (
            "PistonHeads Shed of the Week",
            "https://www.pistonheads.com/news/shed-of-the-week",
            lambda t, u: "shed of the week" in lower(t),
            "Shed of the Week",
        ),
        (
            "PistonHeads Spotted",
            "https://www.pistonheads.com/news/spotted",
            lambda t, u: (
                "spotted" in lower(t)
                or "brave pill" in lower(t)
                or "auction block" in lower(t)
                or "spottedykywt" in u
            ),
            "Spotted / Brave Pill",
        ),
    ]

    result = []
    for name, url, accept, reason in sources:
        result.extend(scrape_listing(name, url, "pistonheads.com", accept, reason, max_items=16))
    return result


def hagerty_items() -> list[Item]:
    # Hagerty occasionally blocks automated requests. Every source is soft-fail:
    # if it refuses a run, the rest of the combined feed is still generated.
    sources = [
        (
            "Hagerty Automotive History",
            "https://www.hagerty.com/media/category/automotive-history/",
            lambda t, u: "/media/automotive-history/" in u,
            "automotive history",
        ),
        (
            "Hagerty Maintenance & Tech",
            "https://www.hagerty.com/media/category/maintenance-and-tech/",
            lambda t, u: "/media/" in u and "/category/" not in u,
            "maintenance & tech",
        ),
        (
            "Hagerty Buyer's Guides",
            "https://www.hagerty.com/media/tags/buyers-guide/",
            lambda t, u: "buyer" in lower(t) and "guide" in lower(t),
            "classic buyer's guide",
        ),
        (
            "Hagerty Market Trends",
            "https://www.hagerty.com/media/tags/market-trends/",
            lambda t, u: "/media/market-trends/" in u,
            "collector-car market",
        ),
    ]

    result = []
    for name, url, accept, reason in sources:
        result.extend(scrape_listing(name, url, "hagerty.com", accept, reason, max_items=12))
    return result


def title_tokens(title: str) -> set[str]:
    text = lower(title)
    text = re.sub(r"#\w+", " ", text)
    text = re.sub(r"\b(?:ph heroes|six of the best|shed of the week|used buying guide)\b", " ", text)
    words = re.findall(r"[a-z0-9à-ÿ]+", text)
    stop = {
        "de", "het", "een", "en", "van", "voor", "met", "op", "in", "is", "dit",
        "deze", "the", "a", "an", "of", "and", "for", "with", "to", "on", "this",
        "that", "car", "auto",
    }
    return {w for w in words if len(w) > 2 and w not in stop}


def similar_titles(a: str, b: str) -> bool:
    ta = title_tokens(a)
    tb = title_tokens(b)
    if len(ta) < 3 or len(tb) < 3:
        return False
    overlap = len(ta & tb)
    union = len(ta | tb)
    return overlap >= 3 and union > 0 and overlap / union >= 0.72


def dedupe(items: list[Item]) -> list[Item]:
    # AutoWeek is intentionally first: if a rare duplicate slips in from an
    # extra source, retain the core item and discard the extra.
    source_rank = {
        "AutoWeek": 0,
        "Autoblog": 1,
        "Autovisie": 2,
    }
    ordered = sorted(
        items,
        key=lambda item: (
            source_rank.get(item.source, 3),
            -item.sort_ts,
            lower(item.title),
        ),
    )

    kept: list[Item] = []
    seen_guids = set()
    for item in ordered:
        if item.guid in seen_guids:
            continue
        duplicate_of = next((other for other in kept if similar_titles(item.title, other.title)), None)
        if duplicate_of:
            debug["duplicates"].append(
                {
                    "dropped_source": item.source,
                    "dropped_title": item.title,
                    "kept_source": duplicate_of.source,
                    "kept_title": duplicate_of.title,
                }
            )
            continue
        seen_guids.add(item.guid)
        kept.append(item)

    return sorted(kept, key=lambda item: item.sort_ts, reverse=True)


def add_text(parent, tag: str, value: str | None, attrs=None):
    if value:
        ET.SubElement(parent, tag, attrs or {}).text = str(value)


def build_feed(items: list[Item]) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", "Mica's Autonieuws — liefhebberseditie")
    add_text(channel, "link", "https://github.com/MicaLovesKPOP/micas-space")
    add_text(
        channel,
        "description",
        "Gefilterd AutoWeek-nieuws plus alleen unieke liefhebbersfeatures van andere bronnen: "
        "klassiekers, youngtimers, eigenaren, historie, koopgidsen en techniek. "
        "Geen gewone duplicaatnieuwsstroom en geen EV-features.",
    )
    add_text(channel, "language", "nl-NL")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    add_text(channel, "generator", "MicasCuratedCarFeed")

    for item in items[:120]:
        node = ET.SubElement(channel, "item")
        add_text(node, "title", item.title)
        add_text(node, "link", item.link)
        guid = ET.SubElement(node, "guid", {"isPermaLink": "false"})
        guid.text = item.guid
        add_text(node, "pubDate", item.published)
        add_text(node, "category", item.reason)
        add_text(node, "source", item.source, {"url": item.link})

        desc = f"{item.source} • {item.reason}"
        if item.summary:
            desc += f"\n\n{item.summary}"
        add_text(node, "description", desc)

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    all_items: list[Item] = []
    all_items.extend(core_autoweek_items())
    all_items.extend(autoblog_items())
    all_items.extend(autovisie_items())
    all_items.extend(pistonheads_items())
    all_items.extend(hagerty_items())

    curated = dedupe(all_items)
    OUTPUT.write_bytes(build_feed(curated))

    debug["generated_at"] = datetime.now(timezone.utc).isoformat()
    debug["input_items"] = len(all_items)
    debug["output_items"] = len(curated)
    DEBUG_OUTPUT.write_text(
        json.dumps(debug, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Curated feed: {len(all_items)} input -> {len(curated)} output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
