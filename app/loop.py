"""The loop as a whole, for the dashboard: its schedule (from the crontab), last and next run per part,
today's tally, and the pause switch. Pure helpers plus a tiny file-based pause. Standard library only."""
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parent
PAUSE = Path(os.environ.get("MAINT_PAUSE", APP / "paused.json"))
MODES = ("gate", "full", "dbx")  # the scheduled parts; spec and cost are manual


# ---- pause ----------------------------------------------------------------------------------------

def paused():
    """{"since": epoch} while paused, else None."""
    try:
        d = json.loads(PAUSE.read_text())
        return {"since": float(d.get("since", 0))}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def set_paused(on):
    if on:
        if not paused():
            tmp = PAUSE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"since": time.time()}))
            tmp.replace(PAUSE)
    else:
        try:
            PAUSE.unlink()
        except FileNotFoundError:
            pass


# ---- schedule -------------------------------------------------------------------------------------

def _field(spec, lo, hi):
    """The set of values a cron field allows: *, */n, a-b, a-b/n, lists, numbers."""
    out = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        step = int(step) if step else 1
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = map(int, rng.split("-"))
        else:
            a = b = int(rng)
        out.update(range(a, b + 1, step))
    return out


def next_run(expr, after):
    """The next datetime after `after` (naive local) that a 5-field cron expression fires, or None within 8 days."""
    m, h, dom, mon, dow = expr.split()
    mins, hours, doms, mons = _field(m, 0, 59), _field(h, 0, 23), _field(dom, 1, 31), _field(mon, 1, 12)
    dows = {d % 7 for d in _field(dow, 0, 7)}  # cron: 0 and 7 are Sunday
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(8 * 24 * 60):
        if (t.minute in mins and t.hour in hours and t.month in mons
                and (t.day in doms if dom != "*" else True)
                and ((t.isoweekday() % 7) in dows if dow != "*" else True)):
            return t
        t += timedelta(minutes=1)
    return None


def parse_crontab(text):
    """One entry per scheduled part: {mode, cron, label, live}. The label is the comment line above the entry."""
    out, comment = [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            comment = s.lstrip("# ").strip()
            continue
        hit = re.search(r"run\.py\s+(\w+)", s)
        fields = s.split()
        if hit and hit.group(1) in MODES and len(fields) > 5:
            out.append({"mode": hit.group(1), "cron": " ".join(fields[:5]),
                        "label": comment.split(":", 1)[-1].strip() if comment else "", "live": "--live" in s})
        comment = ""
    return out


# ---- runs -----------------------------------------------------------------------------------------

def runs(events):
    """Finished and running loop runs from the event log: [{mode, start, end, ok, secs}] oldest first."""
    starts, out = {}, []
    for e in events:
        if e.get("source") != "loop":
            continue
        if e.get("phase") == "start" and e.get("kind") == "run":
            mode = str(e.get("text", "")).split(" ")[0]
            starts[e.get("id")] = {"mode": mode, "start": e["ts"], "end": None, "ok": None, "secs": None}
        elif e.get("phase") == "end" and e.get("id") in starts:
            r = starts.pop(e["id"])
            r.update(end=e["ts"], ok=bool(e.get("ok", True)), secs=round(e["ts"] - r["start"]))
            out.append(r)
    out += list(starts.values())  # still running (or crashed without an end)
    return sorted(out, key=lambda r: r["start"])


def summary(events, crontab_text, now, stale_s=20 * 60):
    """Everything the loop card shows. now is epoch seconds."""
    rs = runs(events)
    running = next((r for r in reversed(rs) if r["end"] is None and now - r["start"] < stale_s), None)
    entries = parse_crontab(crontab_text or "")
    local_now = datetime.fromtimestamp(now)
    day0 = local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    today = [r for r in rs if r["start"] >= day0 and r["end"] is not None]
    parts = []
    for e in entries:
        mine = [r for r in rs if r["mode"] == e["mode"] and r["end"] is not None]
        last = mine[-1] if mine else None
        nxt = next_run(e["cron"], local_now)
        parts.append({"mode": e["mode"], "label": e["label"], "cron": e["cron"],
                      "last": {"ts": last["start"], "ok": last["ok"], "secs": last["secs"]} if last else None,
                      "next": nxt.timestamp() if nxt else None})
    lives = {e["live"] for e in entries}
    return {
        "scheduled": bool(entries),
        "live": True if lives == {True} else False if lives == {False} else None,  # None: mixed or no crontab
        "paused": paused(),
        "running": {"mode": running["mode"], "since": running["start"]} if running else None,
        "parts": parts,
        "today": {"runs": len(today), "failed": sum(1 for r in today if not r["ok"])},
    }
