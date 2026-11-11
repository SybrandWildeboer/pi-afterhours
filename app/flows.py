"""What a run does. Dry-run by default: reads freely, never posts, merges, pushes or opens a PR."""
import re
from datetime import timedelta
from pathlib import Path

import collect as C
import costs
import dbx
import events
import fmt
import rules as R
from util import sh

# Our own posts must never be read back as requests. Slack may return emoji as :shortcodes: too.
BOT_PREFIXES = ("🧭", "🛠", "🔴", "🔒", "⚠️", "❌", "✅", "🟡", "💸", "🔑", "👀", "📝", "🧑", "🧱",
                ":compass:", ":hammer_and_wrench:", ":red_circle:", ":lock:", ":warning:", ":x:",
                ":white_check_mark:", ":large_yellow_circle:", ":money_with_wings:", ":key:", ":eyes:",
                ":memo:", ":adult:", ":technologist:", ":bricks:", "💰", ":moneybag:")
CHUNK = 3400
TAIL = "no further action"  # last line of a post that leaves nothing in progress: the next run stops when it sees it


class Ctx:
    def __init__(self, cfg, state, live, agents, now):
        self.cfg, self.S, self.live, self.ag, self.now = cfg, state, live, agents, now
        self.lines, self.fixes = [], 0
        self.pending = 0         # work still in progress (CI running, failed step to retry): blocks the TAIL marker
        self.idle = False        # set by gate(): last post said "no further action" and you wrote nothing new
        self.last_marked = None  # did the last bot post end with the marker? None = unknown

    def note(self, line, key=None):
        self.lines.append((line, key or line))

    def post(self, text, thread_ts=None, footer=True, tail=""):
        text = R.redact(text)
        line = fmt.fmt_cost(getattr(self.ag, "stats", {}), "this run, excl. posting") if footer else ""
        if line:
            text += "\n" + line
        if tail:  # always the very last line, after the cost footer
            text += "\n" + tail
        if self.live:
            self.ag.post(text, thread_ts)
        else:
            print(f"[dry-run] would post{' in thread ' + thread_ts if thread_ts else ''}:\n{text}\n")

    def report(self, title):
        """Post new lines in chunks. A line counts as 'seen' only once the chunk containing it was sent."""
        todo = [(l, k) for l, k in self.lines if not R.is_seen(self.S["posted"], k, self.now)]
        self.lines = []
        if not todo:
            print("[quiet] nothing new to report")
            return []
        chunks, chunk, size = [], [], len(title)
        for item in todo:
            if chunk and size + len(item[0]) + 1 > CHUNK:
                chunks.append(chunk)
                chunk, size = [], len(title)
            chunk.append(item)
            size += len(item[0]) + 1
        chunks.append(chunk)
        for i, ch in enumerate(chunks):
            last = i == len(chunks) - 1  # cost footer and the "no further action" marker go on the last chunk only
            self.post(title + "\n" + "\n".join(l for l, _ in ch), footer=last, tail=TAIL if last and not self.pending else "")
            for _, k in ch:
                R.mark(self.S["posted"], k, self.now)
        return [l for l, _ in todo]


# ---- Slack requests -------------------------------------------------------------------------
def safe_gate(ctx):
    """A Slack failure must never stop the repo checks."""
    try:
        return gate(ctx)
    except Exception as e:
        ctx.pending += 1  # we could not see Slack: not idle, and not "done" either
        ctx.note(f"⚠️ Slack check failed: {str(e)[:120]}", key=f"gate-fail {ctx.now:%Y-%m-%d %H}")
        return []


def sweep_due(ctx):
    """Even when idle, one full pass per day (the old 'repo scan once a day') finds new problems without you asking."""
    return ctx.S.get("last_sweep") != str(ctx.now.astimezone().date())


def gate(ctx):
    """Read new messages from the user. Returns scan targets; answers spec requests directly."""
    S, now = ctx.S, ctx.now.timestamp()
    if ctx.live and not S["last_ts"]:  # first live run: start from now, never replay history
        S["last_ts"] = str(now)
        return []
    after = S["last_ts"] or str(now - 86400)
    forced = []
    reqs, last_post = ctx.ag.gate(after, S["specs"])
    ctx.last_marked = bool(last_post and last_post.get("no_further_action"))  # first thing we read: the last post
    human_new = False
    if reqs:
        events.emit("gate", f"Slack: {len(reqs)} new message(s) from you")
    for r in sorted(reqs, key=lambda r: float(r["ts"])):
        if not float(after) < float(r["ts"]) <= now + 60:  # do not trust the LLM's "newer than" filter
            continue
        if ctx.live:
            S["last_ts"] = r["ts"]  # at-most-once: a request that crashes is reported, not retried forever
        if r["text"].lstrip().startswith(BOT_PREFIXES):
            continue
        human_new = True
        key = r.get("thread_ts") or r["ts"]
        try:
            if r.get("kind") == "spec":
                spec(ctx, r["text"], key)
            elif r.get("kind") == "scan":
                forced.append((r.get("target") or "all").lower())
            else:
                ctx.post(fmt.HELP, key)
        except Exception as e:
            ctx.note(f"⚠️ Could not handle your request ({str(e)[:100]})", key=f"req-fail {r['ts']}")
    ctx.idle = ctx.last_marked and not human_new
    return forced


def spec(ctx, text, key):
    s = ctx.ag.spec(text, ctx.S["specs"].get(key))  # key is the thread root: replies revise the same spec
    ctx.S["specs"][key] = s
    ctx.post(fmt.fmt_spec(s), key)


# ---- Repos ----------------------------------------------------------------------------------
def full(ctx, forced=()):
    everything = "all" in forced
    for repo in ctx.cfg["repos"]:
        try:
            scan_repo(ctx, repo, everything or repo["name"] in forced)
        except Exception as e:
            ctx.pending += 1  # retried next run, so this is not "done"
            ctx.note(f"⚠️ {repo['name']}: scan failed: {str(e)[:140]}", key=f"fail {repo['name']} {ctx.now.date()}")
    fresh = ctx.report("🛠 *Maintenance*")
    if not fresh and not ctx.pending and ctx.last_marked is False:
        # the previous post left work open, nothing is open now: close it so the next run can go idle
        ctx.post("🟡 All quiet, nothing pending.", tail=TAIL)
    if everything or "databricks" in forced:
        dbx_flow(ctx)


def scan_repo(ctx, repo, force):
    eid = events.begin("scan", f"Scanning {repo['name']}")
    try:
        summary = _scan_repo(ctx, repo, force)
    except Exception as e:
        events.end(eid, f"{repo['name']}: scan failed ({str(e)[:60]})", ok=False)
        raise
    events.end(eid, summary)


def _scan_repo(ctx, repo, force):
    name = repo["name"]
    prs = C.open_prs(repo)
    for pr in prs:
        try:
            triage_pr(ctx, repo, pr)
        except Exception as e:  # one bad PR must not hide the rest of the repo
            ctx.pending += 1
            ctx.note(f"⚠️ {name} #{pr['number']}: could not process: {str(e)[:100]}",
                     key=f"pr-fail {name} {pr['number']} {ctx.now.date()}")
    reds = C.red_workflows(repo, ctx.cfg["ci_max_age_days"], ctx.now)
    for wf in reds:
        red_workflow(ctx, repo, wf)
    sha = C.head_sha(repo)
    if force or ctx.S["last_scan_sha"].get(name) != sha:  # audit only when the code changed
        path = f"{ctx.cfg['projects_root']}/{repo['path']}"
        C.pull(path)
        for line in C.audit(path, name):
            ctx.note(line)
        ctx.S["last_scan_sha"][name] = sha
    return f"{name}: {len(prs)} PRs · {len(reds)} red CI"


def red_workflow(ctx, repo, wf):
    cfg, S = ctx.cfg, ctx.S
    name, wname = repo["name"], wf["workflowName"]
    ctx.note(f"🔴 {name}: workflow '{R.clean(wname, 60)}' failing on main since {wf['createdAt'][:10]}. {wf['url']}",
             key=f"red {name}:{wname}")  # one line per repo+workflow per week, not one per new commit
    day = f"{name}|{ctx.now.date()}"
    # One paid attempt per workflow NAME (it is usually the same template in several repos) and one per
    # repo+workflow, per 3 days, whatever the commit. This is what stopped "one more fix agent every hour".
    wkey, rkey = f"wf:{wname}", f"repo:{name}:{wname}"
    if (ctx.fixes >= cfg["max_fix_per_run"] or R.recent(S["fix_attempts"], wkey, ctx.now, 72)
            or R.recent(S["fix_attempts"], rkey, ctx.now, 72) or S["prs_today"].get(day, 0) >= cfg["max_new_prs_per_repo_day"]):
        return
    ctx.fixes += 1
    if not ctx.live:
        print(f"[dry-run] would dispatch fix agent ({cfg['models']['fix']}, up to ${cfg['budget_usd']['fix']}) for {name}: {wname}")
        return
    S["fix_attempts"][wkey] = S["fix_attempts"][rkey] = ctx.now.isoformat()  # before the call: a failing run must not repeat
    try:
        res = run_fix(ctx, repo, wf)
    except Exception as e:
        ctx.note(f"⚠️ {name}: fix agent failed: {str(e)[:120]}", key=f"fixfail {rkey}")
        return
    if res.get("result") == "pr":
        ctx.pending += 1  # the PR still has to pass CI
        S["prs_today"][day] = S["prs_today"].get(day, 0) + 1
        ctx.note(f"🛠 {name}: opened fix PR {R.clean(res.get('pr_url', ''), 200)}", key=f"fixpr {rkey} {ctx.now.date()}")
        events.emit("fix", f"{name}: opened a fix PR for '{wname}'")
    else:
        events.emit("fix", f"{name}: '{wname}' needs a human, no PR opened")
        ctx.note(f"🧑 {name}: '{R.clean(wname, 60)}' needs a human: {R.clean(res.get('why', '?'))}", key=f"human {rkey}")


def run_fix(ctx, repo, wf):
    """Code, not the agent, prepares an isolated worktree; the agent can only touch that folder."""
    path = f"{ctx.cfg['projects_root']}/{repo['path']}"
    slug = re.sub(r"[^a-z0-9]+", "-", wf["workflowName"].lower()).strip("-")[:24] + "-" + wf["headSha"][:7]
    branch, wt = f"maint/{ctx.now.date()}-{slug}", Path.home() / "maint" / "work" / slug
    sh(["gh", "label", "create", "maint-bot", "--repo", repo["gh"], "--force", "--color", "5319e7",
        "--description", "Opened by the maintenance bot"])
    sh(["git", "-C", path, "fetch", "-q", "origin", "main"], timeout=120)
    sh(["git", "-C", path, "worktree", "remove", "--force", str(wt)], ok=(0, 128))  # leftover from a crash
    sh(["git", "-C", path, "branch", "-D", branch], ok=(0, 1))
    sh(["git", "-C", path, "worktree", "add", str(wt), "-b", branch, "origin/main"])
    try:
        return ctx.ag.fix(repo, wf, branch, str(wt))
    finally:
        sh(["git", "-C", path, "worktree", "remove", "--force", str(wt)], ok=(0, 128))
        sh(["git", "-C", path, "branch", "-D", branch], ok=(0, 1))  # the pushed branch lives on origin


def triage_pr(ctx, repo, pr):
    tag = f"{repo['name']} #{pr['number']}"
    title, author = R.clean(pr["title"]), R.clean(pr["author"]["login"], 40)
    if pr["author"]["login"] in R.BOTS:
        act, why = R.bot_pr_action(pr, ctx.cfg)
        if act == "merge":
            merge(ctx, repo, pr, why)
        elif act == "report":
            ctx.note(f"⚠️ {tag}: {title}: {why}. {pr['url']}", key=f"bot {tag} {pr['headRefOid']} {why}")
        elif act == "wait":
            ctx.pending += 1  # CI still running / GitHub still computing: look again next run
    elif R.is_maint_pr(pr, ctx.cfg):
        maint_pr(ctx, repo, pr, tag)
    elif (not pr["isDraft"] and pr["author"]["login"] != ctx.cfg["me"]  # my own PRs wait on others, not on me
          and R.idle_days(pr["updatedAt"], ctx.now) >= ctx.cfg["stale_human_pr_days"]):
        ctx.note(f"👀 {tag}: '{title}' by {author}, idle {R.idle_days(pr['updatedAt'], ctx.now)}d, "
                 f"checks {R.checks_state(pr['statusCheckRollup'])}, +{pr['additions']}/-{pr['deletions']}. {pr['url']}",
                 key=f"human {tag} {pr['headRefOid']}")


def maint_pr(ctx, repo, pr, tag):
    state = R.checks_state(pr["statusCheckRollup"])
    if state == "red":
        ctx.note(f"🔴 {tag}: my PR has red checks. {pr['url']}", key=f"red {tag} {pr['headRefOid']}")
    if state != "green":
        ctx.pending += state == "pending"  # my own PR is still being checked
        return
    key, sha = f"{repo['name']}#{pr['number']}", pr["headRefOid"]
    seen = ctx.S["reviewed"].get(key)
    if not seen or seen.get("sha") != sha:
        if not ctx.live:
            print(f"[dry-run] would run review agent on {key}")
            return
        seen = {"sha": sha, **ctx.ag.review(repo, pr["number"])}
        ctx.S["reviewed"][key] = seen
    verdict = seen.get("verdict")
    ok, why = R.can_merge(pr, ctx.cfg)
    if verdict == "approve" and ok:
        merge(ctx, repo, pr, "reviewer approved, checks green")
    elif verdict == "approve":
        ctx.note(f"🟡 {tag}: reviewer approves but I will not merge it ({why}). {pr['url']}", key=f"hold {tag} {sha}")
    else:
        notes = "; ".join(R.clean(c, 100) for c in (seen.get("comments") or [])[:3])
        ctx.note(f"📝 {tag}: reviewer says {verdict}: {notes}. {pr['url']}", key=f"rev {tag} {sha}")


def merge(ctx, repo, pr, why):
    tag, n = f"{repo['name']} #{pr['number']}", str(pr["number"])
    if not (ctx.cfg["auto_merge"] and ctx.live):
        ctx.note(f"🟡 {tag}: ready to merge ({why}). Auto-merge is off. {pr['url']}", key=f"ready {tag} {pr['headRefOid']}")
        return
    if pr["author"]["login"] in R.BOTS:  # you cannot approve your own PR
        sh(["gh", "pr", "review", n, "--repo", repo["gh"], "--approve"])
    # pinned to the commit we checked: a later push is never merged unreviewed
    sh(["gh", "pr", "merge", n, "--repo", repo["gh"], "--squash", "--match-head-commit", pr["headRefOid"]])
    ctx.note(f"✅ {repo['gh']} #{n} — {R.clean(pr['title'])}; {why}, +{pr['additions']}/-{pr['deletions']}, "
             f"{len(pr['files'])} files. {pr['url']}")


# ---- Databricks -----------------------------------------------------------------------------
def dbx_flow(ctx):
    for profile in ctx.cfg["workspaces"]:
        for line in dbx.check(profile):
            ctx.note(R.clean(line, 300), key=line)
    return ctx.report("🧱 *Databricks*")


def cost_rollup(ctx):
    """Daily line with the last 24h of tokens and dollars, posted even when everything else is quiet."""
    rows = costs.read(ctx.ag.root / "ledger.csv")
    ctx.post(fmt.fmt_cost(costs.since(rows, ctx.now), "last 24h") or "💰 last 24h: no LLM calls", footer=False)
