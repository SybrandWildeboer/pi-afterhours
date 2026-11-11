"""Token and cost bookkeeping read from ledger.csv. Pure functions plus a small CLI table."""
import csv
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

NUM = ("usd", "turns", "input", "output", "cache_write", "cache_read")


def read(path):
    p = Path(path)
    if not p.exists():
        return []
    rows = list(csv.DictReader(p.open()))
    for r in rows:
        for k in NUM:
            r[k] = float(r.get(k) or 0)
    return rows


def _add(stats, r):
    s = stats.setdefault(r["task"], {"calls": 0, **{k: 0.0 for k in NUM}})
    s["calls"] += 1
    for k in NUM:
        s[k] += r[k]


def since(rows, now, hours=24):
    """Stats per task for the last `hours`."""
    cutoff = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
    stats = {}
    for r in rows:
        if r["ts"] >= cutoff:
            _add(stats, r)
    return stats


def per_run(rows):
    """run_id -> {'ts', 'mode', 'stats'} in the order the runs started."""
    runs = {}
    for r in rows:
        run = runs.setdefault(r["run_id"], {"ts": r["ts"], "mode": r["mode"], "stats": {}})
        _add(run["stats"], r)
    return runs


def totals(stats):
    t = defaultdict(float)
    for s in stats.values():
        for k, v in s.items():
            t[k] += v
    return t


def table(rows, last=20):
    """Per-run table plus per-day totals, for `run.py cost`."""
    out = [f"{'run':<24}{'calls':>6}{'in':>9}{'cached':>10}{'out':>8}{'usd':>9}  tasks"]
    for rid, run in list(per_run(rows).items())[-last:]:
        t = totals(run["stats"])
        tasks = ", ".join(f"{k} ${v['usd']:.3f}" for k, v in run["stats"].items())
        out.append(f"{rid:<24}{int(t['calls']):>6}{int(t['input'] + t['cache_write']):>9}"
                   f"{int(t['cache_read']):>10}{int(t['output']):>8}{t['usd']:>9.4f}  {tasks}")
    days = defaultdict(float)
    for r in rows:
        days[r["ts"][:10]] += r["usd"]
    out += ["", "per day: " + "  ".join(f"{d} ${v:.3f}" for d, v in sorted(days.items())[-7:]),
            f"total: ${sum(days.values()):.3f} over {len(per_run(rows))} runs"]
    return "\n".join(out)
