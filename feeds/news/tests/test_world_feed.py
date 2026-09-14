"""Offline policy/regression tests. Example headlines are NOT fact-checked news.

The first table captures titles supplied in user screenshots / the old feed.
Synthetic cases then test important stories we must not accidentally suppress.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_reuters_world as build
from world_selection import classify, select, is_duplicate, tolls

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)

# Historic fixture labels reflect the requested editorial policy, not a claim
# that any of these underlying events really happened.
SCREENSHOT_AND_OLD_FEED = [
    ("India opens door to fees on large payments made via UPI system", False),
    ("Winter is coming: airBaltic debt woes herald tough season ahead for smaller airlines", False),
    ("Trump privately met with OpenAI’s Altman at GOP convention, MS Now reports", False),
    ("CVC joins JC Flowers in potential bid for UK bank Aldermore, sources say", False),
    ("Spanish minister demands justice after violent death of young woman in Mexico", False),
    ("EU envoys extend Russia sanctions by seven days to debate six-month renewal, EU presidency says", False),
    ("Netanyahu says Gaza documentary 'NAZA' is 'shocking incitement'", False),
    ("US lacks funding to complete first phase of air traffic control reforms, report finds", False),
    ("Almonty and Rwanda form tungsten venture backed by US economic framework", False),
    ("Lula, Bolsonaro neck-and-neck in Brazil runoff polls ahead of election", False),
    ("Canada's August inflation holds steady at 3% as crude stays firm; food prices ease", False),
    ("Indonesia rescuers battle turbulent seas in search for 129 people after passenger ship capsizes", True),
    ("9/11, 25 years on: the Reuters reporter who was with George W. Bush that morning", False),
    ("CPC increased oil exports by 22% in August after fewer attacks on tankers, sources say", False),
    ("China bank loans rise less than expected in August after July slump", False),
    ("Immigrants express relief after Sweden Democrats suffer election setback", False),
    ("Sweden's centre-left ahead as far-right stumbles in tight election", True),
    ("Global AI stocks fall as industry chiefs call for slowing development", False),
    ("Trump attributes state election win of Germany's far-right to immigration", False),
    ("ASML extends chipmaking dominance as customers embrace High NA", False),
    ("Senior Sunni cleric shot dead by unidentified gunmen in southeast Iran - Iranian state media", False),
    ("Tech stocks slide on AI slowdown talks", False),
    ("Etihad Airways says passenger numbers have rebounded from Iran war impact", False),
    ("Final report on Lucy Letby baby murders due, amid growing questions about convictions", False),
    ("Colombia Congress approves 2027 budget as fiscal strains deepen", False),
    ("North Korea's Kim vows to expand ties with Russia, backs victory in 'sacred war'", False),
    ("US NTSB says one-third of FAA answers to safety recommendations are 'unacceptable'", False),
    ("Trump nominates Republican lawmaker as ambassador to Saudi Arabia", False),
    ("Stocks fall as oil and bond yields rise", False),
    ("'Good move': Indonesia's finance minister switch will ease investor jitters", False),
    ("US imposes fresh sanctions on Russia's VTB Bank over alleged Iran ties", True),
    ("Dollar rises as Middle East conflict lifts oil, Fed hike looms", False),
    ("China state newspaper blasts Anthropic's calls to slow AI as 'Cold War' tactic'", False),
    ("Gold falls to over one-month low as oil rally, inflation data boost rate-hike bets", False),
    ("Defensive stocks lift FTSE 100 at start of pivotal week for central banks", False),
    ("Portugal says Israel undermining Palestinian state through settlement expansion", False),
    ("China to impose no-fly zone over Beijing after light aircraft crashed into city's tallest tower", False),
    ("Israeli strikes on southern Lebanese town kill 13 as fears of escalation mount", True),
    ("World Food Programme funding for Sudan plummets as more go hungry, head says", True),
    ("South African rand falls over 1% as oil jumps and investors await Fed meeting", False),
    ("Gulf equities mixed as Saudi energy, shipping security concerns weigh", False),
    ("JPMorgan to launch long-awaited 'frontier' local currency debt index", False),
    ("Yemen's displaced long for loved ones, stability as Houthis advance", False),
    ("Iran protests as US prevents its nuclear chief attending IAEA meeting", False),
]

IMPORTANT = [
    "Israel and Hamas agree to Gaza ceasefire",
    "Gaza ceasefire takes effect after Israel and Hamas sign deal",
    "Gaza ceasefire collapses as Israel resumes attacks",
    "Ukraine peace talks resume after breakthrough",
    "Hostages released under Gaza deal",
    "Russia launches ground offensive in Ukraine",
    "US launches air strikes on Iran",
    "Military coup ousts president in Niger",
    "North Korea conducts nuclear test, officials say",
    "Missile strikes on nuclear plant raise safety alarm",
    "Brazil opposition wins presidential election",
    "Swedish centre-left wins majority in election",
    "Romania president resigns after national protests",
    "French government collapses after no-confidence vote",
    "Opposition leader jailed in Bangladesh",
    "EU imposes new sanctions on Russia",
    "China introduces rare earth export restrictions",
    "US lifts tariffs on imports under agreement",
    "Japan signs defence pact with Philippines",
    "Iran cuts diplomatic ties with Britain",
    "Indonesia ferry sinks, at least 75 people missing",
    "Earthquake kills 200 people in Nepal",
    "Flooding leaves 50,000 people displaced in Pakistan",
    "Wildfires kill dozens in Chile",
    "Chile issues tsunami warning after earthquake",
    "Category 5 hurricane triggers mass evacuations in Mexico",
    "Magnitude 7.8 earthquake strikes Japan",
    "Famine declared in Sudan as millions face starvation",
    "WHO declares international public health emergency over outbreak",
    "WHO ends pandemic emergency",
    "New virus spreads to five countries, health officials say",
    "World records hottest year, UN scientists confirm",
    "Sri Lanka defaults on foreign debt",
    "Argentina introduces capital controls amid banking crisis",
    "Wall Street trading halted as circuit breakers triggered",
    "Nationwide blackout hits Spain and Portugal",
    "Government bans opposition parties nationwide",
    "France parliament legalises same-sex marriage",
    "US Supreme Court overturns abortion rights",
]

NOISE = [
    "US stocks fall as Russia launches invasion of Ukraine",
    "Oil prices rise after Israel and Hamas agree ceasefire",
    "Bank shares rise after government announces sanctions",
    "Trump praises Swedish election winner",
    "Britain condemns Iran missile strikes",
    "Analysts urge government to lift sanctions",
    "Russia considers ground offensive in Ukraine",
    "US plans to launch air strikes on Iran",
    "Polls show government would win Brazil election",
    "Germany far-right wins regional election",
    "Why investors are buying banks ahead of election",
    "Airline reports record passenger numbers after war",
    "Analysis: Gaza ceasefire agreement and what happens next",
    "Plane crash kills 2 near village in France",
    "Company sells 2026 model after earthquake",
    "India reports routine inflation figures",
    "Airline seeks emergency bailout after debt default",
    "Lawmaker comments on nuclear weapons",
]


def story(title, url="one", hours=1):
    return {"title": title, "url": "https://www.reuters.com/world/europe/" + url + "-2026-09-14/",
            "published_dt": NOW - timedelta(hours=hours), "region": "Europe"}


class PolicyTests(unittest.TestCase):
    def test_screenshot_and_old_feed(self):
        for title, keep in SCREENSHOT_AND_OLD_FEED:
            with self.subTest(title=title):
                self.assertEqual(classify(title).keep, keep, classify(title))

    def test_important_events(self):
        for title in IMPORTANT:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))

    def test_noise_and_topic_word_traps(self):
        for title in NOISE:
            with self.subTest(title=title):
                self.assertFalse(classify(title).keep, classify(title))

    def test_casualty_number_context(self):
        self.assertEqual(tolls("2026 stocks rise 22% after crash"), {"dead": 0, "missing": 0, "displaced": 0})
        self.assertEqual(tolls("Floods leave 50,000 people displaced")["displaced"], 50000)
        self.assertEqual(tolls("Death toll rises to 150")["dead"], 150)

    def test_empty_headline(self):
        self.assertFalse(classify("").keep)


class PublicationTests(unittest.TestCase):
    def run_selection(self, rows, previous=None, now=NOW):
        return select(rows, previous or [], now)

    def test_same_election_deduplicated(self):
        rows = [story("Sweden opposition wins election", "a"),
                story("Swedish centre-left wins majority in election", "b", 2)]
        current, _, audit = self.run_selection(rows)
        self.assertEqual(len(current), 1)
        self.assertTrue(any(a["reason"] == "same_event_and_development" for a in audit))

    def test_cross_run_election_dedup(self):
        _, previous, _ = self.run_selection([story("Sweden opposition wins election", "a")])
        current, _, audit = self.run_selection([story("Swedish centre-left wins majority in election", "b")], previous)
        self.assertEqual(len(current), 1)
        self.assertIn("/a-", current[0]["url"])

    def test_real_new_phase_not_suppressed(self):
        rows = [story("Israel and Hamas agree to Gaza ceasefire", "a", 4),
                story("Gaza ceasefire takes effect after Israel and Hamas sign deal", "b", 2),
                story("Gaza ceasefire collapses as Israel resumes attacks", "c", 1)]
        current, _, _ = self.run_selection(rows)
        self.assertEqual(len(current), 3)

    def test_different_countries_not_duplicates(self):
        for a, b in [("Sweden", "France"), ("Latvia", "Estonia")]:
            rows = [story(f"{a} opposition wins parliamentary election", a),
                    story(f"{b} opposition wins parliamentary election", b)]
            self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_different_elections_not_duplicates(self):
        rows = [story("France opposition wins presidential election", "a"),
                story("France opposition wins parliamentary election", "b")]
        self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_annulled_election_is_a_new_development(self):
        rows = [story("Romania opposition wins presidential election", "a", 5),
                story("Romania presidential election annulled by court", "b")]
        self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_sanctions_lifted_not_merged_with_imposition(self):
        rows = [story("US imposes new sanctions on Iran nuclear programme", "a", 5),
                story("US lifts new sanctions on Iran nuclear programme", "b")]
        self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_different_named_disaster_locations(self):
        rows = [story("Brazil floods in Recife leave 50 dead after heavy rainfall", "a"),
                story("Brazil floods in Manaus leave 50 dead after heavy rainfall", "b")]
        self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_new_government_is_not_election_duplicate(self):
        rows = [story("Germany opposition wins election", "a", 5),
                story("Germany opposition forms new government", "b")]
        self.assertEqual(len(self.run_selection(rows)[0]), 2)

    def test_large_toll_update_gets_new_entry(self):
        _, previous, _ = self.run_selection([story("Nepal earthquake death toll rises to 50", "a", 4)])
        current, _, _ = self.run_selection([story("Nepal earthquake death toll rises to 150", "b")], previous)
        self.assertEqual(len(current), 2)

    def test_small_toll_update_suppressed(self):
        _, previous, _ = self.run_selection([story("Nepal earthquake death toll rises to 50", "a", 4)])
        current, _, _ = self.run_selection([story("Nepal earthquake death toll rises to 55", "b")], previous)
        self.assertEqual(len(current), 1)

    def test_same_url_keeps_original_date(self):
        original = story("Sweden opposition wins election", "a", 6)
        _, previous, _ = self.run_selection([original])
        update = story("Swedish centre-left wins majority in election", "a", 1)
        current, _, _ = self.run_selection([update], previous)
        self.assertEqual(current[0]["published_dt"], original["published_dt"])
        self.assertEqual(current[0]["url"], original["url"])
        self.assertEqual(current[0]["title"], update["title"])

    def test_old_noise_not_grandfathered(self):
        current, _, _ = self.run_selection([], [story("Stocks fall as oil rises")])
        self.assertEqual(current, [])

    def test_legacy_duplicates_cleaned(self):
        previous = [story("Sweden opposition wins election", "a", 2),
                    story("Swedish centre-left wins majority in election", "b")]
        self.assertEqual(len(self.run_selection([], previous)[0]), 1)

    def test_no_minimum_quota(self):
        self.assertEqual(self.run_selection([story("Stocks fall as oil rises")])[0], [])

    def test_no_hard_daily_cap(self):
        rows = [story(f"Country{i} opposition wins election", str(i)) for i in range(50)]
        self.assertEqual(len(self.run_selection(rows)[0]), 50)

    def test_rolling_retention_and_no_resurrection(self):
        s = story("Sweden opposition wins election", "a", 80)
        current, history, _ = self.run_selection([story(s["title"], "a")], [s])
        self.assertEqual(current, [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["published_dt"], s["published_dt"])

    def test_empty_discovery_does_not_delete_recent_history_in_selection(self):
        s = story("Sweden opposition wins election")
        self.assertEqual(len(self.run_selection([], [s])[0]), 1)

    def test_invalid_future_old_dates(self):
        for dt in [None, NOW + timedelta(days=1), NOW - timedelta(days=4)]:
            s = story("Sweden opposition wins election")
            s["published_dt"] = dt
            self.assertEqual(self.run_selection([s])[0], [])

    def test_history_expiry(self):
        s = story("Sweden opposition wins election", hours=200)
        self.assertEqual(self.run_selection([], [s])[1], [])


class BuildTests(unittest.TestCase):
    def test_canonical_url_stable(self):
        self.assertEqual(build.canonical_reuters_url("https://reuters.com/world/a-2026-09-14?utm=x#top"),
                         "https://www.reuters.com/world/a-2026-09-14/")
        for bad in ["https://example.com/world/foo", "http://www.reuters.com/world/foo"]:
            with self.assertRaises(ValueError):
                build.canonical_reuters_url(bad)

    def test_sitemap_scopes_and_dates(self):
        xml = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:n="http://www.google.com/schemas/sitemap-news/0.9">
            <url><loc>https://www.reuters.com/world/a-2026-09-14/</loc><n:news>
            <n:title>Sweden opposition wins election</n:title><n:publication_date>2026-09-14T10:00:00Z</n:publication_date>
            </n:news></url><url><loc>https://example.com/world/b-2026-09-14/</loc></url>
            <url><loc>https://www.reuters.com/business/c-2026-09-14/</loc></url></urlset>'''
        rows = build.parse_news_sitemap(xml)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_dt"].tzinfo, timezone.utc)

    def test_rss_ids_escaping_and_dates(self):
        s = story("Israel & Hamas agree to Gaza ceasefire <deal>")
        root = ET.fromstring(build.rss_bytes([s], NOW))
        self.assertEqual(root.findtext("channel/item/guid"), s["url"])
        self.assertEqual(root.findtext("channel/item/title"), s["title"])
        self.assertIn("GMT", root.findtext("channel/item/pubDate"))
        self.assertEqual(ET.fromstring(build.rss_bytes([], NOW)).findall("channel/item"), [])

    def test_reads_all_candidates_before_selection(self):
        urls = ["https://www.reuters.com/map1", "https://www.reuters.com/map2"]
        rows1 = [story("Stocks rise", str(i)) for i in range(95)]
        rows2 = [story("France government collapses", "important")]
        with patch.object(build, "fetch", return_value=b"xml"), \
             patch.object(build, "child_sitemaps", return_value=urls), \
             patch.object(build, "parse_news_sitemap", side_effect=[rows1, rows2]):
            rows, _ = build.discover()
        self.assertEqual(len(rows), 96)
        self.assertTrue(any(s["title"] == "France government collapses" for s in rows))

    def test_output_lifecycle_and_failure_safety(self):
        with tempfile.TemporaryDirectory() as temp:
            out, debug, state = [Path(temp) / name for name in ("feed.xml", "debug.json", "state.json")]
            with patch.multiple(build, OUTPUT=out, DEBUG_OUTPUT=debug, STATE_OUTPUT=state), \
                 patch.object(build, "datetime") as clock:
                clock.now.return_value = NOW
                clock.fromisoformat.side_effect = datetime.fromisoformat
                with patch.object(build, "discover", return_value=([story("Sweden opposition wins election")], {})):
                    self.assertEqual(build.main(), 0)
                original = out.read_bytes()
                saved_state = state.read_bytes()
                self.assertEqual(len(build.load_history()), 1)
                with patch.object(build, "discover", return_value=([], {})):
                    self.assertEqual(build.main(), 1)
                self.assertEqual(out.read_bytes(), original)
                self.assertEqual(state.read_bytes(), saved_state)
                self.assertIn("fatal_error", json.loads(debug.read_text()))

    def test_migration_and_corrupt_state(self):
        with tempfile.TemporaryDirectory() as temp:
            out, state = Path(temp) / "feed.xml", Path(temp) / "state.json"
            with patch.multiple(build, OUTPUT=out, STATE_OUTPUT=state):
                s = story("Sweden opposition wins election")
                out.write_bytes(build.rss_bytes([s], NOW))
                self.assertEqual(build.load_history()[0]["published_dt"], s["published_dt"])
                state.write_text('{"version": 999, "items": []}')
                with self.assertRaises(ValueError):
                    build.load_history()


if __name__ == "__main__":
    unittest.main()
