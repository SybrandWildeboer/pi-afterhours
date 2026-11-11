"""Read-only GitHub and dependency collection with gh/git/pip-audit/npm. No LLM involved."""
import json
import os
from datetime import datetime, timedelta, timezone

from util import jsh, sh

PR_FIELDS = ("number,title,author,labels,isDraft,mergeable,reviewDecision,statusCheckRollup,"
             "updatedAt,additions,deletions,files,url,headRefOid,headRefName")
_SKIP = {"node_modules", ".venv", "venv", ".git", "site-packages"}


def branch(repo):
    return repo.get("branch", "main")


def open_prs(repo):
    return jsh(["gh", "pr", "list", "--repo", repo["gh"], "--state", "open", "--limit", "50",
                "--json", PR_FIELDS]) or []


def red_workflows(repo, max_age_days, now=None):
    """Workflows whose most recent completed run on the default branch failed, within max_age_days."""
    now = now or datetime.now(timezone.utc)
    runs = jsh(["gh", "run", "list", "--repo", repo["gh"], "--branch", branch(repo), "--limit", "60",
                "--json", "workflowName,conclusion,headSha,url,createdAt,status"]) or []
    latest = {}
    for r in sorted(runs, key=lambda r: r["createdAt"], reverse=True):
        if r["status"] == "completed":
            latest.setdefault(r["workflowName"], r)
    cutoff = now - timedelta(days=max_age_days)
    return [r for r in latest.values() if r["conclusion"] == "failure"
            and datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= cutoff]


def head_sha(repo):
    return sh(["gh", "api", f"repos/{repo['gh']}/commits/{branch(repo)}", "-q", ".sha"]).strip()


def pull(repo_dir):
    sh(["git", "-C", repo_dir, "pull", "--ff-only", "-q"], timeout=120)


def _find(root, pattern, depth=4):
    import fnmatch
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _SKIP]
        if d[len(root):].count(os.sep) >= depth:
            dirs[:] = []
        for f in files:
            if fnmatch.fnmatch(f, pattern):
                yield os.path.join(d, f)


def audit(repo_dir, name):
    """Known-vulnerable dependencies from requirements*.txt (pip-audit) and package-lock.json (npm audit)."""
    lines = []
    for f in _find(repo_dir, "requirements*.txt"):
        out = sh(["pip-audit", "-r", f, "-f", "json", "--progress-spinner", "off"], timeout=180, ok=(0, 1))
        for d in (json.loads(out or "{}")).get("dependencies", []):
            for v in d.get("vulns", []):
                fix = ", ".join(v.get("fix_versions") or ["none"])
                lines.append(f"🔒 {name}: {d['name']} {d['version']} has {v['id']} (fix: {fix})")
    for f in _find(repo_dir, "package-lock.json"):
        out = sh(["npm", "audit", "--json", "--package-lock-only"], cwd=os.path.dirname(f), timeout=180, ok=(0, 1))
        v = (json.loads(out or "{}")).get("metadata", {}).get("vulnerabilities", {})
        if v.get("high", 0) + v.get("critical", 0):
            lines.append(f"🔒 {name}: {v.get('high', 0)} high / {v.get('critical', 0)} critical npm "
                         f"vulns in {os.path.relpath(f, repo_dir)}")
    return lines
