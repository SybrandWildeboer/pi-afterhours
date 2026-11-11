# 09 Troubleshooting

Start with the doctor, then share the redacted diagnostics if you ask for help:

```bash
scripts/doctor.sh                       # OK / WARN / FAIL per check
python3 scripts/collect_diagnostics.py  # redacted; read it before sharing
```

## Lessons from the build

**`scp -r` fails with "Connection closed".** A weak Wi-Fi link. Copy files one at a time with retries, send long jobs with `nohup` and poll them, or plug in Ethernet ([01](01-hardware-and-os.md)).

**`<hostname>.local` does not resolve, or times out.** IPv6 name resolution over a lossy link. Use the IPv4 address (`ping -4 <hostname>.local`, or your router's device list). Windows Subsystem for Linux often cannot reach `.local` names at all.

**A headless run hangs and never finishes.** Almost always the workspace trust prompt for a folder the profile has not seen. Run `scripts/seed_trust.py PROFILE_DIR FOLDER` ([02](02-profiles-and-logins.md)).

**`gh` says "not logged in" after a reboot.** The token was in the locked desktop keyring. Log in again with `--insecure-storage` ([03](03-github.md)).

**`claude` works in SSH but cron or systemd cannot find it, or a tool needs `node`.** Cron and systemd have a minimal `PATH`. The shipped crontab and units set `~/.local/bin`; if you installed `node` or `claude` somewhere else, add that directory to the `PATH=` line.

**The Slack read takes minutes.** On a bad link the gate agent's first tool call is slow. It is the network, not the model. Fix the link first.

**Boot takes over a minute and a half.** Either the lightdm wait for a missing GPU node ([06](06-dashboard-and-screen.md)), or a stale `/etc/fstab` entry for a disk that no longer exists (mark it `nofail`).

**The dashboard is blank.** Check `systemctl --user status maint-dash`, then `curl -s localhost:8787/ | head`. The kiosk waits for that URL to answer.

**Remote Control does not appear in the app.** Check `systemctl --user status claude-remote`, that you answered yes to "Enable Remote Control?" once, and that the profile is logged in (`cc personal auth status`).

**A plugin warning from the doctor.** A plugin listed in `config.json` is not installed in that profile. Install it with `cc <profile>` and `/plugin`, or remove it from the config; the loop runs without it.

## Appendix: laptop-side helpers (Windows and WSL)

If you work from Windows with WSL, WSL may not reach the Pi (no IPv6 route, no mDNS) even though Windows can. The workaround used while building this:

1. **Call Windows' own `ssh.exe` from WSL**, for instance with a tiny wrapper script:

   ```bash
   #!/usr/bin/env bash
   # ~/.local/bin/pi: run a command on the Pi through Windows' ssh.exe
   exec powershell.exe -NoProfile -Command "ssh -o BatchMode=yes <user>@<hostname>.local '$*'"
   ```

   Pass `</dev/null` when scripting so ssh does not wait on stdin.
2. **Send scripts as base64**, because PowerShell mangles quotes. `echo "$B64" | base64 -d | bash` on the Pi runs exactly what you wrote:

   ```bash
   B64=$(base64 -w0 my-script.sh)
   pi "echo $B64 | base64 -d | bash"
   ```
3. **Copy files one by one**, with a few retries each, over the IPv4 address, using `scp.exe` and `wslpath -w` to convert paths. Directory copies are what a flaky link breaks.
4. **Prefer the Pi's IPv4 address** over the `.local` name from Windows too, if the name is slow.

On macOS or Linux none of this is needed: plain `ssh` and `rsync` work.
