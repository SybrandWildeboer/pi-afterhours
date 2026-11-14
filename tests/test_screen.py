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
