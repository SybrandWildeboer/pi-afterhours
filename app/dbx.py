"""Daily read-only Databricks health check. Only list/get CLI calls; no LLM, nothing can change."""
import time

from util import jsh

BAD_RUN = {"FAILED", "TIMEDOUT", "INTERNAL_ERROR"}


def _j(profile, *args):
    return jsh(["databricks", *args, "--profile", profile, "-o", "json"], timeout=90) or []


def _jobs(p, now_ms):
    failed = {}
    for r in _j(p, "jobs", "list-runs", "--completed-only", "--limit", "100"):
        if r.get("end_time", 0) >= now_ms - 86_400_000 and (r.get("state") or {}).get("result_state") in BAD_RUN:
            failed.setdefault(r.get("run_name") or r.get("job_id"), []).append(r)
    out = []
    for name, rs in failed.items():
        last = rs[0]
        why = (last["state"].get("state_message") or last["state"]["result_state"])[:90]
        out.append(f"❌ {p}: job '{name}' failed {len(rs)}× in 24h, last: {why} {last.get('run_page_url', '')}")
    return out


def _apps(p, _):
    out = []
    for a in _j(p, "apps", "list"):
        app, comp = (a.get("app_status") or {}).get("state"), (a.get("compute_status") or {}).get("state")
        if comp not in (None, "ACTIVE", "STOPPED", "STARTING") or app not in (None, "RUNNING", "DEPLOYING", "STARTING"):
            out.append(f"❌ {p}: app '{a['name']}' unhealthy (app={app}, compute={comp})")
    return out


def _pipelines(p, _):
    out = []
    for pl in _j(p, "pipelines", "list-pipelines"):
        upd = (pl.get("latest_updates") or [{}])[0].get("state")
        if pl.get("state") == "FAILED" or upd == "FAILED":
            out.append(f"❌ {p}: pipeline '{pl['name']}' failed (state={pl.get('state')}, last update={upd})")
    return out


def _compute(p, _):
    out = []
    for w in _j(p, "warehouses", "list"):
        if w.get("state") == "RUNNING" and not w.get("auto_stop_mins"):
            out.append(f"💸 {p}: SQL warehouse '{w['name']}' is running with no auto-stop")
    for c in _j(p, "clusters", "list"):
        if c.get("state") == "RUNNING" and c.get("cluster_source") != "JOB" and not c.get("autotermination_minutes"):
            out.append(f"💸 {p}: cluster '{c['cluster_name']}' is running with no auto-termination")
    return out


def check(profile, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    try:
        _j(profile, "current-user", "me")
    except Exception as e:  # expired or missing login: report, never try to log in
        return [f"🔑 Databricks profile {profile} no longer authenticates: {str(e)[-110:]}. "
                f"Run: databricks auth login --profile {profile}"]
    lines = []
    for name, fn in (("jobs", _jobs), ("apps", _apps), ("pipelines", _pipelines), ("compute", _compute)):
        try:
            lines += fn(profile, now_ms)
        except Exception as e:
            lines.append(f"⚠️ {profile}: {name} check failed: {str(e)[-90:]}")
    return lines
