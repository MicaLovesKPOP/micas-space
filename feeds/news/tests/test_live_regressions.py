"""Refinements from inspecting BOTH selected and rejected first-run headlines.

These are classification inputs, not verification of the underlying news events.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from world_selection import classify, select


class LiveRegressionTests(unittest.TestCase):
    def test_company_president_is_not_national_leader(self):
        titles = [
            "Chubu says its president to resign, nuclear restart application withdrawn over data scandal",
            "Company president resigns after data scandal",
            "University president resigns following investigation",
            "President of the bank resigns after fraud inquiry",
        ]
        for title in titles:
            with self.subTest(title=title):
                decision = classify(title)
                self.assertFalse(decision.keep, decision)
                self.assertEqual(decision.reason, "corporate_leadership_not_national_power")

    def test_real_national_leaders_still_qualify(self):
        for title in ["Vietnam says its president resigns after corruption probe",
                      "France president resigns after political crisis",
                      "Latvia prime minister resigns after no-confidence vote"]:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))

    def test_regional_election_implications_not_national_result(self):
        titles = [
            "Okinawa election win may give Tokyo freer hand on military build-up",
            "Regional vote victory could pave way for defence reforms",
            "Opposition wins prefectural election in Japan",
            "Democrats win gubernatorial election in US",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(classify(title).keep, classify(title))

    def test_narrow_individual_sanctions_not_major_policy(self):
        for title in ["Ukraine's Zelenskiy imposes sanctions on former press secretary",
                      "President imposes sanctions against his former aide",
                      "Government introduces sanctions on a blogger"]:
            with self.subTest(title=title):
                self.assertFalse(classify(title).keep, classify(title))

    def test_international_sanctions_still_qualify(self):
        for title in ["US imposes fresh sanctions on Russia's VTB Bank over alleged Iran ties",
                      "EU imposes new sanctions on Russia's president",
                      "China lifts tariffs on US imports"]:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))

    def test_major_protest_wave_is_not_missed(self):
        for title in ["Syria fuel price hikes trigger widest protests since Assad fall",
                      "Food price hikes spark largest protests since revolution in Sudan"]:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))
        self.assertFalse(classify("Why Syria's president fears the largest protests since revolution").keep)

    def test_major_emergency_does_not_need_a_death_toll(self):
        for title in ["Urban wildfire threatens Ecuador's capital",
                      "Wildfires engulf national capital as residents flee"]:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))
        self.assertFalse(classify("Wildfire threatens remote barn in France").keep)

    def test_blast_noun_is_not_political_criticism(self):
        for title in ["Bomb blasts kill 100 people in Somalia",
                      "Deadly blast leaves 75 dead in Pakistan"]:
            with self.subTest(title=title):
                self.assertTrue(classify(title).keep, classify(title))
        self.assertFalse(classify("President blasts election result in Sweden").keep)
        self.assertFalse(classify("China state newspaper blasts calls to slow AI").keep)

    def test_previously_selected_false_positive_is_removed(self):
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        previous = [{"title": "Chubu says its president to resign, nuclear restart application withdrawn over data scandal",
                     "url": "https://www.reuters.com/world/example-2026-09-14/",
                     "published_dt": now - timedelta(hours=2), "region": "Asia Pacific",
                     "topic": "power.change"}]
        current, history, audit = select([], previous, now)
        self.assertEqual(current, [])
        self.assertEqual(history, [])
        self.assertEqual(audit[0]["reason"], "corporate_leadership_not_national_power")


if __name__ == "__main__":
    unittest.main()
