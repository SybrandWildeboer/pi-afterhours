#!/usr/bin/env python3
"""Maintenance loop entry point. Dry-run unless --live is given.

  run.py gate            read Slack, answer requests (spec / scan now)         cron: every 30 min
  run.py full            gate + repos (PRs, CI, audits)                        cron: hourly
  run.py dbx             Databricks health check                               cron: daily
  run.py spec "<idea>"   print a spec for an idea (no Slack, no state)
  run.py cost            tokens and estimated dollars per run, plus per-day totals
"""
import fcntl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import costs
import events
import flows
import fmt
import loop
import rules
import state
from llm import Agents

ROOT = Path(__file__).parent


def main(argv):
    live = "--live" in argv
    args = [a for a in argv if a != "--live"]
    mode = args[0] if args else "gate"
    if mode == "cost":
        return print(costs.table(costs.read(ROOT / "ledger.csv")))
    if mode in loop.MODES and loop.paused():  # paused from the dashboard: scheduled runs start nothing
        print(f"[paused] the loop is paused from the dashboard: {mode} run skipped")
        return
    try:
        cfg = config.load(ROOT / "config.json")
    except config.ConfigError as e:
        sys.exit(f"config error: {e}")
    with open(ROOT / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another run is active, skipping")
            return
        S = state.load(ROOT / "state.json")
        now = datetime.now(timezone.utc)
        ctx = flows.Ctx(cfg, S, live, Agents(cfg, ROOT, f"{now:%Y%m%dT%H%M}-{mode}", mode), now)
        t0, eid = time.time(), events.begin("run", f"{mode} run")
        try:
            if mode == "gate":
                forced = flows.safe_gate(ctx)
                if forced:  # an explicit "scan now" request
                    flows.full(ctx, forced)
                else:
                    ctx.report("🛠 *Maintenance*")  # only has lines if the gate itself failed
            elif mode == "full":
                forced = flows.safe_gate(ctx)  # first step of every run: read the last post and what you wrote since
                if ctx.idle and not forced and not flows.sweep_due(ctx):
                    events.emit("run", "idle: last post said no further action, nothing new from you")
                    print("[idle] last post ended with 'no further action' and you wrote nothing new: stopping")
                else:
                    flows.full(ctx, forced)
                    S["last_sweep"] = str(now.astimezone().date())
            elif mode == "dbx":
                flows.dbx_flow(ctx)
                flows.cost_rollup(ctx)
            elif mode == "spec":
                print(fmt.fmt_spec(ctx.ag.spec(" ".join(args[1:]))))
            else:
                sys.exit(__doc__)
        finally:  # even a crash must not lose what was already posted, or the next run reposts it
            events.end(eid, f"{mode} run {'done' if sys.exc_info()[0] is None else 'crashed'} in {time.time() - t0:.0f}s",
                       ok=sys.exc_info()[0] is None)
            if live:
                rules.prune(S, ctx.now)
                state.save(ROOT / "state.json", S)


if __name__ == "__main__":
    main(sys.argv[1:])
