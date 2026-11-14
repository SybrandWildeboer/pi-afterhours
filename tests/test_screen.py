import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import dash  # noqa: E402
import screen  # noqa: E402

CFG = screen.load_settings_from({})  # the defaults: dim 20:00, off 22:00-07:00, idle 60 min, wake 2 min


def at(hhmm):
    """Epoch seconds for today's local hh:mm (the windows use local time)."""
    h, m = map(int, hhmm.split(":"))
    return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


class Windows(unittest.TestCase):
    def test_a_window_may_cross_midnight(self):
        self.assertTrue(screen.in_window(23 * 60, "22:00", "07:00"))
        self.assertTrue(screen.in_window(3 * 60, "22:00", "07:00"))
        self.assertFalse(screen.in_window(7 * 60, "22:00", "07:00"))
        self.assertTrue(screen.in_window(21 * 60, "20:00", "22:00"))
        self.assertFalse(screen.in_window(22 * 60, "20:00", "22:00"))


class Decide(unittest.TestCase):
    def test_day_dim_and_quiet(self):
        self.assertEqual(screen.decide(at("12:00"), at("11:59"), CFG), ("day", CFG["day_brightness"]))
        self.assertEqual(screen.decide(at("21:00"), at("20:59"), CFG), ("dim", CFG["dim_brightness"]))
        self.assertEqual(screen.decide(at("23:00"), at("21:30"), CFG), ("quiet", 0.0))

    def test_a_tap_at_night_wakes_the_screen_dimmed_for_a_short_while(self):
        self.assertEqual(screen.decide(at("23:00"), at("23:00") - 30, CFG), ("dim", CFG["dim_brightness"]))
        self.assertEqual(screen.decide(at("23:00"), at("23:00") - 3 * 60, CFG), ("quiet", 0.0))

    def test_off_after_an_hour_without_input(self):
        self.assertEqual(screen.decide(at("15:00"), at("14:01"), CFG)[0], "day")
        self.assertEqual(screen.decide(at("15:00"), at("13:59"), CFG), ("idle", 0.0))
        never = screen.load_settings_from({"idle_minutes": 0})
        self.assertEqual(screen.decide(at("15:00"), at("08:00"), never)[0], "day")

    def test_off_now_holds_until_the_next_input(self):
        now = at("12:00")
        self.assertEqual(screen.decide(now, now - 10, CFG, forced_off_at=now - 5), ("off-now", 0.0))
        self.assertEqual(screen.decide(now, now - 1, CFG, forced_off_at=now - 5)[0], "day")


class Settings(unittest.TestCase):
    def test_bad_values_fall_back_or_are_clamped(self):
        s = screen.load_settings_from({"day_brightness": 7, "dim_brightness": 0, "quiet_from": "late",
                                       "idle_minutes": -5, "wake_minutes": 0, "unknown": 1, "dim_from": True})
        self.assertEqual(s["day_brightness"], 1.0)
        self.assertEqual(s["dim_brightness"], 0.02)   # never 0: off is a mode
        self.assertEqual(s["quiet_from"], "22:00")
        self.assertEqual(s["dim_from"], "20:00")
        self.assertEqual((s["idle_minutes"], s["wake_minutes"]), (0, 1))
        self.assertNotIn("unknown", s)


class Inputs(unittest.TestCase):
    def test_keyboards_mice_and_touch_count_power_button_and_hdmi_do_not(self):
        text = "\n\n".join([
            'N: Name="USB Keyboard"\nH: Handlers=sysrq kbd leds event0',
            'N: Name="USB Mouse"\nH: Handlers=mouse0 event1',
            'N: Name="pwr_button"\nH: Handlers=kbd event5',
            'N: Name="Goodix Capacitive TouchScreen"\nH: Handlers=kbd mouse1 event6',
            'N: Name="vc4-hdmi-0"\nH: Handlers=kbd event7',
            'N: Name="vc4-hdmi-0 HDMI Jack"\nH: Handlers=event8',
        ])
        self.assertEqual(screen.input_paths(text), ["/dev/input/event0", "/dev/input/event1", "/dev/input/event6"])


class Backlight(unittest.TestCase):
    def test_levels_map_to_the_panel_range_and_zero_is_off(self):
        with tempfile.TemporaryDirectory() as d:
            bl = Path(d)
            (bl / "max_brightness").write_text("31")
            (bl / "brightness").write_text("15")
            self.assertEqual(screen.set_level(bl, 0.5), 16)
            self.assertEqual(screen.set_level(bl, 0.01), 1)    # a tiny level is still on
            self.assertEqual(screen.set_level(bl, 0.0), 0)
            self.assertEqual((bl / "brightness").read_text(), "0")


class Endpoints(unittest.TestCase):
    """The settings menu's endpoints, against a real server on a free loopback port."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (screen.SETTINGS, screen.STATE, screen.COMMAND, dash.DEMO)
        screen.SETTINGS, screen.STATE, screen.COMMAND = d / "screen.json", d / "screen-state.json", d / "screen-cmd.json"
        dash.DEMO = True  # power actions must never run in tests
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        screen.SETTINGS, screen.STATE, screen.COMMAND, dash.DEMO = self.saved
        self.tmp.cleanup()

    def post(self, path, body, header=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Afterhours": "1"} if header else {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_settings_are_validated_and_saved(self):
        code, body = self.post("/api/screen", {"settings": {"day_brightness": 0.8, "quiet_from": "23:00"}})
        self.assertEqual(code, 200)
        saved = json.loads(screen.SETTINGS.read_text())
        self.assertEqual((saved["day_brightness"], saved["quiet_from"]), (0.8, "23:00"))
        self.assertEqual(body["screen"]["settings"]["quiet_from"], "23:00")
        self.assertEqual(self.post("/api/screen", {"settings": {"rm -rf": 1}})[0], 400)

    def test_screen_off_now_is_a_command_for_the_screen_service(self):
        self.assertEqual(self.post("/api/screen", {"action": "off"})[0], 200)
        self.assertEqual(json.loads(screen.COMMAND.read_text())["action"], "off")
        action, _ = screen.read_command(0)
        self.assertEqual(action, "off")

    def test_requests_without_the_page_header_are_refused(self):
        self.assertEqual(self.post("/api/screen", {"action": "off"}, header=False)[0], 403)
        self.assertEqual(self.post("/api/power", {"action": "reboot"}, header=False)[0], 403)
        self.assertFalse(screen.COMMAND.exists())

    def test_power_actions_are_allowlisted_and_off_in_demo_mode(self):
        self.assertEqual(self.post("/api/power", {"action": "rm"})[0], 400)
        self.assertEqual(self.post("/api/power", {"action": "poweroff"})[0], 403)  # demo: never runs


if __name__ == "__main__":
    unittest.main()


# ---- the loop card ----------------------------------------------------------------------------------
import loop  # noqa: E402

CRONTAB = """PATH=/usr/bin
# Slack: listen for requests (spec / scan now) every 30 min, 07:00-21:30
*/30 7-21 * * * cd ~/maint/app && python3 run.py gate --live >> run.log 2>&1
# Repos: PRs, failing CI, audits. Hourly on weekdays 08:05-18:05
5 8-18 * * 1-5 cd ~/maint/app && python3 run.py full --live >> run.log 2>&1
10 7 * * 1-5 cd ~/maint/app && python3 run.py dbx --live >> run.log 2>&1
"""


class LoopSchedule(unittest.TestCase):
    def test_crontab_entries_with_their_comment_and_live_flag(self):
        parts = loop.parse_crontab(CRONTAB)
        self.assertEqual([(p["mode"], p["cron"], p["live"]) for p in parts],
                         [("gate", "*/30 7-21 * * *", True), ("full", "5 8-18 * * 1-5", True), ("dbx", "10 7 * * 1-5", True)])
        self.assertEqual(parts[0]["label"], "listen for requests (spec / scan now) every 30 min, 07:00-21:30")
        self.assertEqual(parts[2]["label"], "")

    def test_next_run(self):
        fri_2140 = datetime(2026, 11, 13, 21, 40)  # a Friday
        self.assertEqual(loop.next_run("*/30 7-21 * * *", fri_2140), datetime(2026, 11, 14, 7, 0))
        self.assertEqual(loop.next_run("5 8-18 * * 1-5", fri_2140), datetime(2026, 11, 16, 8, 5))  # Monday
        self.assertEqual(loop.next_run("10 7 * * 1-5", datetime(2026, 11, 16, 7, 9)), datetime(2026, 11, 16, 7, 10))


class LoopRuns(unittest.TestCase):
    EVENTS = [
        {"ts": 100.0, "source": "loop", "phase": "start", "kind": "run", "id": "a", "text": "gate run"},
        {"ts": 128.0, "source": "loop", "phase": "end", "kind": "end", "id": "a", "text": "gate run done in 28s", "ok": True},
        {"ts": 200.0, "source": "loop", "phase": "start", "kind": "run", "id": "b", "text": "full run"},
        {"ts": 241.0, "source": "loop", "phase": "end", "kind": "end", "id": "b", "text": "full run crashed in 41s", "ok": False},
        {"ts": 300.0, "source": "loop", "phase": "start", "kind": "run", "id": "c", "text": "gate run"},
        {"ts": 310.0, "source": "work", "phase": "start", "kind": "run", "id": "x", "text": "gate run"},  # not the loop
    ]

    def test_runs_pair_start_and_end_and_keep_the_one_still_running(self):
        rs = loop.runs(self.EVENTS)
        self.assertEqual([(r["mode"], r["ok"], r["secs"]) for r in rs], [("gate", True, 28), ("full", False, 41), ("gate", None, None)])

    def test_summary_shows_last_run_per_part_running_and_paused(self):
        with tempfile.TemporaryDirectory() as d:
            saved = loop.PAUSE
            loop.PAUSE = Path(d) / "paused.json"
            try:
                s = loop.summary(self.EVENTS, CRONTAB, now=320.0)
                self.assertEqual(s["running"], {"mode": "gate", "since": 300.0})
                self.assertIs(s["live"], True)
                full = next(p for p in s["parts"] if p["mode"] == "full")
                self.assertEqual(full["last"], {"ts": 200.0, "ok": False, "secs": 41})
                self.assertIsNone(s["paused"])
                loop.set_paused(True)
                self.assertIsNotNone(loop.summary(self.EVENTS, CRONTAB, now=320.0)["paused"])
                loop.set_paused(False)
                self.assertIsNone(loop.paused())
            finally:
                loop.PAUSE = saved

    def test_no_crontab_means_not_scheduled(self):
        s = loop.summary([], "", now=0.0)
        self.assertEqual((s["scheduled"], s["live"], s["parts"]), (False, None, []))


class LoopPauseEndpoint(Endpoints):
    def test_pause_is_refused_in_demo_and_without_the_header(self):
        self.assertEqual(self.post("/api/loop", {"action": "pause"}, header=False)[0], 403)
        self.assertEqual(self.post("/api/loop", {"action": "stop"})[0], 400)
        self.assertEqual(self.post("/api/loop", {"action": "pause"})[0], 403)  # demo mode

    def test_pause_and_resume_write_the_pause_file(self):
        with tempfile.TemporaryDirectory() as d:
            saved = loop.PAUSE
            loop.PAUSE, dash.DEMO = Path(d) / "paused.json", False
            try:
                self.assertEqual(self.post("/api/loop", {"action": "pause"})[0], 200)
                self.assertTrue(loop.PAUSE.exists())
                self.assertEqual(self.post("/api/loop", {"action": "resume"})[0], 200)
                self.assertFalse(loop.PAUSE.exists())
            finally:
                loop.PAUSE, dash.DEMO = saved, True


class RunPy(unittest.TestCase):
    def test_a_paused_loop_skips_scheduled_runs_before_reading_config(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            pause = Path(d) / "paused.json"
            pause.write_text('{"since": 1}')
            env = {**os.environ, "MAINT_PAUSE": str(pause), "MAINT_EVENTS": str(Path(d) / "events.jsonl")}
            for mode in ("gate", "full", "dbx"):
                r = subprocess.run([sys.executable, str(ROOT / "app" / "run.py"), mode], capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"{mode} run skipped", r.stdout)
            self.assertFalse((Path(d) / "events.jsonl").exists())  # nothing started
