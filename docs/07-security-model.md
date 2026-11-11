# 07 Security model

Read this before `./install.sh --go-live`.

## What you are running

Unattended AI agents, on a small always-on computer, holding: a GitHub token, one or two Claude logins, optionally Slack access and Databricks OAuth tokens. The agents read content written by other people (PR titles, CI logs, Slack messages), which is a prompt-injection surface.

## Defaults that reduce the risk

- **Dry-run until you say so.** Cron starts in dry-run; `--go-live` is a separate, deliberate step.
- **`auto_merge` is off**, and `--go-live` refuses if you turn it on. Fixes are pull requests.
- **One small agent per task**, each with a model, a spending cap (`--max-budget-usd`), an explicit tool allowlist and a deny list for credential paths. The review agent can only see PR diffs; the gate agent can only read Slack.
- **Slack text is data.** The gate agent classifies and returns JSON; the code, not the model, decides what happens next.
- **Narrow write paths.** The fix agent may not run `git commit`, `git push` or `gh pr create` directly (those accept file arguments such as `-F` or `--body-file` that could copy a token into a commit or PR). It runs `maint-commit`, `push-maint` and `maint-pr`: wrapper scripts with fixed arguments that work only on a `maint/<name>` branch, take the message and body as literal text, and never run repository hooks. The worktree is created by code, not by the model.
- **The permission mode is forced** to `default` on every agent call, so a `bypassPermissions` default in the profile's own settings is not inherited. The profile's allow rules and hooks (`--setting-sources user`) still load: keep the loop profile's `settings.json` free of broad `Bash(*)` allows.
- **Settings are scoped** with `--setting-sources user`, so a repository's own `.claude/settings.json` cannot widen the agents' permissions, and only the Slack agents get any connectors (`--strict-mcp-config` for the rest).
- **The dashboard binds to localhost** only.
- **Remote Control asks before acting** (`--permission-mode default`).
- **A diagnostics collector redacts** emails, IPs, MACs, tokens, your username and hostname before you share anything.

## Known limits

> **The profile and credential rules are a soft wall.** The deny rules block Claude's Read, Edit and Write tools on credential paths. They do not stop a shell command: a session on the Pi that can run `cat` can read any file your Linux user can, including the other profile's login, the `gh` token and Databricks tokens.

Concretely:

1. **Same Linux user for everything.** The work and personal profiles are not isolated from each other. Remote Control from the phone (personal account) can run commands as that user. Hardening: separate OS users per profile.
2. **Tokens are on disk in plaintext** (`~/.config/gh/hosts.yml`, `~/.databricks`, profile credentials) so unattended runs survive a reboot. Anyone with shell access to the Pi has them. Use narrow scopes, and revoke them if the Pi is lost.
3. **Prompt injection is mitigated, not solved.** A hostile PR or Slack message could try to steer an agent. The allowlists and the push wrapper limit what it could do; they do not make it impossible to waste your money or open an unwanted PR.
4. **Allowlists match prefixes.** An allowed `Bash(git commit:*)` allows any `git commit` arguments. The push path is a script for this reason.
5. **Branch protection is your backstop.** Only some repositories may protect `main`; check yours.
6. **The installer is untested from scratch** on a clean Pi.
7. **Costs are capped per call, not per day.** See [08](08-costs-and-limits.md).

## If something goes wrong

Stop the loop first: remove or comment the cron entries (`crontab -e`), then `systemctl --user stop claude-remote claude-remote-work`. Rotate the tokens on the Pi (GitHub, Slack, Databricks) and log out of the Claude profiles. Then read `~/maint/events.jsonl` and `run.log`. See also [SECURITY.md](../SECURITY.md).
