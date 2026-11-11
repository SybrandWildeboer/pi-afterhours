import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_leaks  # noqa: E402
import dash  # noqa: E402

NOW = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
LEDGER_HEAD = "ts,run_id,mode,task,model,usd,turns,input,output,cache_write,cache_read\n"


class Isolated:
    """Point the dashboard at an empty temp world so tests never read the real home folder."""

    def __init__(self, ledger_rows="", make_profiles=("work", "personal")):
        self.ledger_rows, self.make_profiles = ledger_rows, make_profiles

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (dash.PROFILES, dash.EVENTS, dash.APP, dash.BAND)
        dash.PROFILES = {n: d / n for n in ("work", "personal")}
        for n in self.make_profiles:
            (d / n / "projects").mkdir(parents=True)
        dash.EVENTS, dash.APP, dash.BAND = d / "events.jsonl", d, d / "band"
        if self.ledger_rows:
            (d / "ledger.csv").write_text(LEDGER_HEAD + self.ledger_rows)
        return self

    def __exit__(self, *a):
        dash.PROFILES, dash.EVENTS, dash.APP, dash.BAND = self.saved
        self.tmp.cleanup()


class Demo(unittest.TestCase):
    def test_demo_state_has_same_keys_as_real_state(self):
        with Isolated():
            real = dash.build_state()
        demo = dash.demo_state(NOW)
        self.assertEqual(set(demo), set(real))
        self.assertEqual(set(demo["total"]), set(real["total"]))
        for name in real["profiles"]:
            self.assertEqual(set(demo["profiles"][name]), set(real["profiles"][name]))

    def test_demo_state_is_deterministic_and_serializable(self):
        self.assertEqual(json.dumps(dash.demo_state(NOW)), json.dumps(dash.demo_state(NOW)))

    def test_demo_shows_both_profiles_working(self):
        demo = dash.demo_state(NOW)
        self.assertTrue(demo["has_cost"])
        self.assertTrue(all(p["active"] for p in demo["profiles"].values()))
        self.assertEqual(len(demo["hourly"]), 24)
        self.assertGreaterEqual(len(demo["events"]), 10)
        self.assertEqual({w["src"] for w in demo["now_working"]}, {"work", "personal"})

    def test_demo_contains_nothing_private(self):  # also runs with the owner's real terms when .leakcheck-terms exists
        text = json.dumps(dash.demo_state(NOW))
        self.assertEqual(check_no_leaks.scan_text(text, check_no_leaks.load_terms(ROOT)), [])


class Real(unittest.TestCase):
    def test_no_cost_data_sets_has_cost_false(self):
        with Isolated():
            self.assertIs(dash.build_state()["has_cost"], False)

    def test_a_ledger_row_sets_has_cost_true(self):
        row = f"{datetime.now(timezone.utc).isoformat()},r1,full,gate,haiku,0.005,4,10,300,4000,17000\n"
        with Isolated(ledger_rows=row):
            state = dash.build_state()
        self.assertIs(state["has_cost"], True)
        self.assertGreater(state["total"]["usd"], 0)

    def test_missing_profile_dir_does_not_crash(self):  # a friend whose layout differs
        with Isolated(make_profiles=("work",)):
            state = dash.build_state()
        self.assertEqual(set(state["profiles"]), {"work", "personal"})

    def test_page_knows_about_missing_cost(self):
        self.assertIn("has_cost", (ROOT / "app" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
