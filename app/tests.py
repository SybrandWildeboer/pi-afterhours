"""Assert-based self-check: python3 tests.py  (no dependencies)."""
import os
import tempfile

os.environ["MAINT_EVENTS"] = os.path.join(tempfile.mkdtemp(), "events.jsonl")  # never touch the real event log
from datetime import datetime, timedelta, timezone

import fmt
import rules as R
from util import extract_json, fill

CFG = {"max_diff_lines": 400, "protected_paths": ["deploy", "infra", "workflows", "secrets", "prod"]}
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
GREEN = [{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]


def pr(**kw):
    base = {"isDraft": False, "mergeable": "MERGEABLE", "statusCheckRollup": GREEN, "additions": 5,
            "deletions": 2, "files": [{"path": "requirements.txt"}], "title": "Bump x from 1.2.3 to 1.2.4",
            "author": {"login": "app/dependabot"}}
    return {**base, **kw}


# version bumps
assert R.semver_bump("1.2.3", "1.2.4") == "patch"
assert R.semver_bump("1.2.3", "1.3.0") == "minor"
assert R.semver_bump("1.2.3", "2.0.0") == "major"
assert R.semver_bump("0.3.1", "0.4.0") == "major"      # 0.x minor can break
assert R.semver_bump("1.2.3", "1.2.3") == "unknown"
assert R.semver_bump("v1.2.3", "v1.2.9") == "patch"
assert R.title_bump("Bump foo from 1.2.3 to 1.2.4 in /app") == "patch"
assert R.title_bump("Update lockfile") == "unknown"

# check state
assert R.checks_state([]) == "none"
assert R.checks_state(GREEN) == "green"
assert R.checks_state(GREEN + [{"conclusion": "FAILURE"}]) == "red"
assert R.checks_state(GREEN + [{"status": "IN_PROGRESS", "conclusion": ""}]) == "pending"

# merge gate: every blocker must block
assert R.can_merge(pr(), CFG) == (True, "ok")
assert not R.can_merge(pr(isDraft=True), CFG)[0]
assert not R.can_merge(pr(mergeable="CONFLICTING"), CFG)[0]
assert not R.can_merge(pr(statusCheckRollup=[]), CFG)[0]
assert not R.can_merge(pr(additions=300, deletions=200), CFG)[0]
assert not R.can_merge(pr(files=[{"path": ".github/workflows/deploy-prod.yml"}]), CFG)[0]
assert not R.can_merge(pr(files=[{"path": "x"}] * 100), CFG)[0]

# bot PR routing
assert R.bot_pr_action(pr(), CFG)[0] == "merge"
assert R.bot_pr_action(pr(title="Bump x from 1.2.3 to 2.0.0"), CFG)[0] == "report"
assert R.bot_pr_action(pr(statusCheckRollup=GREEN + [{"conclusion": "FAILURE"}]), CFG)[0] == "report"
assert R.bot_pr_action(pr(statusCheckRollup=GREEN + [{"status": "QUEUED", "conclusion": ""}]), CFG)[0] == "wait"
assert R.bot_pr_action(pr(author={"login": "octo-user"}), CFG)[0] == "skip"
assert R.bot_pr_action(pr(mergeable="UNKNOWN"), CFG)[0] == "wait"      # GitHub still computing: no nagging
assert R.bot_pr_action(pr(mergeable="CONFLICTING"), CFG)[0] == "report"

# secrets never reach Slack
assert "ghp_" not in R.redact("token ghp_" + "a" * 30)
assert "dapi" not in R.redact("dapi" + "0" * 32)
assert R.redact("nothing secret here") == "nothing secret here"

# dedupe within ttl, repeat after ttl
posted = {}
assert R.seen(posted, "line A", NOW) is False
assert R.seen(posted, "line A", NOW + timedelta(days=1)) is True
assert R.seen(posted, "line A", NOW + timedelta(days=8)) is False

# misc
assert R.idle_days("2026-11-05T12:00:00Z", NOW) == 5
assert extract_json('here:\n```json\n{"a": 1}\n```') == {"a": 1}
assert extract_json("no json") is None and extract_json("{bad") is None
assert fill("hi {{x}} {{y}}", x=1, y="b") == "hi 1 b"
spec = {"title": "T", "summary": "S", "plan": ["a"] * 9, "open_questions": ["q"] * 5, "effort": "M"}
msg = fmt.fmt_spec(spec)
assert msg.startswith("🧭 *Spec: T*") and msg.count("\n5. ") == 1 and "\n6. " not in msg
assert msg.count("• q") == 3 and len(msg) < 3500

# ---- findings from the code review -----------------------------------------------------------
import json
import os
import subprocess
import tempfile
from pathlib import Path

import flows
import state

# untrusted text becomes one harmless line; more secret shapes are redacted
c = R.clean("Fix <!channel> @here\n`rm -rf` " + "x" * 300)
assert "<" not in c and "\n" not in c and "`" not in c and "@here" not in c and len(c) <= 120
for secret in ("github_pat_" + "a" * 30, "xapp-1-" + "b" * 20, "-----BEGIN " + "RSA PRIVATE KEY-----"):
    assert "[redacted]" in R.redact(secret), secret

# a grouped bump is not judged by its first pair; a label alone does not make a PR "ours"
assert R.title_bump("Bump a from 1.0.0 to 1.0.1 and b from 1.0.0 to 3.0.0") == "unknown"
ME = {**CFG, "me": "octo-user"}
mine = pr(author={"login": "octo-user"}, labels=[{"name": "maint-bot"}], headRefName="maint/2026-11-10-x")
assert R.is_maint_pr(mine, ME)
assert not R.is_maint_pr({**mine, "headRefName": "feature/x"}, ME)                      # label on a foreign branch
assert not R.is_maint_pr({**mine, "author": {"login": "someone-else"}}, ME)            # label on someone else's PR

# prune keeps state small
S = {"posted": {"a": (NOW - timedelta(days=20)).isoformat(), "b": NOW.isoformat()},
     "fix_attempts": {"k": (NOW - timedelta(days=40)).isoformat()}, "prs_today": {"r|2026-11-09": 1, "r|2026-11-10": 2},
     "reviewed": {str(i): i for i in range(80)}, "specs": {}}
R.prune(S, NOW)
assert list(S["posted"]) == ["b"] and S["fix_attempts"] == {} and S["prs_today"] == {"r|2026-11-10": 2}
assert len(S["reviewed"]) == 50 and "79" in S["reviewed"]


class FakeAgents:
    def __init__(self, reqs=(), fail_post_at=None, last=None):
        self.reqs, self.posts, self.specs, self.fail_post_at, self.last = list(reqs), [], [], fail_post_at, last

    def gate(self, after, threads):
        return self.reqs, self.last

    def spec(self, text, prior=None):
        self.specs.append((text, prior))
        return {"title": "T", "summary": "S"}

    def post(self, text, thread_ts=None):
        if self.fail_post_at is not None and len(self.posts) == self.fail_post_at:
            raise RuntimeError("slack down")
        self.posts.append((text, thread_ts))


def ctx(ag, live=True, **S):
    st = {"last_ts": None, "posted": {}, "fix_attempts": {}, "prs_today": {}, "reviewed": {}, "specs": {}, "last_scan_sha": {}, **S}
    return flows.Ctx({**CFG, "me": "x"}, st, live, ag, NOW)


# Slack gate: first live run replays nothing; old / future / our own messages are ignored; threads revise
now = NOW.timestamp()
ag = FakeAgents([{"ts": str(now - 50), "text": "old", "kind": "spec"}])
c1 = ctx(ag)
assert flows.gate(c1) == [] and c1.S["last_ts"] == str(now) and not ag.specs          # first run: start from now
after = str(now - 100)
reqs = [{"ts": str(now - 200), "text": "too old", "kind": "spec"},
        {"ts": str(now + 99999), "text": "from the future", "kind": "spec"},
        {"ts": str(now - 60), "text": "🧭 *Spec: echo*", "kind": "spec"},
        {"ts": str(now - 50), "text": ":warning: echo", "kind": "other"},
        {"ts": str(now - 40), "text": "build me a thing", "kind": "spec"},
        {"ts": str(now - 30), "thread_ts": str(now - 40), "text": "make it smaller", "kind": "spec"},
        {"ts": str(now - 20), "text": "scan example-repo now", "kind": "scan", "target": "example-repo"},
        {"ts": str(now - 10), "text": "hello?", "kind": "other"}]
ag = FakeAgents(reqs)
c2 = ctx(ag, last_ts=after)
assert flows.gate(c2) == ["example-repo"]
assert [t for t, _ in ag.specs] == ["build me a thing", "make it smaller"]
assert ag.specs[1][1] == {"title": "T", "summary": "S"}                                 # reply revised the earlier spec
assert c2.S["last_ts"] == str(now - 10) and ag.posts[-1][0].startswith("🧭")           # help text carries a bot prefix
assert len(ag.posts) == 3                                                                # 2 specs + 1 help, no echo replies

# a crashing agent is reported, never fatal, and does not stop the run
class Boom(FakeAgents):
    def gate(self, a, t):
        raise RuntimeError("json broke")
c3 = ctx(Boom(), last_ts=after)
assert flows.safe_gate(c3) == [] and "Slack check failed" in c3.lines[0][0]

# reports are chunked; a line counts as posted only after its chunk was sent
ag = FakeAgents()
c4 = ctx(ag)
for i in range(60):
    c4.note(f"🔴 line {i} " + "y" * 150)
sent = c4.report("🛠 *Maintenance*")
assert len(sent) == 60 and len(ag.posts) > 1 and all(len(t) <= flows.CHUNK + 50 for t, _ in ag.posts)
ag = FakeAgents(fail_post_at=1)
c5 = ctx(ag)
for i in range(60):
    c5.note(f"🔴 line {i} " + "y" * 150)
try:
    c5.report("T")
    raise AssertionError("expected the second post to fail")
except RuntimeError:
    pass
assert 0 < len(c5.S["posted"]) < 60                                                      # unsent lines will be retried

# state survives a torn write
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "state.json"
    state.save(p, {"last_ts": "1", "posted": {"a": "x"}})
    state.save(p, {"last_ts": "2", "posted": {}})
    p.write_text('{"last_ts": "3", "poste')                                              # power cut mid-write
    assert state.load(p)["last_ts"] == "1"                                              # falls back to the backup
    assert state.load(Path(d) / "missing.json")["specs"] == {}

# push-maint: the only push the fix agent has. Real git, local bare remote, nothing leaves the machine.
with tempfile.TemporaryDirectory() as d:
    sh_ = lambda *a, **k: subprocess.run(a, cwd=k.get("cwd", d), capture_output=True, text=True)
    sh_("git", "init", "-q", "--bare", "remote.git")
    sh_("git", "clone", "-q", "remote.git", "w")
    w = os.path.join(d, "w")
    sh_("git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=w)
    sh_("git", "checkout", "-q", "-b", "maint/ok-1", cwd=w)
    script = str(Path(__file__).parent / "push-maint")
    for bad in ("main", "maint/x:main", "maint/x :main", "maint/../x", "--force", "", "maint/other"):
        assert sh_(script, bad, cwd=w).returncode == 2, bad                             # refused before git runs
    assert sh_(script, "maint/ok-1", cwd=w).returncode == 0
    assert "maint/ok-1" in sh_("git", "branch", "--list", cwd=os.path.join(d, "remote.git")).stdout

# ---- tokens and cost per run --------------------------------------------------------------------
import costs
import llm

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "ledger.csv").write_text("ts,task,model,usd,turns\n2026-11-10T08:00:00+00:00,gate,haiku,0.005,4\n")  # old layout
    ag = llm.Agents({"models": {"gate": "haiku", "spec": "sonnet"}}, d, "20261110T1005-full", "full")
    ag._ledger("gate", {"total_cost_usd": 0.0055, "num_turns": 4, "usage": {
        "input_tokens": 10, "output_tokens": 300, "cache_creation_input_tokens": 4000, "cache_read_input_tokens": 17000}})
    ag._ledger("spec", {"total_cost_usd": 0.107, "num_turns": 6, "usage": {
        "input_tokens": 20, "output_tokens": 900, "cache_creation_input_tokens": 9000, "cache_read_input_tokens": 60000}})
    ag._ledger("gate", {"num_turns": 1})                                                  # a call that reports no usage at all
    assert (d / "ledger.v1.csv").exists()                                                # old layout kept, not mixed in
    rows = costs.read(d / "ledger.csv")
    assert len(rows) == 3 and rows[0]["input"] == 10 and rows[0]["run_id"] == "20261110T1005-full"

    line = fmt.fmt_cost(ag.stats, "this run")
    assert "3 calls" in line and "13.0k in + 77.0k cached" in line and "1.2k out" in line, line
    assert "$0.11" in line and "spec $0.107" in line and line.startswith("💰")
    assert fmt.fmt_cost({}, "x") == ""
    run = costs.per_run(rows)["20261110T1005-full"]
    assert run["mode"] == "full" and costs.totals(run["stats"])["calls"] == 3
    assert costs.since(rows, datetime.now(timezone.utc) + timedelta(days=2)) == {}      # nothing in the window
    assert "20261110T1005-full" in costs.table(rows) and "total: $" in costs.table(rows)

    # the footer rides on the LAST chunk of a report only, and the daily rollup has none
    class Costed(FakeAgents):
        stats, root = ag.stats, d

    cag = Costed()
    c6 = ctx(cag)
    for i in range(60):
        c6.note(f"🔴 line {i} " + "y" * 150)
    c6.report("🛠 *Maintenance*")
    assert len(cag.posts) > 1 and [("💰" in t) for t, _ in cag.posts] == [False] * (len(cag.posts) - 1) + [True]
    c6.post("🧭 spec reply", "123.4")
    assert "💰 this run, excl. posting" in cag.posts[-1][0] and cag.posts[-1][1] == "123.4"
    flows.cost_rollup(c6)
    assert cag.posts[-1][0].startswith("💰 last 24h") and cag.posts[-1][0].count("💰") == 1
    assert flows.BOT_PREFIXES and "💰".startswith(flows.BOT_PREFIXES)                   # never read back as a request
    # every emoji we post must also be recognised in the :shortcode: form Slack hands back (seen live: 🧑 -> :adult:)
    for shortcode in (":hammer_and_wrench:", ":red_circle:", ":adult:", ":moneybag:", ":white_check_mark:", ":compass:"):
        assert shortcode.startswith(flows.BOT_PREFIXES), shortcode

# ---- idle mode: read the last post first, stop when it said "no further action" ---------------------
MARKED, UNMARKED = {"ts": "1", "no_further_action": True}, {"ts": "1", "no_further_action": False}
quiet = lambda last, reqs=(): (lambda c: (flows.gate(c), c)[1])(ctx(FakeAgents(reqs, last=last), last_ts=after))
assert quiet(MARKED).idle is True                                                        # marker and nothing new: stop
assert quiet(UNMARKED).idle is False and quiet(UNMARKED).last_marked is False           # last post left work open: carry on
assert quiet(None).idle is False                                                         # the bot never posted
assert quiet(MARKED, [{"ts": str(now - 5), "text": "can you check example-repo?", "kind": "scan", "target": "example-repo"}]).idle is False
assert quiet(MARKED, [{"ts": str(now - 5), "text": "🛠 *Maintenance* all quiet", "kind": "other"}]).idle is True  # our own echo is not you
assert quiet(MARKED, [{"ts": str(now - 500), "text": "too old to count", "kind": "spec"}]).idle is True
assert ctx(Boom(), last_ts=after).idle is False                                          # cannot read Slack: never assume idle

# the marker: last line of a post that leaves nothing in progress, after the cost footer; never while work is open
class Costed2(FakeAgents):
    stats = {"gate": {"calls": 1, "usd": 0.005, "input": 10, "output": 5, "cache_write": 0, "cache_read": 100, "turns": 2}}


for pending, expect in ((0, True), (1, False)):
    cag = Costed2()
    cx = ctx(cag)
    cx.pending = pending
    for i in range(60):                                                                  # long enough to need several chunks
        cx.note(f"🔴 line {i} " + "y" * 150)
    cx.report("🛠 *Maintenance*")
    ends = [t.splitlines()[-1] == flows.TAIL for t, _ in cag.posts]
    assert ends == [False] * (len(cag.posts) - 1) + [expect], (pending, ends)           # last chunk only
    if expect:
        assert "💰" in cag.posts[-1][0].splitlines()[-2]                                 # footer sits above the marker

# nothing new, nothing pending, but the last post left work open -> one closing post, so the next run can go idle
flows_scan, flows.scan_repo = flows.scan_repo, lambda c, r, f: None
for marked, closes in ((False, True), (True, False), (None, False)):
    cag = Costed2()
    cx = ctx(cag)
    cx.cfg = {**cx.cfg, "repos": [{"name": "r"}]}
    cx.last_marked = marked
    flows.full(cx, ())
    assert bool(cag.posts) is closes, marked
    if closes:
        assert cag.posts[0][0].startswith("🟡 All quiet") and cag.posts[0][0].splitlines()[-1] == flows.TAIL
cx = ctx(Costed2())
cx.cfg = {**cx.cfg, "repos": [{"name": "r"}]}
flows.scan_repo = lambda c, r, f: (_ for _ in ()).throw(RuntimeError("github down"))
flows.full(cx, ())                                                                       # a failed scan is "pending": no marker
assert cx.pending == 1 and cx.ag.posts and cx.ag.posts[0][0].splitlines()[-1] != flows.TAIL
flows.scan_repo = flows_scan

# one full pass per day even when idle
assert flows.sweep_due(ctx(FakeAgents())) is True
swept = ctx(FakeAgents(), last_sweep=str(NOW.astimezone().date()))
assert flows.sweep_due(swept) is False

# fix agents: one paid attempt per workflow NAME (shared template) and per repo+workflow, per 3 days, whatever the commit
fix_calls = []
real_run_fix, flows.run_fix = flows.run_fix, lambda c, repo, wf: fix_calls.append(repo["name"]) or {"result": "needs_human", "why": "lock"}
FIXCFG = {**CFG, "me": "x", "max_fix_per_run": 1, "max_new_prs_per_repo_day": 3, "models": {"fix": "sonnet"}, "budget_usd": {"fix": 1.5}}
wf = {"workflowName": "Governance Rollout", "headSha": "a" * 10, "createdAt": "2026-11-09T10:00:00Z", "url": "u"}
shared = {"last_ts": None, "posted": {}, "fix_attempts": {}, "prs_today": {}, "reviewed": {}, "specs": {}, "last_scan_sha": {}}
at = lambda hours: flows.Ctx(FIXCFG, shared, True, FakeAgents(), NOW + timedelta(hours=hours))
flows.red_workflow(at(0), {"name": "A", "gh": "o/a"}, wf)
flows.red_workflow(at(1), {"name": "B", "gh": "o/b"}, wf)                                # same workflow, other repo: skipped
flows.red_workflow(at(25), {"name": "A", "gh": "o/a"}, {**wf, "headSha": "b" * 10})       # new commit, same repo: skipped
assert fix_calls == ["A"], fix_calls
flows.red_workflow(at(73), {"name": "B", "gh": "o/b"}, wf)                               # after the cooldown: allowed again
assert fix_calls == ["A", "B"]
flows.red_workflow(at(74), {"name": "C", "gh": "o/c"}, {**wf, "workflowName": "Deploy"})   # a different workflow is independent
assert fix_calls == ["A", "B", "C"]
flows.run_fix = real_run_fix
assert R.recent({"k": NOW.isoformat()}, "k", NOW + timedelta(hours=1), 2) and not R.recent({}, "k", NOW, 2)
assert not R.recent({"k": NOW.isoformat()}, "k", NOW + timedelta(hours=3), 2)

# ---- event log (feeds the dashboard) -----------------------------------------------------------
import events

lines = lambda: [json.loads(l) for l in events.PATH.read_text().splitlines()]
events.emit("gate", "Slack: 2 new message(s) from you")
eid = events.begin("agent", "Writing a spec: mobile layout")
events.end(eid, "Writing a spec: mobile layout · $0.107 · 6 turns")
a, b, c_ = lines()[-3:]
assert a["phase"] == "done" and b["phase"] == "start" and c_["phase"] == "end" and b["id"] == c_["id"] == eid
events.emit("x", "y" * 999)
assert len(lines()[-1]["text"]) == 200                                                  # one-liners stay one-liners
for i in range(6000):                                                                    # the log trims itself
    events.emit("bulk", "z" * 100)
assert events.PATH.stat().st_size < events.MAX_BYTES + 5000 and len(lines()) <= events.KEEP_LINES + 800
saved = events.PATH
events.PATH = Path("/proc/definitely/not/writable.jsonl")
events.emit("boom", "logging must never break a run")                                  # no exception
events.PATH = saved

# ---- dashboard logic ----------------------------------------------------------------------------
import time

import dash

assert dash.tool_line("Bash", {"command": "gh pr list --repo x\nsecond line"}) == "$ gh pr list --repo x"
assert dash.tool_line("Bash", {}) == "$ " and dash.tool_line("Edit", {"file_path": "/a/b/c.py"}) == "Edit c.py"
assert dash.tool_line("mcp__claude_ai_Slack__slack_read_channel", {}) == "slack read channel"
assert dash.tool_line("Agent", {"description": "review the diff"}) == "Delegating: review the diff"
assert dash.prompt_text("<system-reminder>x</system-reminder>") == "" and dash.prompt_text([{"type": "tool_result"}]) == ""
assert dash.prompt_text([{"type": "text", "text": "Fix the build\nplease"}]) == "Fix the build"

now_iso = lambda: datetime.now(timezone.utc).isoformat()
rec = lambda t, **kw: json.dumps({"timestamp": now_iso(), "type": t, **kw}) + "\n"
asst = lambda tool: rec("assistant", message={"usage": {"input_tokens": 5, "cache_creation_input_tokens": 100,
                                                       "cache_read_input_tokens": 1000, "output_tokens": 50},
                                              "content": [{"type": "tool_use", "name": "Bash", "input": {"command": tool}}]})
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    t = d / "proj" / "aaaaaaaa-1111.jsonl"
    t.parent.mkdir()
    t.write_text(rec("user", message={"content": "Deploy the dashboard"}) + asst("make build"))
    day = dash.fold_file(t)[datetime.now().astimezone().date().isoformat()]
    assert day == {"turns": 1, "in": 105, "cached": 1000, "out": 50, "tools": 1}
    with t.open("a") as f:                                                              # a live session: whole line + half a line
        f.write(asst("make test") + asst("make lint")[:40])
    assert next(iter(dash.fold_file(t).values()))["turns"] == 2                         # half-written line is not counted yet
    with t.open("a") as f:
        f.write(asst("make lint")[40:])
    assert next(iter(dash.fold_file(t).values()))["turns"] == 3                         # ...and counted once complete
    assert [x for _, x in dash.tail_events(t)] == ["Request: Deploy the dashboard", "$ make build", "$ make test", "$ make lint"]
    big = d / "proj" / "big.jsonl"                                                      # a file longer than the read window
    big.write_text("".join(asst(f"step {i}") for i in range(900)))
    assert big.stat().st_size > 80_000 and dash.tail_events(big)[-1][1] == "$ step 899"

    # hourly buckets: right hour, right profile, nothing outside the window
    nl = datetime(2026, 11, 10, 12, 30).astimezone()
    hb = dash.hourly([(nl - timedelta(minutes=20), "work", 0.5), (nl - timedelta(hours=5), "personal", 0.25),
                      (nl - timedelta(hours=30), "work", 9.0), (nl, "ghost", 9.0)], nl)
    assert len(hb) == 24 and hb[-1]["work"] == 0.5 and hb[-6]["personal"] == 0.25
    assert round(sum(b["work"] + b["personal"] for b in hb), 2) == 0.75

    # what is running now: unfinished starts only, and not ones from a crashed run long ago
    evs = [{"phase": "start", "id": "a", "ts": 1000, "text": "x"}, {"phase": "end", "id": "a", "ts": 1005},
           {"phase": "start", "id": "b", "ts": 1990, "text": "live"}, {"phase": "start", "id": "c", "ts": 10, "text": "crashed"}]
    assert [e["id"] for e in dash.open_work(evs, 2000)] == ["b"]

    # ponytail cost rows count only for sessions that have a transcript (loop agents have none)
    band = d / "band"
    band.mkdir()
    (band / "p.csv").write_text("key,started,project,name,cost_usd\naaaaaaaa-1,2026-11-10 12:10,p,x,0.4\nbbbbbbbb-2,2026-11-10 12:11,p,y,9.9\n")
    old_band, dash.BAND = dash.BAND, band
    items = dash.band_items({"aaaaaaaa": "personal"})
    dash.BAND = old_band
    assert [(p, c) for _, p, c in items] == [("personal", 0.4)]

    # end to end: a fresh transcript shows up as work happening now, attributed to its profile
    old = dash.PROFILES, dash.EVENTS
    pp = d / "pp" / "projects" / "proj"                                                 # a profile dir laid out like the real ones
    pp.mkdir(parents=True)
    (pp / t.name).write_text(t.read_text())
    dash.PROFILES = {"work": d / "none", "personal": d / "pp"}
    dash.EVENTS = d / "events.jsonl"
    dash.EVENTS.write_text(json.dumps({"ts": time.time() + 5, "phase": "start", "id": "z", "kind": "agent", "text": "Reading Slack"}) + "\n")
    (d / "ledger.csv").write_text(                                                       # one call today, one two days ago
        "ts,run_id,mode,task,model,usd,turns,input,output,cache_write,cache_read\n"
        f"{(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},r1,full,gate,haiku,0.005,4,10,300,4000,17000\n"
        f"{(datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},r0,full,spec,sonnet,0.1,6,1,1,1,1\n")
    old_app, dash.APP = dash.APP, d
    s = dash.build_state()
    dash.PROFILES, dash.EVENTS, dash.APP = old[0], old[1], old_app
    assert s["profiles"]["work"]["calls"] == 1 and s["total"]["calls"] == 1             # only today's loop call counts
    hist = [e["text"] for e in s["events"] if e["src"] == "loop"]
    assert "gate · $0.005 · 4 turns" in hist and "spec · $0.100 · 6 turns" in hist      # ledger fills the history
    mine = [w for w in s["now_working"] if w["src"] == "personal"]
    assert mine and mine[0]["text"] == "Deploy the dashboard" and mine[0]["step"] == "$ make lint"
    assert any(w["src"] == "loop" and w["text"] == "Reading Slack" for w in s["now_working"])
    assert s["profiles"]["personal"]["turns"] == 3 and s["profiles"]["personal"]["active"] and not s["profiles"]["work"]["active"]
    assert len(s["hourly"]) == 24 and json.dumps(s)

print("all tests passed")
