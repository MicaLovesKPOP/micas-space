#!/usr/bin/env python3
"""Build a filtered AutoWeek RSS feed for Inoreader.

The filter is intentionally conservative: normal car news stays in the feed.
It mainly removes routine consumer-oriented EV product coverage (range, charging,
prices, ordinary reviews, etc.) while retaining major EV industry/technology
news and unusual enthusiast/performance stories.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import feedparser

SOURCE_URLS = [
    "https://www.autoweek.nl/rss",
    "https://www.autoweek.nl/rss/",
]

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "autoweek-filtered.xml"
DEBUG_OUTPUT = ROOT / "filter-debug.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; MicaAutoWeekFeed/1.0; "
    "+https://github.com/MicaLovesKPOP/micas-space)"
)

# If one of these appears, keep the article even when it concerns an EV.
MAJOR_NEWS_TERMS = [
    "schrapt",
    "geschrapt",
    "stopt met",
    "stopzet",
    "failliet",
    "faillissement",
    "terugroep",
    "recall",
    "brandgevaar",
    "accubrand",
    "batterijbrand",
    "productiestop",
    "productie stopt",
    "fabriek sluit",
    "fabriek dicht",
    "ontslag",
    "strategie",
    "koerswijziging",
    "verbod",
    "wetgeving",
    "europese unie",
    "eu-regels",
    "importheffing",
    "invoerheffing",
    "tarief",
    "verkopen storten",
    "verkoop stort",
    "verkoopcijfers",
    "marktaandeel",
    "doorbraak",
    "nieuwe accutechniek",
    "nieuwe batterijtechniek",
    "solid-state",
    "prototype",
    "concept car",
    "conceptauto",
]

# Exceptional car-enthusiast EV stories may still be worth seeing.
EXCEPTIONAL_TERMS = [
    "nürburgring",
    "nurburgring",
    "record",
    "hypercar",
    "supercar",
    "raceauto",
    "rally",
    "drift",
    "restomod",
    "1000 pk",
    "1.000 pk",
    "1500 pk",
    "1.500 pk",
]

# Signals that the article is actually about an EV. These are checked mainly
# against the title, so a combustion-car article mentioning electric windows in
# its body does not disappear by accident.
EV_TERMS = [
    "elektrisch",
    "electric",
    "bev",
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
    "polestar",
    "tesla",
    "zeekr",
    "xpeng",
    "leapmotor",
    "byd",
    "nio ",
    "eqa",
    "eqb",
    "eqe",
    "eqs",
    "ex30",
    "ex40",
    "ec40",
    "ev2",
    "ev3",
    "ev4",
    "ev5",
    "ev6",
    "ev9",
    "taycan",
    "macan electric",
    "cayenne electric",
    "a6 e-tron",
    "a2 e-tron",
    "q4 e-tron",
    "q6 e-tron",
    "i4",
    "i5",
    "i7",
    "ix1",
    "ix2",
    "ix3",
    "bmw ix",
]

# Routine ownership/shopping/review subjects that make EV coverage uninteresting
# for this feed.
BORING_EV_TERMS = [
    "rijtest",
    "test:",
    "getest",
    "review",
    "actieradius",
    "rijbereik",
    "praktijkbereik",
    "range",
    "laadsnelheid",
    "snelladen",
    "snellader",
    "laadpaal",
    "laadpas",
    "thuisladen",
    "wallbox",
    "laadtijd",
    "laden met",
    "kwh",
    "private lease",
    "leaseprijs",
    "bijtelling",
    "vanaf €",
    "vanaf euro",
    "kost €",
    "kost euro",
    "prijs van",
    "heeft prijs",
    "goedkoper",
    "duurder",
    "bestellen",
    "bestelbaar",
    "leverbaar",
]

# Routine launch/update coverage of an EV. Only used when an EV signal is also
# present, so normal combustion-car introductions remain untouched.
ROUTINE_EV_PRODUCT_TERMS = [
    "nieuwe ",
    "vernieuwde ",
    "facelift",
    "modeljaar",
    "uitvoering",
    "instapper",
    "long range",
    "standard range",
    "lounge",
    "performance",
    "onthuld",
    "debuut",
    "komt naar nederland",
    "in nederland",
]


def normalize(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.lower().replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def matches(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def has_ev_signal(title: str) -> tuple[bool, list[str]]:
    hits = matches(title, EV_TERMS)
    if re.search(r"(?:^|\W)ev(?:$|\W)", title):
        hits.append("ev")
    return bool(hits), sorted(set(hits))


def decide(entry) -> tuple[bool, str, dict]:
    title = normalize(entry.get("title", ""))
    summary = normalize(entry.get("summary", ""))
    combined = f"{title} {summary}".strip()

    ev, ev_hits = has_ev_signal(title)
    major_hits = matches(combined, MAJOR_NEWS_TERMS)
    exceptional_hits = matches(combined, EXCEPTIONAL_TERMS)
    boring_hits = matches(combined, BORING_EV_TERMS)
    routine_hits = matches(title, ROUTINE_EV_PRODUCT_TERMS)

    evidence = {
        "ev": ev_hits,
        "major": major_hits,
        "exceptional": exceptional_hits,
        "boring": boring_hits,
        "routine_product": routine_hits,
    }

    if not ev:
        return True, "non-EV car news", evidence

    if major_hits:
        return True, "major EV industry/technology news", evidence

    if exceptional_hits:
        return True, "exceptional enthusiast/performance EV story", evidence

    if boring_hits:
        return False, "routine EV consumer/review/charging/range content", evidence

    if routine_hits:
        return False, "routine EV product/update coverage", evidence

    # When unsure, keep it. Better one mildly irrelevant article than silently
    # losing interesting news.
    return True, "EV article kept because no routine-consumer trigger matched", evidence


def fetch_source() -> tuple[bytes, str]:
    last_error = None
    for url in SOURCE_URLS:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
            if data:
                return data, url
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            print(f"Could not fetch {url}: {exc}", file=sys.stderr)
    raise RuntimeError(f"Could not fetch AutoWeek RSS: {last_error}")


def add_text(parent, tag: str, value: str | None):
    if value:
        ET.SubElement(parent, tag).text = str(value)


def build_feed(entries, source_url: str) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", "AutoWeek — gefilterd voor Mica")
    add_text(channel, "link", "https://www.autoweek.nl/")
    add_text(
        channel,
        "description",
        "AutoWeek zonder de meeste routine EV-reviews, laad/range- en productartikelen; belangrijk EV-industrienieuws blijft staan.",
    )
    add_text(channel, "language", "nl-NL")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    add_text(channel, "generator", "MicaAutoWeekFeed")
    add_text(channel, "docs", source_url)

    for entry, reason in entries:
        item = ET.SubElement(channel, "item")
        title = entry.get("title", "(zonder titel)")
        link = entry.get("link", "")
        guid = entry.get("id") or link or title
        add_text(item, "title", title)
        add_text(item, "link", link)
        guid_el = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid_el.text = guid

        published = entry.get("published") or entry.get("updated")
        add_text(item, "pubDate", published)

        # Keep only a small source excerpt so Inoreader remains useful while the
        # actual article stays on AutoWeek.
        summary = normalize(entry.get("summary", ""))
        if len(summary) > 500:
            summary = summary[:497].rstrip() + "…"
        desc = f"Filter: {reason}."
        if summary:
            desc += f"\n\n{summary}"
        add_text(item, "description", desc)
        add_text(item, "category", reason)

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    raw, source_url = fetch_source()
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"AutoWeek RSS could not be parsed: {parsed.bozo_exception}")

    kept = []
    debug = []
    for entry in parsed.entries:
        keep, reason, evidence = decide(entry)
        debug.append(
            {
                "keep": keep,
                "reason": reason,
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "matches": evidence,
            }
        )
        if keep:
            kept.append((entry, reason))

    OUTPUT.write_bytes(build_feed(kept, source_url))
    DEBUG_OUTPUT.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": source_url,
                "source_items": len(parsed.entries),
                "kept_items": len(kept),
                "dropped_items": len(parsed.entries) - len(kept),
                "decisions": debug,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Source: {len(parsed.entries)} | kept: {len(kept)} | dropped: {len(parsed.entries) - len(kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
