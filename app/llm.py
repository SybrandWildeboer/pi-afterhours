"""One small agent per task: fixed model, budget cap, tool allowlist, plugins off unless needed."""
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import events
from util import extract_json, fill, sh

HOME = str(Path.home())
SLACK = "mcp__claude_ai_Slack__"
PUSH = f"{HOME}/maint/app/push-maint"  # the only way to push: see push-maint

# Never readable or writable by any agent, whatever the allowlist says.
DENY = ["Read(~/.ssh/**)", "Read(~/.claude-profiles/**)", "Read(~/.claude/**)", "Read(~/.databricks/**)",
        "Read(~/.databrickscfg)", "Read(~/.config/gh/**)", "Read(~/.git-credentials)", "Read(~/.netrc)",
        "Edit(**/.git/**)", "Write(**/.git/**)", "Edit(**/.claude/**)", "Write(**/.claude/**)"]

TOOLS = {
    "gate": ["ToolSearch", SLACK + "slack_read_channel", SLACK + "slack_read_thread"],
    "post": ["ToolSearch", SLACK + "slack_send_message"],
    "spec": ["Read(~/projects/**)", "Grep", "Glob", "Skill"],
    "review": ["Bash(gh pr view:*)", "Bash(gh pr diff:*)", "Bash(gh pr checks:*)"],  # no Read: it sees only the diff
    "fix": ["Read(~/maint/work/**)", "Edit(~/maint/work/**)", "Write(~/maint/work/**)", "Grep", "Glob", "Skill",
            "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git add:*)", "Bash(git commit:*)",
            f"Bash({PUSH}:*)", "Bash(gh run view:*)", "Bash(gh pr create:*)", "Bash(gh pr view:*)"],
}


FIELDS = ["ts", "run_id", "mode", "task", "model", "usd", "turns", "input", "output", "cache_write", "cache_read"]


class Agents:
    def __init__(self, cfg, root, run_id="", mode=""):
        self.cfg, self.root, self.run_id, self.mode = cfg, Path(root), run_id, mode
        self.stats = {}  # this run's usage per task; shown in the Slack cost footer

    def _prompt(self, name, **kw):
        return fill((self.root / "agents" / f"{name}.md").read_text(), **kw)

    def plugins_for(self, task):
        return list(self.cfg["plugins"].get(task, []))

    def command(self, task, prompt, plugins=()):
        """The exact claude argv for one agent call. Pure: nothing is run here."""
        c = self.cfg
        slack = task in ("gate", "post")
        skills = task in ("spec", "fix")
        known = {p: False for p in c["plugins"]["off"]}  # listed as off unless this agent was given it
        known.update({p: True for p in plugins})
        cmd = ["claude", "-p", prompt, "--model", c["models"][task], "--output-format", "json",
               "--no-session-persistence", f"--max-budget-usd={c['budget_usd'][task]}",
               "--setting-sources", "user",  # ignore any .claude/settings in the repo being worked on
               "--settings", json.dumps({"enabledPlugins": known})]
        if not slack:  # claude.ai connectors add ~5x tokens per call: only Slack agents get them
            cmd += ["--strict-mcp-config", '--mcp-config={"mcpServers":{}}']
        if not skills:
            cmd.append("--disable-slash-commands")
        cmd += ["--disallowedTools", *DENY, "--allowedTools", *TOOLS[task]]  # variadic flags: keep last
        return cmd

    def _run(self, task, prompt, plugins=(), cwd=None, label=None):
        c = self.cfg
        label = label or task
        cmd = self.command(task, prompt, plugins)
        env = {**os.environ, "CLAUDE_CONFIG_DIR": f"{HOME}/.claude-profiles/{c['profile']}",
               "PATH": f"{HOME}/.local/bin:{os.environ['PATH']}"}
        eid = events.begin("agent", label)
        try:
            out = json.loads(sh(cmd, timeout=1200, cwd=cwd, env=env))
        except Exception as e:
            events.end(eid, f"{label}: failed ({str(e)[:70]})", ok=False)
            raise
        self._ledger(task, out)
        ok = not out.get("is_error") and out.get("subtype") == "success"
        events.end(eid, f"{label} · ${out.get('total_cost_usd') or 0:.3f} · {out.get('num_turns') or 0} turns", ok=ok)
        if not ok:
            raise RuntimeError(f"{task}: {out.get('subtype')} {str(out.get('result'))[:150]}")
        return out["result"]

    def _ledger(self, task, out):
        u = out.get("usage") or {}
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": self.run_id,
               "mode": self.mode, "task": task, "model": self.cfg["models"][task],
               "usd": round(out.get("total_cost_usd") or 0, 5), "turns": out.get("num_turns") or 0,
               "input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
               "cache_write": u.get("cache_creation_input_tokens") or 0, "cache_read": u.get("cache_read_input_tokens") or 0}
        f = self.root / "ledger.csv"
        if f.exists() and f.read_text().split("\n", 1)[0] != ",".join(FIELDS):  # older column layout
            f.rename(self.root / "ledger.v1.csv")
        new = not f.exists()
        with f.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        s = self.stats.setdefault(task, {"calls": 0, "usd": 0.0, "turns": 0.0, "input": 0.0, "output": 0.0,
                                         "cache_write": 0.0, "cache_read": 0.0})
        s["calls"] += 1
        for k in ("usd", "turns", "input", "output", "cache_write", "cache_read"):
            s[k] += row[k]

    def _json(self, task, *a, **kw):
        j = extract_json(self._run(task, *a, **kw))
        if j is None:
            raise RuntimeError(f"{task}: answer was not JSON")
        return j

    def gate(self, after_ts, threads=()):
        extra = ("Also read these existing threads (thread root ts) for replies newer than that: "
                 + ", ".join(list(threads)[-10:])) if threads else ""
        p = self._prompt("gate", channel=self.cfg["channel"], after_ts=after_ts, threads=extra)
        for attempt in (1, 2):
            try:
                j = self._json("gate", p, label="Reading the last post and new requests")
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(20)  # the Slack connector is sometimes still connecting when claude starts
        return j.get("requests", []), j.get("last_bot_post")

    def post(self, text, thread_ts=None):
        p = self._prompt("post", channel=self.cfg["channel"], thread_ts=thread_ts or "none", text=json.dumps(text))
        self._run("post", p, label="Posting to Slack")

    def spec(self, text, prior=None):
        names = ", ".join(r["path"] for r in self.cfg["repos"])
        prior_block = (f"\nA previous version of this spec exists. Revise it using the new message above:\n"
                       f"{json.dumps(prior)}\n") if prior else ""
        p = self._prompt("spec", text=text, repos=names, prior=prior_block)
        return self._json("spec", p, plugins=self.plugins_for("spec"), cwd=self.cfg["projects_root"],
                          label=f"Writing a spec: {text[:70]}")

    def review(self, repo, number):
        p = self._prompt("review", gh=repo["gh"], number=number)
        return self._json("review", p, label=f"Reviewing {repo['gh']}#{number}")

    def fix(self, repo, wf, branch, worktree):
        """The caller (code) has already created `worktree` on `branch`; the agent works only inside it."""
        p = self._prompt("fix", repo=repo["name"], gh=repo["gh"], workflow=wf["workflowName"], branch=branch,
                         base="main", sha=wf["headSha"][:10], url=wf["url"], push=PUSH)
        return self._json("fix", p, plugins=self.plugins_for("fix"), cwd=worktree,
                          label=f"Fixing {repo['name']}: {wf['workflowName']}")
