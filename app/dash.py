#!/usr/bin/env python3
"""Touchscreen dashboard: the maintenance loop plus both Claude profiles. Serves 127.0.0.1 only (never the network).

Reads: the loop ledger + event log, ponytail's per-task cost files, the Claude session transcripts of each profile.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).parent
sys.path.insert(0, str(APP))
import costs  # noqa: E402

HOME = Path.home()
PROFILES = {"work": HOME / ".claude-profiles" / "work", "personal": HOME / ".claude-profiles" / "personal"}
EVENTS = Path(os.environ.get("MAINT_EVENTS", HOME / "maint" / "events.jsonl"))
BAND = HOME / ".config" / "ponytail" / "band"
PORT = 8787
STALE_S = 20 * 60        # a 'started' event with no end after this long is a crashed run, not live work
ACTIVE_S = 90            # transcript touched this recently = a session is working right now


# ---- pure helpers (unit-tested) ----------------------------------------------------------------
def tool_line(name, inp):
    inp = inp or {}
    if name == "Bash":
        cmd = (inp.get("command") or "").strip()
        return "$ " + (cmd.splitlines()[0] if cmd else "")[:80]
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"{name} {os.path.basename(inp.get('file_path') or inp.get('notebook_path') or '')}"
    if name in ("Grep", "Glob"):
        return f"Search {inp.get('pattern', '')}"[:80]
    if name in ("Agent", "Task"):
        return "Delegating: " + (inp.get("description") or "")[:70]
    if name == "Skill":
        return f"Skill {inp.get('skill', '')}"
    if name.startswith("mcp__"):
        return name.split("__")[-1].replace("_", " ")
    return name


def prompt_text(content):
    """User message content (str or blocks) -> first line of its text, '' for tool results."""
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    t = (content or "").strip()
    if not t or t.startswith("<"):  # system reminders / command wrappers are not requests
        return ""
    return t.splitlines()[0][:110]


def local_day(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().date().isoformat()


def parse_lines(lines, acc):
    """Fold transcript lines into acc: day -> {turns, in, cached, out, tools}. Returns recent (ts, text) events."""
    evs = []
    for line in lines:
        try:
            d = json.loads(line)
            ts = d["timestamp"]
        except (ValueError, KeyError, TypeError):
            continue
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            day = acc.setdefault(local_day(ts), {"turns": 0, "in": 0, "cached": 0, "out": 0, "tools": 0})
            u = m.get("usage") or {}
            day["turns"] += 1
            day["in"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            day["cached"] += u.get("cache_read_input_tokens") or 0
            day["out"] += u.get("output_tokens") or 0
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    day["tools"] += 1
                    evs.append((ts, tool_line(b.get("name", "?"), b.get("input"))))
        elif d.get("type") == "user":
            t = prompt_text(m.get("content"))
            if t:
                evs.append((ts, "Request: " + t))
    return evs


def hourly(items, now, hours=24):
    """items: (aware datetime, profile, usd) -> one bucket per local hour, oldest first."""
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    out = [{"t": (start + timedelta(hours=i)).isoformat(timespec="minutes"), "work": 0.0, "personal": 0.0}
           for i in range(hours)]
    for dt, prof, usd in items:
        i = int((dt.astimezone() - start).total_seconds() // 3600)
        if 0 <= i < hours and prof in ("work", "personal"):
            out[i][prof] += usd
    return out


def open_work(evs, now_ts):
    """Start events with no matching end, newer than STALE_S -> what is running right now."""
    ended = {e["id"] for e in evs if e.get("phase") == "end"}
    return [e for e in evs if e.get("phase") == "start" and e["id"] not in ended and now_ts - e["ts"] < STALE_S]


# ---- data sources ------------------------------------------------------------------------------
_tcache = {}  # path -> {"off": bytes consumed, "days": acc}


def transcripts(profile):
    return sorted((PROFILES[profile] / "projects").glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)


def fold_file(path):
    """Incremental: only the bytes appended since last poll are parsed."""
    st = path.stat()
    c = _tcache.get(path)
    if not c or st.st_size < c["off"]:
        c = _tcache[path] = {"off": 0, "days": {}}
    if st.st_size > c["off"]:
        with path.open("rb") as f:
            f.seek(c["off"])
            data = f.read()
        end = data.rfind(b"\n") + 1  # never parse a half-written line
        parse_lines(data[:end].decode("utf-8", "replace").splitlines(), c["days"])
        c["off"] += end
    return c["days"]


def tail_events(path, limit=8):
    size = path.stat().st_size
    with path.open("rb") as f:
        f.seek(max(0, size - 80_000))
        data = f.read().decode("utf-8", "replace").splitlines()
    if size > 80_000:  # the read started mid-file, so its first line is cut in half
        data = data[1:]
    return parse_lines(data, {})[-limit:]


def read_events():
    try:
        return [json.loads(l) for l in EVENTS.read_text().splitlines()[-700:] if l.strip()]
    except (OSError, ValueError):
        return []


def band_items(prefix_to_profile):
    """Ponytail per-task cost rows, only for sessions that have a transcript (so loop agents are not double counted)."""
    out = []
    for f in BAND.glob("*.csv"):
        try:
            for r in csv.DictReader(f.open()):
                prof = prefix_to_profile.get(r["key"].split("-")[0])
                if prof:
                    out.append((datetime.strptime(r["started"], "%Y-%m-%d %H:%M").astimezone(), prof, float(r["cost_usd"] or 0)))
        except (OSError, KeyError, ValueError):
            continue
    return out


def system():
    def first(p, default=0.0):
        try:
            return float(Path(p).read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return default
    mem = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines()[:5]}
    disk = shutil.disk_usage("/")
    return {"temp": first("/sys/class/thermal/thermal_zone0/temp") / 1000, "load": os.getloadavg()[0],
            "mem_pct": round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"])), "disk_pct": round(100 * disk.used / disk.total),
            "uptime_h": round(first("/proc/uptime") / 3600, 1)}


_svc = {"t": 0, "v": "unknown"}


REMOTES = {"claude-remote": "personal", "claude-remote-work": "work"}


def remote_state():
    """'active' when both Remote Control devices (personal for the phone, work for Claude Desktop) are up."""
    if time.time() - _svc["t"] > 15:
        bad = []
        for unit, label in REMOTES.items():
            try:
                v = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True,
                                   text=True, timeout=5).stdout.strip() or "unknown"
            except Exception:
                v = "unknown"
            if v != "active":
                bad.append(f"{label} {v}")
        _svc["v"], _svc["t"] = ", ".join(bad) or "active", time.time()
    return _svc["v"]


# ---- the state the screen polls ------------------------------------------------------------------
def build_state():
    now = datetime.now().astimezone()
    today, now_ts = now.date().isoformat(), time.time()
    ledger = costs.read(APP / "ledger.csv")
    prof = {}
    prefix = {}
    ev_rows, active = [], []
    for name in PROFILES:
        files = transcripts(name) if (PROFILES[name] / "projects").exists() else []
        agg = {"turns": 0, "in": 0, "cached": 0, "out": 0, "tools": 0}
        sessions, last = 0, 0.0
        for p in files:
            prefix[p.stem.split("-")[0]] = name
            day = fold_file(p).get(today)
            if day:
                sessions += 1
                for k in agg:
                    agg[k] += day[k]
            mt = p.stat().st_mtime
            last = max(last, mt)
            if now_ts - mt < 7200:
                ev_rows += [{"ts": datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp(), "src": name, "text": x, "ok": True}
                            for t, x in tail_events(p)]
            if now_ts - mt < ACTIVE_S:
                evs = tail_events(p, 40)
                req = next((x for _, x in reversed(evs) if x.startswith("Request: ")), "")
                step = next((x for _, x in reversed(evs) if not x.startswith("Request: ")), "thinking…")
                active.append({"src": name, "text": req[9:] or "working", "step": step, "since": mt})
        prof[name] = {**agg, "sessions": sessions, "last": last, "usd": 0.0, "calls": 0,
                      "active": any(a["src"] == name for a in active)}

    # loop (runs under the work profile): ledger rows + live events
    items = []
    for r in ledger:
        dt = datetime.fromisoformat(r["ts"]).astimezone()
        items.append((dt, "work", r["usd"]))
        if dt.date().isoformat() == today:
            prof["work"]["in"] += r["input"] + r["cache_write"]
            prof["work"]["cached"] += r["cache_read"]
            prof["work"]["out"] += r["output"]
            prof["work"]["turns"] += r["turns"]
            prof["work"]["calls"] += 1
    items += band_items(prefix)
    for dt, p, usd in items:
        if dt.date().isoformat() == today and p in prof:
            prof[p]["usd"] += usd
    if ledger:
        prof["work"]["last"] = max(prof["work"]["last"], datetime.fromisoformat(ledger[-1]["ts"]).timestamp())

    evs = read_events()
    first = min((e["ts"] for e in evs), default=float("inf"))  # before live events existed, the ledger is the history
    for r in ledger[-40:]:
        ts = datetime.fromisoformat(r["ts"]).timestamp()
        if ts < first:
            ev_rows.append({"ts": ts, "src": "loop", "text": f"{r['task']} · ${r['usd']:.3f} · {int(r['turns'])} turns", "ok": True})
    for e in evs:
        if e.get("phase") in ("done", "end"):
            ev_rows.append({"ts": e["ts"], "src": "loop", "text": e["text"], "ok": e.get("ok", True)})
    what = {"agent": "agent call in progress", "scan": "checking PRs and CI", "run": "loop run in progress"}
    live = [{"src": "loop", "text": e["text"], "step": what.get(e["kind"], "running"), "since": e["ts"]}
            for e in open_work(evs, now_ts)]
    ev_rows.sort(key=lambda e: -e["ts"])
    runs = [e for e in evs if e.get("kind") == "end" and e["text"].split(" run ")[0] in ("gate", "full", "dbx")]
    tot = {k: sum(prof[p][k] for p in prof) for k in ("in", "cached", "out", "turns", "usd", "tools", "calls")}
    return {"now": now_ts, "today": today, "total": tot, "profiles": prof, "now_working": live + active,
            "hourly": hourly(items, now), "events": ev_rows[:60], "system": system(), "remote": remote_state(),
            "last_run": ({"ts": runs[-1]["ts"], "ok": runs[-1].get("ok", True), "text": runs[-1]["text"]} if runs else None)}


_cache = {"t": 0, "v": None}
_lock = threading.Lock()


def state():
    with _lock:  # one computation per 2 seconds, however many pages are open
        if time.time() - _cache["t"] > 2:
            _cache["v"], _cache["t"] = json.dumps(build_state()).encode(), time.time()
        return _cache["v"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            body, ctype = state(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = (APP / "index.html").read_bytes(), "text/html; charset=utf-8"
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
