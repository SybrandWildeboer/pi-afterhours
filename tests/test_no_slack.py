import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import flows  # noqa: E402
import state  # noqa: E402


class Agents:
    """Blows up if Slack is touched: with an empty channel nothing may read or post."""
    stats = {"gate": {"calls": 1, "usd": 0.005, "input": 10, "output": 5, "cache_write": 0, "cache_read": 100, "turns": 2}}

    def gate(self, *a):
        raise AssertionError("gate must not run without Slack")

    def post(self, *a):
        raise AssertionError("post must not run without Slack")


def make_ctx(channel="", last_ts="1"):
    cfg = {**config.DEFAULTS, "projects_root": "/x", "channel": channel,
           "repos": [{"name": "r", "path": "r", "gh": "o/r"}]}
    S = state.load(Path("/nonexistent"))
    S["last_ts"] = last_ts
    return flows.Ctx(cfg, S, True, Agents(), datetime.now(timezone.utc))


class SlackOptional(unittest.TestCase):
    def test_slack_enabled_follows_the_channel(self):
        self.assertFalse(flows.slack_enabled({"channel": ""}))
        self.assertFalse(flows.slack_enabled({}))
        self.assertTrue(flows.slack_enabled({"channel": "C123"}))

    def test_gate_skipped_without_channel(self):
        c = make_ctx()
        self.assertEqual(flows.safe_gate(c), [])
        self.assertFalse(c.idle)
        self.assertEqual(c.lines, [])  # and no "Slack check failed" note either

    def test_post_goes_to_stdout(self):
        c, buf = make_ctx(), io.StringIO()
        with redirect_stdout(buf):
            c.post("hello team")
        self.assertIn("hello team", buf.getvalue())
        self.assertIn("this run", buf.getvalue())  # the cost footer is still shown

    def test_full_pass_runs_without_slack(self):
        c, buf, real = make_ctx(), io.StringIO(), flows.scan_repo
        flows.scan_repo = lambda ctx, repo, force: ctx.note(f"found something in {repo['name']}")
        try:
            with redirect_stdout(buf):
                flows.full(c, ())
        finally:
            flows.scan_repo = real
        self.assertIn("found something in r", buf.getvalue())
        self.assertTrue(c.S["posted"])  # reported lines still count as seen

    def test_gate_runs_when_channel_set(self):
        with self.assertRaises(AssertionError):
            flows.gate(make_ctx(channel="C123", last_ts="1"))


if __name__ == "__main__":
    unittest.main()
