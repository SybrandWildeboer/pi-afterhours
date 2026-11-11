# 02 Profiles and logins

## Two profiles with `cc`

`bin/cc` runs Claude Code with its own config directory, so each account has its own login, settings, plugins and history:

```bash
cc work     auth login      # CLAUDE_CONFIG_DIR=~/.claude-profiles/work
cc personal auth login
cc work                     # interactive session as the work account
```

Profile names are letters, digits, `-` and `_`. `cc-agents` lists background sessions across profiles.

The installer creates `work` and `personal` and writes a small `CLAUDE.md` into each, explaining delegation to the other (see [Remote Control](04-remote-control.md)).

## Which profile does what

`config.json` has `"profile"`: the account the loop's agents run as. The work profile is the default. The personal profile is meant for Remote Control to your phone and for your own sessions.

## Logins need a human

The installer only prints these, because they need a browser or phone. Run them on the Pi, one at a time:

```bash
cc personal auth login
cc work auth login
```

Over SSH the CLI prints a URL; open it on your laptop and paste the code back. For tools that use a local callback port (Databricks), tunnel it: `ssh -L 8020:localhost:8020 <pi>`.

After both are logged in, answer yes once to "Enable Remote Control?" with `cc personal remote-control` (stop with Ctrl+C), the same for `work`, then enable the services (see [04](04-remote-control.md)).

## Workspace trust is pre-seeded

A headless run that hits the "do you trust this folder?" prompt just hangs. `scripts/seed_trust.py PROFILE_DIR PROJECT_PATH` records the folder as trusted in a profile. The installer does this for your projects folder; run it again for any new folder a service or the loop works in.

## Plugins

`config.json` lists plugins per task (`off`, `spec`, `fix`). Agents start with plugins off and only the named ones for the named task. `config.example.json` lists two example plugins; the doctor warns when a listed plugin is not installed in the profile, and the loop still runs without it.
