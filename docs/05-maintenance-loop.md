# 05 The maintenance loop

## Modes

`run.py` lives in `~/maint/app`. Without `--live` it is a **dry-run**: it reads and prints, and never posts to Slack, pushes, opens PRs or saves state.

| Command | What it does | Cron |
|---|---|---|
| `python3 run.py gate` | reads Slack, answers requests ("spec ..." or "scan now") | every 30 min, 07:00-21:30 |
| `python3 run.py full` | gate first, then repos: PRs, failing CI, audits | hourly, weekdays 08:05-18:05 |
| `python3 run.py dbx` | Databricks health check | once, weekdays 07:10 |
| `python3 run.py spec "<idea>"` | prints a spec for an idea (no Slack, no state) | manual |
| `python3 run.py cost` | tokens and estimated dollars per run, and per-day totals | manual |

Times are the Pi's local time. Edit your crontab to change them; the installer only rewrites the block between its `BEGIN`/`END pi-afterhours` markers.

## Dry-run first, then live

1. Copy `config.example.json` to `config.json`: your repos, your GitHub login (`me`), your projects folder, and optionally a Slack channel id.
2. Run `python3 run.py full` by hand and read the output. The installed cron entries are also dry-run.
3. When you are happy: `./install.sh --go-live`. It requires `config.json`, refuses if `auto_merge` is on, and switches the cron entries to `--live`.

Going live means the loop **posts to Slack and may open pull requests** from the fix agent. It never merges.

Slack is optional: with `"channel": ""` there is no gate, no posts and no idle rule; the loop only prints.

## The idle rule

The first step of every `full` run is to read the last bot post in the channel. If that post ends with "no further action" and you have written nothing new since, the run stops there (one small call, around a cent). The first full run of each day still does a sweep. A post carries the marker only when nothing is in progress. This is what stops the loop paying to repeat the same work every hour.

## Cooldowns and limits

- One fix attempt per failing workflow, and per repository and workflow, every 72 hours.
- `max_fix_per_run` 1, `max_new_prs_per_repo_day` 3, `max_diff_lines` 400.
- `protected_paths` (deploy, infra, workflows, secrets, prod) are not touched by a fix.
- All of these are in `config.json`; defaults are in `app/config.py`.

## Small agents

Each task is a separate `claude -p` call with a fixed model, a spending cap (`--max-budget-usd`), a tool allowlist, a deny list, no session saved, and plugins only where `config.json` names them. The agent prompts are plain Markdown in `app/agents/`.

| Task | Default model | Cap | Can use |
|---|---|---|---|
| gate | haiku | $0.05 | read Slack only |
| post | haiku | $0.05 | send one Slack message |
| spec | sonnet | $0.60 | read your projects, no writes |
| review | sonnet | $0.40 | `gh pr view/diff/checks` only |
| fix | sonnet | $1.50 | edit a scratch worktree, `git`, `push-maint`, `gh pr create` |

The fix agent works in a worktree the code creates under `~/maint/work`, and can push only through `push-maint`. See [security](07-security-model.md) for what that does and does not guarantee.

## Where to look

- `~/maint/run.log` the cron output.
- `~/maint/ledger.csv` one row per agent call, with tokens and estimated cost.
- `~/maint/events.jsonl` one-line events, shown on the dashboard.
- `~/maint/app/state.json` what has been posted and when (do not edit by hand).
