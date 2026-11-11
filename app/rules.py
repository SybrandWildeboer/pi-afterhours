"""Pure decision rules for the maintenance loop. No I/O, so every rule is unit-tested."""
import hashlib
import re
from datetime import datetime, timedelta

BOTS = {"dependabot[bot]", "app/dependabot", "renovate[bot]", "app/renovate"}
_BAD = {"FAILURE", "TIMED_OUT", "CANCELLED", "ERROR", "STARTUP_FAILURE", "ACTION_REQUIRED"}
_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_SECRET = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprse][.-][A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}"
    r"|dapi[0-9a-f]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def redact(text):
    return _SECRET.sub("[redacted]", text)


def clean(text, n=120):
    """Untrusted text (PR titles, logs) that ends up in a Slack line: one line, no mentions, no markup."""
    t = re.sub(r"[<>`\r\n\t]+", " ", str(text)).replace("@", "@​").strip()
    return redact(t)[: n - 1] + "…" if len(t) > n else redact(t)


def _ver(s):
    m = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", s.strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def semver_bump(old, new):
    a, b = _ver(old), _ver(new)
    if not a or not b or b <= a:
        return "unknown"
    if a[0] != b[0]:
        return "major"
    if a[1] != b[1]:
        return "major" if a[0] == 0 else "minor"  # in 0.x a minor bump may break
    return "patch"


def title_bump(title):
    ms = re.findall(r"from (\S+) to (\S+)", title)
    return semver_bump(*ms[0]) if len(ms) == 1 else "unknown"  # a grouped bump is judged by you, not by the first pair


def is_maint_pr(pr, cfg):
    """Only PRs this bot opened: its label AND its branch prefix AND the bot's own account. A label alone is not enough."""
    return ("maint-bot" in {l["name"] for l in pr["labels"]} and pr.get("headRefName", "").startswith("maint/")
            and pr["author"]["login"] == cfg["me"])


def checks_state(rollup):
    if not rollup:
        return "none"
    res = [(i.get("conclusion") or i.get("state") or "").upper() for i in rollup]
    if any(r in _BAD for r in res):
        return "red"
    return "green" if all(r in _OK for r in res) else "pending"


def is_protected(path, protected):
    p = path.lower()
    return any(x in p for x in protected)


def can_merge(pr, cfg):
    """(ok, reason). Never True for drafts, conflicts, red/pending checks, big diffs, protected paths."""
    if pr.get("isDraft"):
        return False, "draft"
    if pr.get("mergeable") == "UNKNOWN":  # GitHub computes this lazily: look again next run
        return False, "mergeable unknown"
    if pr.get("mergeable") != "MERGEABLE":
        return False, f"mergeable={pr.get('mergeable')}"
    c = checks_state(pr.get("statusCheckRollup"))
    if c != "green":
        return False, f"checks {c}"
    if (pr.get("additions") or 0) + (pr.get("deletions") or 0) > cfg["max_diff_lines"]:
        return False, "diff too large"
    files = pr.get("files") or []
    if len(files) >= 100:  # gh lists at most 100 files, so we cannot see them all
        return False, "too many files to check"
    hit = [f["path"] for f in files if is_protected(f["path"], cfg["protected_paths"])]
    if hit:
        return False, f"touches protected path {hit[0]}"
    return True, "ok"


def bot_pr_action(pr, cfg):
    """Dependabot/Renovate PRs -> ('skip'|'wait'|'merge'|'report', reason)."""
    if pr["author"]["login"] not in BOTS:
        return "skip", "not a bot"
    bump = title_bump(pr["title"])
    if bump not in ("patch", "minor"):
        return "report", f"{bump} bump needs you"
    ok, why = can_merge(pr, cfg)
    if ok:
        return "merge", f"{bump} bump, checks green"
    return ("wait" if why in ("checks pending", "mergeable unknown") else "report"), why


def idle_days(updated_iso, now):
    return (now - datetime.fromisoformat(updated_iso.replace("Z", "+00:00"))).days


def _h(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def is_seen(posted, key, now, ttl_days=7):
    t = posted.get(_h(key))
    return bool(t) and now - datetime.fromisoformat(t) < timedelta(days=ttl_days)


def mark(posted, key, now):
    posted[_h(key)] = now.isoformat()


def seen(posted, key, now, ttl_days=7):
    """True if already posted within ttl; otherwise records it and returns False."""
    if is_seen(posted, key, now, ttl_days):
        return True
    mark(posted, key, now)
    return False


def recent(attempts, key, now, hours):
    """True if `key` was recorded less than `hours` ago (a cooldown check)."""
    t = attempts.get(key)
    return bool(t) and now - datetime.fromisoformat(t) < timedelta(hours=hours)


def prune(S, now):
    """Keep state.json small: drop expired entries, keep the newest 50 reviews/specs."""
    old = lambda days: (now - timedelta(days=days)).isoformat()
    S["posted"] = {k: v for k, v in S["posted"].items() if v >= old(14)}
    S["fix_attempts"] = {k: v for k, v in S["fix_attempts"].items() if v >= old(30)}
    S["prs_today"] = {k: v for k, v in S["prs_today"].items() if k.endswith(str(now.date()))}
    for k in ("reviewed", "specs"):
        S[k] = dict(list(S[k].items())[-50:])
