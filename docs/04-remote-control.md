# 04 Remote Control and delegation

## Two services

Claude Code's Remote Control lets the Claude phone app or Claude Desktop drive a session running on another machine. The installer ships two user systemd units, one per account:

| Unit | Profile | Shows up in | Device name |
|---|---|---|---|
| `claude-remote.service` | `personal` | the Claude phone app | the Pi's hostname |
| `claude-remote-work.service` | `work` | Claude Desktop on the work account | hostname + `-work` |

Both run `claude remote-control --permission-mode default --capacity 3` from your projects folder, under `script -qfc` because the command draws a terminal UI and needs a pseudo-terminal. `loginctl enable-linger` keeps them running with nobody logged in. Enable them **after** both profiles are logged in and you have answered yes once to "Enable Remote Control?" ([02](02-profiles-and-logins.md)):

```bash
systemctl --user enable --now claude-remote.service claude-remote-work.service
systemctl --user status claude-remote.service
```

## Permission mode and the deny files

`--permission-mode default` means Claude asks before it edits or runs a command; you approve from the phone. Do not change this to a mode that skips prompts. `capacity 3` allows three concurrent sessions per account.

`/etc/claude-remote-settings.json` and `/etc/claude-remote-work-settings.json` carry deny rules for the credential folders (`~/.ssh`, `~/.config/gh`, `~/.databricks`, the profile directories) and for editing the loop's own code. They are passed with `--settings`.

Loop runs (`claude -p`) never appear in Claude Desktop or the phone app: they are headless and not sessions. The [dashboard](06-dashboard-and-screen.md) is where you see them.

## Delegating a task between profiles

From a project directory, hand a self-contained task to the other account:

```bash
cc personal --bg "<the full prompt, with all context>"   # prints a session id
cc-agents                                                # list background sessions
cc personal logs <id>                                    # read its output
cc personal stop <id>                                    # stop it
```

The generated `CLAUDE.md` in each profile tells Claude to delegate only when you ask or when a task is clearly independent, and never to copy code or data between the work and personal profiles unless you say so. The delegate does not see the conversation that started it, so the prompt must carry everything.

> **This is a soft wall.** The rule against crossing profiles is an instruction to a model, not an enforcement boundary. Both profiles run as the same Linux user, so a shell command run from either one could read the other's files. The deny rules cover Claude's Read, Edit and Write tools, not what a shell command can do. If your work account must stay isolated from your personal one, run the profiles as **separate Linux users** (not covered by the installer), or do not run both on one Pi. See [the security model](07-security-model.md).

## Hardening you can do

- Keep `--permission-mode default`, and read each prompt on the phone.
- Put Remote Control for the work account on a separate OS user.
- Remove a service you do not use: `systemctl --user disable --now claude-remote.service`.
