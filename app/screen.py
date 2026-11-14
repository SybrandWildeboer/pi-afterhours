#!/usr/bin/env python3
"""Screen manager for the touchscreen: dims in the evening, turns the screen off at night and after
inactivity, and wakes it on a tap. The Pi keeps running; only the backlight changes.

Runs as maint-screen.service. Settings live in screen.json (edited from the dashboard's settings
menu); the current state goes to screen-state.json for the dashboard. Standard library only.

    python3 app/screen.py            # run the loop
    python3 app/screen.py --once     # print the decision for now and exit
"""
import json
import os
import select
import sys
import time
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent
SETTINGS = Path(os.environ.get("SCREEN_SETTINGS", APP / "screen.json"))
STATE = Path(os.environ.get("SCREEN_STATE", APP / "screen-state.json"))
COMMAND = Path(os.environ.get("SCREEN_COMMAND", APP / "screen-cmd.json"))
BACKLIGHT_ROOT = Path(os.environ.get("SCREEN_BACKLIGHT_ROOT", "/sys/class/backlight"))
INPUT_DEVICES = Path("/proc/bus/input/devices")

DEFAULTS = {
    "day_brightness": 0.5,    # share of the panel's maximum, 0-1
    "dim_brightness": 0.15,   # in the evening, before quiet hours
    "dim_from": "20:00",
    "quiet_from": "22:00",    # screen off; a tap wakes it for wake_minutes
    "quiet_to": "07:00",
    "idle_minutes": 60,       # off after this long without input; 0 = never
    "wake_minutes": 2,        # how long a tap keeps the screen on during quiet hours
}
SKIP_DEVICES = ("pwr_button", "hdmi")  # these send events that are not a person at the screen


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(now_min, start, end):
    """Whether now (minutes since midnight) is in [start, end), a window that may cross midnight."""
    s, e = minutes(start), minutes(end)
    return s <= now_min < e if s <= e else now_min >= s or now_min < e


def load_settings(path=None):
    try:
        raw = json.loads(Path(path or SETTINGS).read_text())
    except (OSError, ValueError):
        raw = {}
    return load_settings_from(raw)


def load_settings_from(raw):
    """Defaults overlaid with the valid keys of raw, clamped to safe values."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    for k, v in raw.items():
        want = (int, float) if isinstance(DEFAULTS.get(k), (int, float)) else str
        if k in DEFAULTS and isinstance(v, want) and not isinstance(v, bool):
            out[k] = v
    for k in ("day_brightness", "dim_brightness"):
        out[k] = min(1.0, max(0.02, float(out[k])))  # never 0: "off" is a mode, not a brightness
    for k in ("dim_from", "quiet_from", "quiet_to"):
        try:
            minutes(out[k])
        except (ValueError, AttributeError):
            out[k] = DEFAULTS[k]
    out["idle_minutes"] = max(0, int(out["idle_minutes"]))
    out["wake_minutes"] = max(1, int(out["wake_minutes"]))
    return out


def decide(now, last_input, cfg, forced_off_at=0.0):
    """(mode, level): mode is day | dim | quiet | idle | off-now; level is the 0-1 brightness, 0 for off.

    now and last_input are epoch seconds; local time decides the windows. A tap after "off now" or
    after the screen went off counts as input, so last_input > forced_off_at wakes it again.
    """
    since = now - last_input
    if forced_off_at and last_input <= forced_off_at:
        return "off-now", 0.0
    local = datetime.fromtimestamp(now)
    now_min = local.hour * 60 + local.minute
    if in_window(now_min, cfg["quiet_from"], cfg["quiet_to"]):
        if since < cfg["wake_minutes"] * 60:
            return "dim", cfg["dim_brightness"]
        return "quiet", 0.0
    if cfg["idle_minutes"] and since >= cfg["idle_minutes"] * 60:
        return "idle", 0.0
    if in_window(now_min, cfg["dim_from"], cfg["quiet_from"]):
        return "dim", cfg["dim_brightness"]
    return "day", cfg["day_brightness"]


def backlight():
    found = sorted(BACKLIGHT_ROOT.glob("*")) if BACKLIGHT_ROOT.exists() else []
    return found[0] if found else None


def set_level(bl, level):
    """Write a 0-1 level as the panel's raw brightness. Returns the raw value written."""
    top = int((bl / "max_brightness").read_text())
    raw = 0 if level <= 0 else max(1, round(top * level))
    if int((bl / "brightness").read_text()) != raw:
        (bl / "brightness").write_text(str(raw))
    return raw


def input_paths(text):
    """/dev/input/eventN of every keyboard, mouse or touch device, from /proc/bus/input/devices."""
    paths = []
    for block in text.strip().split("\n\n"):
        name = next((l.split("=", 1)[1].strip('"') for l in block.splitlines() if l.startswith("N: Name=")), "")
        handlers = next((l.split("=", 1)[1].split() for l in block.splitlines() if l.startswith("H: Handlers=")), [])
        if any(s in name.lower() for s in SKIP_DEVICES):
            continue
        if any(h.startswith(("mouse", "kbd")) for h in handlers):
            paths += [f"/dev/input/{h}" for h in handlers if h.startswith("event")]
    return paths


def open_inputs():
    fds = []
    try:
        text = INPUT_DEVICES.read_text()
    except OSError:
        return fds
    for p in input_paths(text):
        try:
            fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass  # not in the input group, or the device went away
    return fds


def read_command(last_seen):
    """A command from the dashboard: {"action": "off" | "wake", "at": epoch}. Returns (action, at)."""
    try:
        c = json.loads(COMMAND.read_text())
        at = float(c.get("at", 0))
        if at > last_seen and c.get("action") in ("off", "wake"):
            return c["action"], at
    except (OSError, ValueError, TypeError):
        pass
    return None, last_seen


def write_state(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(STATE)


def run():
    bl = backlight()
    if bl is None:
        print("screen: no backlight under", BACKLIGHT_ROOT, file=sys.stderr)
        return 1
    fds, reopened = open_inputs(), time.time()
    last_input, forced_off_at, cmd_seen = time.time(), 0.0, time.time()
    while True:
        ready = select.select(fds, [], [], 1.0)[0] if fds else (time.sleep(1.0) or [])
        for fd in ready:
            try:
                while os.read(fd, 4096):
                    pass
            except BlockingIOError:
                pass
            except OSError:
                pass
            last_input = time.time()
        action, cmd_seen = read_command(cmd_seen)
        if action == "off":
            forced_off_at = time.time()
        elif action == "wake":
            last_input = time.time()
        if time.time() - reopened > 60:  # pick up a keyboard plugged in later
            for fd in fds:
                os.close(fd)
            fds, reopened = open_inputs(), time.time()
        cfg = load_settings()
        mode, level = decide(time.time(), last_input, cfg, forced_off_at)
        if last_input > forced_off_at:
            forced_off_at = 0.0
        raw = set_level(bl, level)
        write_state({"mode": mode, "on": level > 0, "level": level, "raw": raw,
                     "last_input": last_input, "settings": cfg, "updated": time.time()})


if __name__ == "__main__":
    if "--once" in sys.argv:
        cfg = load_settings()
        print(json.dumps({"decision": decide(time.time(), time.time(), cfg), "settings": cfg, "backlight": str(backlight())}))
        sys.exit(0)
    sys.exit(run())
