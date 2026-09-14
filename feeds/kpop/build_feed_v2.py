#!/usr/bin/env python3
"""Build a low-noise K-pop changelog RSS feed for Inoreader.

The feed is about *changes*, not celebrity coverage: debuts, meaningful comeback
or release announcements, contract/agency moves, important legal/business
updates, group/member status changes and major label developments.

Reddit is intentionally not used as a source or intermediary.
"""

from __future__ import annotations

import calendar
import html
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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
    "Mozilla/5.0 (compatible; MicasKpopChangelog/2.0; "
    "+https://github.com/MicaLovesKPOP/micas-space)"
)

SOURCES = {
    "Korea Herald": {"kind": "rss", "url": "https://www.koreaherald.com/rss/kh_Kpop"},
    "Music Business Worldwide": {"kind": "rss", "url": "https://www.musicbusinessworldwide.com/feed/"},
    "Soompi Music": {"kind": "rss", "url": "https://www.soompi.com/category/music/feed"},
    "Soompi Celeb": {"kind": "rss", "url": "https://www.soompi.com/category/celeb/feed"},
    "Yonhap K-pop": {"kind": "html", "url": "https://en.yna.co.kr/culture/k-pop", "host": "en.yna.co.kr"},
}

SOURCE_PRIORITY = {
    "Yonhap K-pop": 100,
    "Korea Herald": 95,
    "Music Business Worldwide": 90,
    "Soompi Music": 80,
    "Soompi Celeb": 80,
}

MBW_KPOP_CONTEXT = [
    "k-pop", "kpop", "south korea", "korean music", "korean entertainment",
    "hybe", "ador", "belift", "source music", "pledis", "koz entertainment",
    "sm entertainment", "yg entertainment", "jyp entertainment", "starship",
    "cube entertainment", "attrakt", "wakeone", "modhaus", "rbw", "fnc entertainment",
    "newjeans", "fifty fifty", "bts", "blackpink", "aespa", "ive", "illit",
    "le sserafim", "twice", "stray kids", "seventeen", "enhypen", "txt",
]

EVENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("Debut / new group", [
        r"\bnew girl group\b", r"\bnew boy group\b", r"\bnew idol group\b",
        r"\bdebut lineup\b", r"\bpre[- ]?debut\b", r"\bsolo debut\b",
        r"\bset to debut\b", r"\bto debut\b", r"\bdebut(?:s|ed|ing)?\b",
        r"\blaunch(?:es|ing)? .*\b(?:girl|boy|idol)? ?group\b",
    ]),
    ("Comeback / release", [
        r"\bcomeback\b",
        r"\breturn(?:s|ing)? with .*\b(?:album|ep|single)s?\b",
        r"\bset to return with .*\b(?:album|ep|single)s?\b",
        r"\bannounces? .*\b(?:album|ep|single)s?\b",
        r"\bconfirms? .*\b(?:album|ep|single)s?\b",
        r"\bset to release .*\b(?:album|ep|single)s?\b",
        r"\bto release .*\b(?:album|ep|single)s?\b",
        r"\bto drop .*\b(?:album|ep|single)s?\b",
        r"\bdrops? .*\b(?:album|ep|single)s?\b",
        r"\breleases? .*\b(?:album|ep|single)s?\b",
        r"\brelease date\b",
    ]),
    ("Contract / agency", [
        r"\bexclusive contract\b", r"\bcontract dispute\b", r"\bcontract termination\b",
        r"\bterminates? .*contract\b", r"\bends? .*contract\b", r"\brenews? .*contract\b",
        r"\bcontract renewal\b", r"\bsigns? with .*agency\b", r"\bsigned with .*agency\b",
        r"\bsigning with .*agency\b", r"\bnew agency\b", r"\bjoins? .*agency\b",
        r"\bleaves? .*agency\b", r"\bparts ways with\b", r"\bmanagement contract\b",
        r"\btransfer(?:s|red)? to\b", r"\bchanges? agencies\b",
    ]),
    ("Legal / dispute", [
        r"\bcourt\b", r"\blawsuit\b", r"\bsues?\b", r"\bsued\b", r"\binjunction\b",
        r"\bappeal\b", r"\bruling\b", r"\blegal action\b", r"\blegal dispute\b",
        r"\binvestigation\b", r"\bprosecutors?\b", r"\bcomplaint\b",
        r"\bfair trade commission\b", r"\bkftc\b",
    ]),
    ("Group / member status", [
        r"\bdisbands?\b", r"\bdisbandment\b", r"\bhiatus\b",
        r"\bhalts? activities\b", r"\bsuspends? activities\b",
        r"\bresumes? activities\b", r"\breturns? to activities\b",
        r"\bleaves? (?:the )?group\b", r"\bdeparts? (?:from )?(?:the )?group\b",
        r"\bmember departure\b", r"\bjoins? (?:the )?group\b",
        r"\blineup change\b", r"\bpromote as [0-9]+[- ]member\b",
    ]),
    ("Industry / label", [
        r"\bacquisition\b", r"\bacquires?\b", r"\bmerger\b", r"\bmerges? with\b",
        r"\bnew subsidiary\b", r"\blaunches? .*label\b", r"\blaunches? .*agency\b",
        r"\brestructur(?:e|es|ing)\b", r"\bappoints? .*ceo\b", r"\bnew ceo\b",
        r"\bdistribution deal\b", r"\bmanagement deal\b",
    ]),
]

GOSSIP_DROP = [
    "dating", "relationship rumor", "dating rumor", "spotted with", "seen with",
    "airport fashion", "airport look", "outfit", "luxury bag", "handbag", "purse",
    "jewelry", "jewellery", "mansion", "house purchase", "real estate",
    "property purchase", "donation", "donates", "donated", "charity",
    "netizens react", "netizens debate", "netizens discuss", "stuns in", "gorgeous",
    "visuals", "instagram", "selfie", "brand ambassador", "global ambassador",
    "endorsement", "ad campaign", "pictorial", "magazine cover", "birthday",
    "net worth", "richest", "expensive car", "marriage", "wedding", "pregnancy",
]

NOISE_DROP = [
    "music chart", "weekly chart", "billboard", "world albums chart", "circle chart",
    "brand reputation", "takes 1st win", "takes 2nd win", "takes 3rd win",
    "music show win", "million views", "billion views", "sales record",
    "first-week sales", "pre-order record", "award lineup", "red carpet",
    "fan meeting", "fanmeeting", "tour dates", "tour stops", "concert tour",
    "festival lineup", "performance video", "dance practice", "itunes chart",
    "debut anniversary", "acting debut", "light stick", "military enlistment",
]

TEASER_DROP = [
    "teaser", "concept photo", "concept image", "concept film", "concept films",
    "highlight medley", "track list", "tracklist", "scheduler", "schedule poster",
    "preview", "mood sampler", "ahead of comeback",
]
STRONG_ANNOUNCEMENT = [
    "announces", "announced", "confirms", "confirmed", "comeback date", "debut date",
    "set to debut", "to debut", "set to return", "set to release", "release date",
]

REGIONAL_DEBUT_DROP = [
    "japan debut", "japanese debut", "korean debut", "u.s. debut", "us debut",
]

# Ordinary crime/defamation cases involving a celebrity are not the kind of legal
# news wanted here. A legal headline needs to concern artist/agency business,
# contracts, rights, ownership or one of the large ongoing K-pop disputes.
LEGAL_RELEVANCE = [
    "contract", "exclusive", "management", "copyright", "plagiarism", "trademark",
    "music rights", "artist rights", "royalt", "ownership", "shareholder", "shares",
    "injunction", "termination", "ador", "newjeans", "min hee-jin", "min heejin",
    "attrakt", "fifty fifty", "hybe", "belift", "source music",
]

# Soompi Celeb also covers actors. Reject obvious acting-only items unless the
# title/summary has clear music/idol context.
NON_MUSIC_CELEB = [
    " actor ", " actress ", "drama", "film", "movie", "acting career", "starring in",
]
MUSIC_CONTEXT = [
    "k-pop", "kpop", "singer", "idol", "rapper", "soloist", "girl group", "boy group",
    "member of", "members of", "band", "comeback", "album", "ep ", "single",
]

DEDUP_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "with", "for", "of", "in", "on", "at",
    "as", "from", "after", "amid", "over", "new", "kpop", "pop", "group", "girl",
    "boy", "members", "member", "agency", "label", "entertainment", "activities",
    "announces", "announced", "confirms", "confirmed", "officially", "sign", "signs",
    "signed", "comeback", "return", "returns", "release", "releases", "released",
    "album", "ep", "single", "debut", "date", "next", "month", "spring", "fall",
    "autumn", "winter", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december", "team",
    "make", "makes", "making", "plans", "plan", "restart", "under", "will",
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


def trim(value: str, limit: int = 820) -> str:
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
    with urllib.request.urlopen(req, timeout=30) as response:
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


def soompi_celeb_is_music(title: str, summary: str) -> bool:
    hay = f" {lower(title)} {lower(summary)} "
    title_l = lower(title)
    if "acting debut" in title_l:
        return False
    if any(term in hay for term in NON_MUSIC_CELEB) and not any(term in hay for term in MUSIC_CONTEXT):
        return False
    return True


def classify(title: str, summary: str, source: str) -> tuple[str | None, str]:
    # Headlines determine the event. Summaries are only used to identify actors
    # in Soompi's mixed Celeb feed; historical facts in an excerpt must not turn
    # an unrelated story into a false event.
    text = lower(title)

    if source == "Music Business Worldwide" and not any(term in text for term in MBW_KPOP_CONTEXT):
        return None, "MBW: no Korean/K-pop context in headline"

    if source == "Soompi Celeb" and not soompi_celeb_is_music(title, summary):
        return None, "Soompi Celeb: acting/non-music item"

    gossip = [term for term in GOSSIP_DROP if term in text]
    if gossip:
        return None, "celebrity/lifestyle noise: " + ", ".join(gossip[:3])

    noise = [term for term in NOISE_DROP if term in text]
    if noise:
        return None, "routine PR/fandom noise: " + ", ".join(noise[:3])

    category = None
    for candidate, patterns in EVENT_PATTERNS:
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            category = candidate
            break

    if not category:
        return None, "no meaningful-change event matched"

    if category == "Debut / new group" and any(term in text for term in REGIONAL_DEBUT_DROP):
        if not any(term in text for term in ("new girl group", "new boy group", "new idol group")):
            return None, "regional-market debut rather than a new act"

    teaser_hits = [term for term in TEASER_DROP if term in text]
    if teaser_hits and category in {"Debut / new group", "Comeback / release"}:
        if not any(term in text for term in STRONG_ANNOUNCEMENT):
            return None, "teaser/rollout post"

    if category == "Legal / dispute" and not any(term in text for term in LEGAL_RELEVANCE):
        return None, "legal story unrelated to contracts/agency business/artist rights"

    return category, "whitelisted event"


def article_meta(url: str) -> tuple[str, str | None, float]:
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
    result: list[Item] = []
    for entry in parsed.entries[:70]:
        title = normalize(entry.get("title", ""))
        link = entry.get("link", "")
        summary = trim(entry.get("summary", "") or entry.get("description", ""))
        category, reason = classify(title, summary, name)
        debug["decisions"].append({
            "source": name, "title": title, "link": link, "keep": bool(category),
            "category": category, "reason": reason,
        })
        if not category:
            continue
        published, ts = published_info(entry)
        result.append(Item(title, link, name, summary, category, published, ts))
    return result


def yonhap_items(name: str, url: str, host: str, debug: dict) -> list[Item]:
    try:
        soup = BeautifulSoup(fetch_bytes(url), "html.parser")
    except Exception as exc:
        debug["sources"].append({"name": name, "url": url, "status": "error", "error": str(exc)})
        return []

    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a.get("href", "")).split("#", 1)[0]
        parsed = urlparse(href)
        if parsed.hostname != host and not (parsed.hostname and parsed.hostname.endswith("." + host)):
            continue
        if "/view/AEN" not in parsed.path or "section=culture/k-pop" not in href:
            continue
        title = normalize(a.get_text(" ", strip=True))
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        links.append((title, href))
        if len(links) >= 45:
            break

    debug["sources"].append({"name": name, "url": url, "status": "ok", "items": len(links)})
    result: list[Item] = []
    for title, link in links:
        category, reason = classify(title, "", name)
        if not category:
            debug["decisions"].append({
                "source": name, "title": title, "link": link, "keep": False,
                "category": None, "reason": reason,
            })
            continue
        summary, published, ts = article_meta(link)
        debug["decisions"].append({
            "source": name, "title": title, "link": link, "keep": True,
            "category": category, "reason": reason,
        })
        result.append(Item(title, link, name, summary, category, published, ts))
    return result


def dedupe_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", lower(title))
    return {w for w in words if len(w) > 2 and w not in DEDUP_STOPWORDS}


def likely_duplicate(a: Item, b: Item) -> bool:
    if a.link == b.link:
        return True
    if a.category != b.category:
        return False

    ta, tb = dedupe_tokens(a.title), dedupe_tokens(b.title)
    shared = ta & tb
    if not shared:
        return False

    # Newsrooms normally publish the same event within roughly the same day.
    # This lets titles such as "ILLIT comeback date" and "ILLIT to return with
    # new EP" collapse while unrelated template headlines about two different
    # artists never collide merely because both say "October comeback".
    if a.sort_ts and b.sort_ts and abs(a.sort_ts - b.sort_ts) <= 36 * 3600:
        return True

    union = ta | tb
    return bool(union) and len(shared) / len(union) >= 0.5


def priority(item: Item) -> int:
    base = SOURCE_PRIORITY.get(item.source, 50)
    if item.category in {"Debut / new group", "Comeback / release", "Group / member status"} and item.source.startswith("Soompi"):
        return base + 30
    if item.category in {"Legal / dispute", "Contract / agency"} and item.source in {"Yonhap K-pop", "Korea Herald"}:
        return base + 20
    return base


def dedupe(items: list[Item], debug: dict) -> list[Item]:
    ranked = sorted(items, key=lambda x: (priority(x), x.sort_ts), reverse=True)
    kept: list[Item] = []
    for item in ranked:
        match = next((x for x in kept if likely_duplicate(item, x)), None)
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
        "Betekenisvolle K-pop-veranderingen: debuts, comebacks/releases, contracten/agencies, relevante juridische zaken, groepsstatus en belangrijke labelontwikkelingen. Geen celebritygossip, lifestyle, dating, donaties, charts of teaser-spam. Geen Reddit.",
    )
    add_text(channel, "language", "en")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    add_text(channel, "generator", "MicasKpopChangelog/2")

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
            candidates.extend(yonhap_items(name, cfg["url"], cfg["host"], debug))

    final = dedupe(candidates, debug)
    OUTPUT.write_bytes(build_feed(final))
    debug["candidate_items"] = len(candidates)
    debug["final_items"] = len(final)
    DEBUG_OUTPUT.write_text(json.dumps(debug, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"K-pop candidates: {len(candidates)} | final after dedupe: {len(final)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
