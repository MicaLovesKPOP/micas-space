#!/usr/bin/env python3
"""Build Mica's K-pop changelog RSS feed.

This feed is deliberately *not* a celebrity/gossip feed. It only keeps concrete
changes: debuts, meaningful comeback/release announcements, contract/agency
changes, legal disputes/rulings, group/member status changes and major K-pop
industry moves. Reddit is not used as a source or intermediary.
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
from difflib import SequenceMatcher
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import feedparser
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "micas-kpop-feed.xml"
DEBUG_OUTPUT = ROOT / "filter-debug.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; MicasKpopChangelog/1.0; "
    "+https://github.com/MicaLovesKPOP/micas-space)"
)

# Sources are intentionally direct publishers. No Reddit, aggregators or gossip
# sites are used. Soompi is useful for release/agency statements; Korean news
# sources and MBW are preferred for legal/business developments.
SOURCES = {
    "Korea Herald": {"kind": "rss", "url": "https://www.koreaherald.com/rss/kh_Kpop"},
    "Music Business Worldwide": {"kind": "rss", "url": "https://www.musicbusinessworldwide.com/feed/"},
    "Soompi Music": {"kind": "html", "url": "https://www.soompi.com/category/music", "host": "soompi.com"},
    "Soompi Celeb": {"kind": "html", "url": "https://www.soompi.com/category/celeb", "host": "soompi.com"},
    "Yonhap K-pop": {"kind": "html", "url": "https://en.yna.co.kr/culture/k-pop", "host": "en.yna.co.kr"},
}

# MBW is a global music-industry feed, so it needs an explicit Korean/K-pop
# context check. The other sources are already K-pop-specific enough.
MBW_KPOP_CONTEXT = [
    "k-pop", "kpop", "south korea", "korean music", "korean entertainment",
    "hybe", "ador", "belift", "source music", "pledis", "koz entertainment",
    "sm entertainment", "yg entertainment", "jyp entertainment", "starship",
    "cube entertainment", "attrakt", "wakeone", "modhaus", "rbw", "fnc entertainment",
    "newjeans", "fifty fifty", "bts", "blackpink", "aespa", "ive", "illit",
    "le sserafim", "twice", "stray kids", "seventeen", "enhypen", "txt",
]

# Strong whitelist signals. An article must match one of these event families.
EVENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("Debut / new group", [
        r"\bdebut(?:s|ed|ing)?\b", r"\bpre[- ]?debut\b", r"\bnew girl group\b",
        r"\bnew boy group\b", r"\bnew group\b", r"\bdebut lineup\b",
        r"\blaunch(?:es|ing)? .*group\b",
    ]),
    ("Comeback / release", [
        r"\bcomeback\b", r"\breturns? with\b", r"\bset to return\b",
        r"\bconfirms? .*return\b", r"\bannounces? .*album\b",
        r"\bannounces? .*single\b", r"\bnew (?:full[- ]length )?album\b",
        r"\bnew mini album\b", r"\bnew ep\b", r"\bset to release\b",
        r"\brelease date\b", r"\bdrops? .*album\b", r"\breleases? .*album\b",
        r"\breleases? .*single\b",
    ]),
    ("Contract / agency", [
        r"\bexclusive contract\b", r"\bcontract dispute\b", r"\bcontract termination\b",
        r"\bterminates? .*contract\b", r"\bends? .*contract\b", r"\brenews? .*contract\b",
        r"\bcontract renewal\b", r"\bsigns? with .*agency\b", r"\bsigned with .*agency\b",
        r"\bnew agency\b", r"\bjoins? .*agency\b", r"\bleaves? .*agency\b",
        r"\bparts ways with\b", r"\bmanagement contract\b", r"\btransfer(?:s|red)? to\b",
        r"\bchanges? agencies\b",
    ]),
    ("Legal / dispute", [
        r"\bcourt\b", r"\blawsuit\b", r"\bsues?\b", r"\bsued\b", r"\binjunction\b",
        r"\bappeal\b", r"\bruling\b", r"\blegal action\b", r"\blegal dispute\b",
        r"\binvestigation\b", r"\bprosecutors?\b", r"\bcomplaint\b", r"\bregulator\b",
        r"\bfair trade commission\b", r"\bkftc\b", r"\bftc\b",
    ]),
    ("Group / member status", [
        r"\bdisbands?\b", r"\bdisbandment\b", r"\bhiatus\b", r"\bhalts? activities\b",
        r"\bsuspends? activities\b", r"\bresumes? activities\b", r"\breturns? to activities\b",
        r"\bleaves? (?:the )?group\b", r"\bdeparts? (?:from )?(?:the )?group\b",
        r"\bmember departure\b", r"\bjoins? (?:the )?group\b", r"\blineup change\b",
        r"\bpromote as [0-9]+[- ]member\b", r"\btemporarily halts?\b",
    ]),
    ("Industry / label", [
        r"\bacquisition\b", r"\bacquires?\b", r"\bmerger\b", r"\bmerges? with\b",
        r"\bnew subsidiary\b", r"\blaunches? .*label\b", r"\blaunches? .*agency\b",
        r"\brestructur(?:e|es|ing)\b", r"\bappoints? .*ceo\b", r"\bnew ceo\b",
        r"\bdistribution deal\b", r"\bmanagement deal\b",
    ]),
]

# These topics are precisely the celebrity-news noise this feed is meant to avoid.
GOSSIP_DROP = [
    "dating", "relationship rumor", "dating rumor", "spotted with", "seen with",
    "male idol", "female idol", "airport fashion", "airport look", "outfit",
    "fashion", "luxury bag", "handbag", "purse", "jewelry", "jewellery",
    "mansion", "apartment", "house purchase", "real estate", "property purchase",
    "donation", "donates", "donated", "charity", "netizens react", "netizens debate",
    "netizens discuss", "stuns in", "gorgeous", "visuals", "instagram", "selfie",
    "brand ambassador", "global ambassador", "endorsement", "ad campaign", "pictorial",
    "magazine cover", "birthday", "wealth", "net worth", "richest", "expensive car",
]

# Routine fandom/PR churn that is not a meaningful change.
NOISE_DROP = [
    "music chart", "weekly chart", "billboard chart", "world albums chart", "circle chart",
    "brand reputation", "takes 1st win", "takes 2nd win", "takes 3rd win", "music show win",
    "million views", "billion views", "sales record", "first-week sales", "pre-order record",
    "award lineup", "red carpet", "fan meeting", "fanmeeting", "tour dates", "tour stops",
    "concert tour", "festival lineup", "performance video", "dance practice",
]

# Teaser spam is excluded unless the title also contains one of the strong
# announcement phrases below.
TEASER_DROP = [
    "teaser", "concept photo", "concept image", "highlight medley", "track list",
    "tracklist", "scheduler", "schedule poster", "preview", "mood sampler",
]
TEASER_KEEP = [
    "confirms comeback", "announces comeback", "sets comeback", "comeback date",
    "release date", "set to debut", "debut date",
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "with", "for", "of", "in", "on", "at",
    "as", "from", "after", "amid", "over", "new", "kpop", "k", "pop", "group",
    "agency", "entertainment", "announces", "confirms", "report", "reports",
}

SOURCE_BASE_PRIORITY = {
    "Yonhap K-pop": 100,
    "Korea Herald": 95,
    "Music Business Worldwide": 90,
    "Soompi Music": 80,
    "Soompi Celeb": 80,
}


@dataclass
class Item:
    title: str
    link: str
    source: str
    summary: str
    category: str
    published: str | None = None
    sort_ts: float = 0.0


def normalize(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def lower(value: str) -> str:
    return normalize(value).lower()


def trim(value: str, limit: int = 760) -> str:
    value = normalize(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rsplit(" ", 1)[0] + "…"


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


def published_info(entry) -> tuple[str | None, float]:
    published = entry.get("published") or entry.get("updated")
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return published, float(calendar.timegm(parsed))
        except Exception:
            pass
    return published, 0.0


def classify(title: str, summary: str, source: str) -> tuple[str | None, str]:
    text = lower(f"{title} {summary}")

    if source == "Music Business Worldwide" and not any(term in text for term in MBW_KPOP_CONTEXT):
        return None, "MBW: no Korean/K-pop context"

    gossip = [term for term in GOSSIP_DROP if term in text]
    if gossip:
        return None, "celebrity/gossip noise: " + ", ".join(gossip[:3])

    noise = [term for term in NOISE_DROP if term in text]
    if noise:
        return None, "routine fandom/PR noise: " + ", ".join(noise[:3])

    teaser = [term for term in TEASER_DROP if term in text]
    if teaser and not any(term in text for term in TEASER_KEEP):
        return None, "teaser/rollout post"

    for category, patterns in EVENT_PATTERNS:
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            return category, "whitelisted event"

    return None, "no meaningful-change event matched"


def article_meta(url: str) -> tuple[str, str | None, float]:
    """Fetch a useful excerpt/date for HTML-listing sources. Best-effort only."""
    try:
        soup = BeautifulSoup(fetch_bytes(url), "html.parser")
    except Exception:
        return "", None, 0.0

    desc = ""
    for attrs in (
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            desc = trim(node.get("content", ""))
            break

    published = None
    ts = 0.0
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"name": "date"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            published = node.get("content")
            try:
                ts = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
            break
    return desc, published, ts


def rss_items(name: str, url: str, debug: dict) -> list[Item]:
    try:
        parsed = feedparser.parse(fetch_bytes(url))
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(str(parsed.bozo_exception))
    except Exception as exc:
        debug["sources"].append({"name": name, "url": url, "status": "error", "error": str(exc)})
        return []

    debug["sources"].append({"name": name, "url": url, "status": "ok", "items": len(parsed.entries)})
    result = []
    for entry in parsed.entries[:60]:
        title = normalize(entry.get("title", ""))
        link = entry.get("link", "")
        summary = trim(entry.get("summary", "") or entry.get("description", ""))
        category, reason = classify(title, summary, name)
        debug["decisions"].append({"source": name, "title": title, "link": link, "keep": bool(category), "category": category, "reason": reason})
        if not category:
            continue
        published, ts = published_info(entry)
        result.append(Item(title, link, name, summary, category, published, ts))
    return result


def html_listing_items(name: str, url: str, host: str, debug: dict) -> list[Item]:
    try:
        soup = BeautifulSoup(fetch_bytes(url), "html.parser")
    except Exception as exc:
        debug["sources"].append({"name": name, "url": url, "status": "error", "error": str(exc)})
        return []

    links: list[tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a.get("href", "")).split("#", 1)[0]
        parsed = urlparse(href)
        if parsed.hostname != host and not (parsed.hostname and parsed.hostname.endswith("." + host)):
            continue

        # Keep only actual article shapes for these sites.
        if name.startswith("Soompi"):
            if "/article/" not in parsed.path:
                continue
        elif name == "Yonhap K-pop":
            if "/view/AEN" not in parsed.path:
                continue

        title = normalize(a.get_text(" ", strip=True))
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        links.append((title, href))
        if len(links) >= 45:
            break

    debug["sources"].append({"name": name, "url": url, "status": "ok", "items": len(links)})
    result = []
    for title, link in links:
        # First classify by title to avoid fetching every celebrity-fluff page.
        category, reason = classify(title, "", name)
        if not category:
            debug["decisions"].append({"source": name, "title": title, "link": link, "keep": False, "category": None, "reason": reason})
            continue

        summary, published, ts = article_meta(link)
        # Reclassify with the actual article description; this catches gossip/noise
        # that had an ambiguous headline.
        category2, reason2 = classify(title, summary, name)
        keep = bool(category2)
        debug["decisions"].append({"source": name, "title": title, "link": link, "keep": keep, "category": category2, "reason": reason2})
        if keep:
            result.append(Item(title, link, name, summary, category2, published, ts))
    return result


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", lower(title))
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def duplicates(a: Item, b: Item) -> bool:
    if a.category != b.category:
        return False
    ta, tb = title_tokens(a.title), title_tokens(b.title)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, lower(a.title), lower(b.title)).ratio()
    return jaccard >= 0.48 or seq >= 0.72


def source_priority(item: Item) -> int:
    base = SOURCE_BASE_PRIORITY.get(item.source, 50)
    # Soompi is particularly useful for official comeback/debut announcements.
    if item.category in {"Debut / new group", "Comeback / release", "Group / member status"} and item.source.startswith("Soompi"):
        return base + 25
    # Korean news outlets are preferred for court/legal developments.
    if item.category in {"Legal / dispute", "Contract / agency"} and item.source in {"Yonhap K-pop", "Korea Herald"}:
        return base + 20
    return base


def dedupe(items: list[Item], debug: dict) -> list[Item]:
    # Consider higher-quality sources first, then more recent items.
    ranked = sorted(items, key=lambda x: (source_priority(x), x.sort_ts), reverse=True)
    kept: list[Item] = []
    for item in ranked:
        match = next((existing for existing in kept if duplicates(item, existing)), None)
        if match:
            debug["duplicates"].append({
                "dropped": item.title,
                "dropped_source": item.source,
                "kept": match.title,
                "kept_source": match.source,
                "category": item.category,
            })
            continue
        kept.append(item)
    return sorted(kept, key=lambda x: x.sort_ts, reverse=True)


def add_text(parent, tag: str, value: str | None, attrs: dict | None = None):
    if value:
        ET.SubElement(parent, tag, attrs or {}).text = str(value)


def build_feed(items: list[Item]) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", "Mica's K-pop Changelog")
    add_text(channel, "link", "https://github.com/MicaLovesKPOP/micas-space")
    add_text(
        channel,
        "description",
        "Alleen betekenisvolle K-pop-veranderingen: debuts, comebacks/releases, contracten/agencies, juridische zaken, groepsstatus en belangrijke labelontwikkelingen. Geen gossip, lifestyle, dating, donaties, luxe-aankopen, charts of teaser-spam. Geen Reddit.",
    )
    add_text(channel, "language", "en")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    add_text(channel, "generator", "MicasKpopChangelog")

    for item in items[:120]:
        node = ET.SubElement(channel, "item")
        add_text(node, "title", item.title)
        add_text(node, "link", item.link)
        add_text(node, "guid", item.link, {"isPermaLink": "false"})
        add_text(node, "pubDate", item.published)
        add_text(node, "category", item.category)
        add_text(node, "source", item.source, {"url": item.link})

        description = f"{item.source} • {item.category}"
        if item.summary:
            description += "\n\n" + item.summary
        add_text(node, "description", description)

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    debug = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [],
        "decisions": [],
        "duplicates": [],
    }

    candidates: list[Item] = []
    for name, cfg in SOURCES.items():
        if cfg["kind"] == "rss":
            candidates.extend(rss_items(name, cfg["url"], debug))
        else:
            candidates.extend(html_listing_items(name, cfg["url"], cfg["host"], debug))

    final = dedupe(candidates, debug)
    OUTPUT.write_bytes(build_feed(final))
    debug["candidate_items"] = len(candidates)
    debug["final_items"] = len(final)
    DEBUG_OUTPUT.write_text(json.dumps(debug, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"K-pop candidates: {len(candidates)} | final after dedupe: {len(final)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
