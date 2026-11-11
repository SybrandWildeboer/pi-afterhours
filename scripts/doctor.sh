#!/usr/bin/env bash
# Health check for a pi-afterhours install. usage: doctor.sh [--root DIR] [--user NAME]
# One line per check: OK / WARN / FAIL / SKIP. Exit 1 if any check FAILs.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT=""; USER_NAME="$(id -un)"
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="${2:?--root needs a directory}"; shift ;;
    --user) USER_NAME="${2:?--user needs a name}"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ -z "$ROOT" ] && [ "$USER_NAME" = "$(id -un)" ]; then HOME_DIR="$HOME"; else HOME_DIR="/home/$USER_NAME"; fi
P() { printf '%s%s' "$ROOT" "$1"; }
FAILS=0
ok() { printf 'OK   %s\n' "$1"; }
warn() { printf 'WARN %s: %s\n' "$1" "$2"; }
fail() { printf 'FAIL %s: %s\n' "$1" "$2"; FAILS=$((FAILS + 1)); }
skip() { printf 'SKIP %s: %s\n' "$1" "$2"; }

APP="$(P "$HOME_DIR/maint/app")"; CFG="$APP/config.json"; channel="-"
if [ -f "$APP/run.py" ]; then ok "app installed"; else fail "app installed" "no $HOME_DIR/maint/app/run.py: run ./install.sh"; fi
if [ -f "$CFG" ]; then
  vals="$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print("on" if c.get("auto_merge") else "off", c.get("channel") or "-")' "$CFG" 2>/dev/null)"
  if [ -z "$vals" ]; then fail "config.json" "is not valid JSON"
  else
    ok "config.json"; channel="${vals#* }"
    [ "${vals%% *}" = on ] && warn "auto_merge" "is on: PRs can be merged without you"
  fi
else fail "config.json" "missing: copy app/config.example.json to config.json and edit it"; fi

if [ -n "$ROOT" ]; then cron_text="$(cat "$(P "$HOME_DIR/.pi-afterhours.crontab")" 2>/dev/null)"; else cron_text="$(crontab -l 2>/dev/null)"; fi
n="$(printf '%s\n' "$cron_text" | grep -c 'run.py' || true)"
if [ "$n" -ge 3 ]; then
  if printf '%s\n' "$cron_text" | grep 'run.py' | grep -q -- '--live'; then ok "cron entries (live: the loop posts and may open PRs)"; else ok "cron entries (dry-run)"; fi
else fail "cron entries" "found $n of 3: run ./install.sh"; fi

if command -v claude >/dev/null; then
  while IFS= read -r line; do
    case "$line" in
      ERROR*) fail "claude" "${line#ERROR: }" ;;
      WARN*) warn "claude" "${line#WARN: }" ;;
      "claude: ok") ok "claude version and flags" ;;
    esac
  done < <(python3 "$REPO/scripts/detect.py" claude-check)
else fail "claude" "not on PATH: install Claude Code (docs/02-profiles-and-logins.md)"; fi

if [ -n "$ROOT" ]; then skip "system checks" "logins, services, dashboard, display and Wi-Fi need the real machine (--root was given)"; exit $((FAILS > 0 ? 1 : 0)); fi

for p in work personal; do
  if CLAUDE_CONFIG_DIR="$HOME_DIR/.claude-profiles/$p" claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then ok "profile $p logged in"
  else fail "profile $p" "not logged in: cc $p auth login"; fi
done
if gh auth status >/dev/null 2>&1; then ok "gh logged in"; else fail "gh" "not logged in: gh auth login -p ssh -w --insecure-storage"; fi
if [ "$channel" = "-" ]; then skip "slack" "off (channel is empty in config.json)"
elif CLAUDE_CONFIG_DIR="$HOME_DIR/.claude-profiles/$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile","work"))' "$CFG")" claude mcp list 2>/dev/null | grep -i slack | grep -q Connected; then ok "slack connector"
else fail "slack connector" "not connected: connect Slack in claude.ai for the loop's profile"; fi
for u in maint-dash claude-remote claude-remote-work; do
  if [ "$(systemctl --user is-active "$u" 2>/dev/null)" = active ]; then ok "service $u"; else fail "service $u" "not active: systemctl --user status $u"; fi
done
if curl -sf -m 5 http://127.0.0.1:8787/api/state >/dev/null; then ok "dashboard answers on 127.0.0.1:8787"; else fail "dashboard" "no answer on 127.0.0.1:8787"; fi
if pgrep -x labwc >/dev/null; then ok "display session (labwc)"; else warn "display session" "labwc is not running (no screen attached, or not booted to the graphical target)"; fi
if [ ! -e /dev/dri/renderD128 ] && [ ! -f /etc/systemd/system/lightdm.service ]; then warn "lightdm" "no GPU render node and no override: the screen may wait 90 s at boot"; else ok "lightdm start-up"; fi
if iw dev wlan0 get power_save 2>/dev/null | grep -qi ' on'; then warn "wifi" "power saving is on and drops incoming connections: nmcli con mod <name> 802-11-wireless.powersave 2"; fi
if [ -f "$CFG" ]; then
  listed="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])).get("plugins",{}); print("\n".join(sum(p.values(), [])))' "$CFG" 2>/dev/null)"
  for prof in work personal; do
    for name in $(CLAUDE_CONFIG_DIR="$HOME_DIR/.claude-profiles/$prof" claude plugin list 2>/dev/null | grep -oE '[A-Za-z0-9._-]+@[A-Za-z0-9._-]+' | sort -u); do
      printf '%s\n' "$listed" | grep -qxF "$name" || warn "plugin $name ($prof)" "installed but not listed in config.json plugins: it may load into agents and add cost"
    done
  done
fi
exit $((FAILS > 0 ? 1 : 0))
