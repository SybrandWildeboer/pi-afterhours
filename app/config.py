"""Load config.json and fill in defaults, so a minimal file works and mistakes are explained."""
import copy
import json
from pathlib import Path


class ConfigError(Exception):
    pass


DEFAULTS = {
    "channel": "",          # Slack channel id; empty = Slack off (no gate, no posts, no idle rule)
    "profile": "work",      # Claude profile that runs the loop's agents
    "me": "",               # your GitHub login: PRs by anyone else are "human PRs"
    "projects_root": "",    # folder that holds your repo checkouts (required)
    "auto_merge": False,
    "max_fix_per_run": 1,
    "max_new_prs_per_repo_day": 3,
    "max_diff_lines": 400,
    "stale_human_pr_days": 3,
    "ci_max_age_days": 14,
    "protected_paths": ["deploy", "infra", "workflows", "secrets", "prod"],
    "models": {"gate": "haiku", "post": "haiku", "spec": "sonnet", "fix": "sonnet", "review": "sonnet"},
    "budget_usd": {"gate": 0.05, "post": 0.05, "spec": 0.6, "fix": 1.5, "review": 0.4},
    "repos": [],
    "workspaces": [],
    "plugins": {"off": [], "spec": [], "fix": []},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path):
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"{path} not found: copy config.example.json to config.json and edit it") from None
    except ValueError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: the top level must be a JSON object")
    if not isinstance(raw.get("auto_merge", False), bool):
        raise ConfigError("config.json: 'auto_merge' must be true or false (not a string)")
    cfg = _merge(DEFAULTS, raw)
    if not cfg["projects_root"]:
        raise ConfigError("config.json: 'projects_root' is required (the folder that holds your repo checkouts)")
    for i, repo in enumerate(cfg["repos"]):
        for key in ("name", "path", "gh"):
            if not repo.get(key):
                raise ConfigError(f"config.json: repos[{i}] is missing '{key}'")
    return cfg
