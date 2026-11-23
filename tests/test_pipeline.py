import os
import unittest
from datetime import date

from worklog_copilot.anonymize import anonymize
from worklog_copilot.parser import parse_date, parse_log
from worklog_copilot.rag import Index
from worklog_copilot.signals import weekly_signals

HERE = os.path.dirname(__file__)


def load():
    with open(os.path.join(HERE, "fixtures", "messy.work.log"), encoding="utf-8") as f:
        return parse_log(f.read(), "alice", "lab/repo", "alice", "messy.work.log")


class ParseDate(unittest.TestCase):
    def test_variants(self):
        cases = {
            "2025.8.22 - 2025.8.25": (date(2025, 8, 22), date(2025, 8, 25)),
            "2025.8.19~20": (date(2025, 8, 19), date(2025, 8, 20)),
            "2025.8.15 & 8.17": (date(2025, 8, 15), date(2025, 8, 17)),
            "2025.08.31-09.01": (date(2025, 8, 31), date(2025, 9, 1)),
            "2025.7.06 (abroad soon)": (date(2025, 7, 6), date(2025, 7, 6)),
            "2026/7/1": (date(2026, 7, 1), date(2026, 7, 1)),
        }
        for raw, (s, e) in cases.items():
            got = parse_date(raw)
            self.assertEqual((got[0], got[1]), (s, e), raw)
            self.assertEqual(got[3], [], raw)

    def test_bad_dates_are_flagged_not_dropped(self):
        for raw in ("2026.7.X", "2026.2.30", "July 1st"):
            start, _, _, issues = parse_date(raw)
            self.assertIsNone(start)
            self.assertTrue(issues)


class ParseLog(unittest.TestCase):
    def setUp(self):
        self.entries = load()

    def test_all_entries_kept(self):
        self.assertEqual(len(self.entries), 4)

    def test_hours_and_sections(self):
        e = self.entries[0]
        self.assertEqual(e.hours, 3.5)
        self.assertEqual(e.todos, ["rerun baseline"])
        self.assertEqual(e.open_questions, [])          # "None" is not a question
        self.assertEqual(e.note, "traveling on 7.16")

    def test_wrapped_line_joins_previous_item(self):
        self.assertEqual(len(self.entries[1].discuss), 1)
        self.assertIn("two jobs", self.entries[1].discuss[0])

    def test_custom_section_kept(self):
        self.assertIn("Current understanding", self.entries[3].other)

    def test_source_line_numbers(self):
        self.assertEqual(self.entries[0].source.line, 3)


class Signals(unittest.TestCase):
    def test_blockers_inside_done_and_discuss(self):
        s = weekly_signals(load(), date(2026, 7, 13), ["alice"])["alice"]
        texts = " ".join(t for t, _ in s.blockers)
        self.assertIn("budget", texts)
        self.assertIn("GPU quota", texts)
        self.assertIn("not sure", texts)

    def test_missing_week_alert(self):
        s = weekly_signals(load(), date(2026, 7, 20), ["alice", "bob"])
        self.assertTrue(any("沒有任何日誌" in a for a in s["alice"].alerts))
        self.assertTrue(any("沒有任何日誌" in a for a in s["bob"].alerts))

    def test_multi_day_entry_counts_each_day(self):
        s = weekly_signals(load(), date(2026, 7, 13), ["alice"])["alice"]
        self.assertEqual(s.logged_days, 3)   # 14, 15, 16


class Rag(unittest.TestCase):
    def test_search_and_not_found(self):
        idx = Index(load())
        hits = idx.search("GPU quota")
        self.assertTrue(hits and "GPU" in hits[0][0].as_text())
        ans = idx.ask("kubernetes helm chart")
        self.assertFalse(ans.found)


class Anonymize(unittest.TestCase):
    def test_names_removed(self):
        out = anonymize(load(), extra_names={"paper A": "a paper"})
        blob = " ".join(e.as_text() for e in out)
        self.assertNotIn("alice", blob.lower())
        self.assertNotIn("traveling", " ".join(e.note for e in out))
        self.assertNotIn("paper A", blob)


if __name__ == "__main__":
    unittest.main()
