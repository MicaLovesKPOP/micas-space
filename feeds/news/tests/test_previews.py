"""RSS presentation regressions: no boilerplate masquerading as article intros."""
import copy
import sys
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_reuters_world as build

NOW = datetime(2026, 9, 15, 5, tzinfo=timezone.utc)


def story(**overrides):
    return {
        "title": "Example headline for an RSS rendering test",
        "url": "https://www.reuters.com/world/example-2026-09-14/",
        "published_dt": NOW - timedelta(hours=8),
        "region": "World",
        **overrides,
    }


class PreviewTests(unittest.TestCase):
    def test_article_preview_is_explicitly_empty(self):
        for region in ("World", "Europe", "Asia Pacific", None):
            with self.subTest(region=region):
                root = ET.fromstring(build.rss_bytes([story(region=region)], NOW))
                item = root.find("channel/item")
                description = item.find("description")
                self.assertIsNotNone(description)
                self.assertEqual(description.text or "", "")
                item_xml = ET.tostring(item, encoding="unicode")
                for boilerplate in ("Selected from", "Headline from", "Open the original", "World / World"):
                    self.assertNotIn(boilerplate, item_xml)
                self.assertIsNone(item.find("{http://purl.org/rss/1.0/modules/content/}encoded"))

    def test_explanation_remains_at_feed_level(self):
        root = ET.fromstring(build.rss_bytes([story()], NOW))
        self.assertEqual(root.findtext("channel/title"), "Reuters World — Mica")
        self.assertIn("Headline-based selection", root.findtext("channel/description"))
        self.assertEqual(root.findtext("channel/link"), build.WORLD_URL)

    def test_refresh_does_not_change_article_identity_or_publication_date(self):
        source = story()
        first = ET.fromstring(build.rss_bytes([source], NOW)).find("channel/item")
        later = ET.fromstring(build.rss_bytes([source], NOW + timedelta(hours=1))).find("channel/item")
        for tag in ("title", "link", "guid", "pubDate", "category"):
            self.assertEqual(first.findtext(tag), later.findtext(tag))
        self.assertEqual(later.findtext("guid"), source["url"])
        self.assertEqual(later.find("guid").get("isPermaLink"), "true")
        self.assertEqual(later.findtext("pubDate"), format_datetime(source["published_dt"], usegmt=True))

    def test_presentation_does_not_mutate_selection_or_history(self):
        stories = [story(), story(title="Second rendering fixture", url="https://www.reuters.com/world/second-2026-09-14/")]
        original = copy.deepcopy(stories)
        root = ET.fromstring(build.rss_bytes(stories, NOW))
        self.assertEqual(stories, original)
        self.assertEqual([i.findtext("title") for i in root.findall("channel/item")],
                         [s["title"] for s in original])

    def test_xml_escaping_preserves_headline(self):
        title = 'A & B: "agreement" <draft> — café'
        root = ET.fromstring(build.rss_bytes([story(title=title)], NOW))
        self.assertEqual(root.findtext("channel/item/title"), title)

    def test_empty_feed_is_valid_without_filler(self):
        root = ET.fromstring(build.rss_bytes([], NOW))
        self.assertEqual(root.get("version"), "2.0")
        for tag in ("title", "link", "description"):
            self.assertTrue(root.findtext("channel/" + tag))
        self.assertEqual(root.findall("channel/item"), [])


if __name__ == "__main__":
    unittest.main()
