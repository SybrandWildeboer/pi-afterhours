#!/usr/bin/env bash
# pi-afterhours installer. Idempotent: run it again any time. Start with --dry-run.
#
#   ./install.sh [--dry-run] [--yes] [--user NAME] [--touch-device NAME] [--touch-output NAME] [--go-live]
#                [--root DIR] [--skip-system]
#
#   --dry-run       print what would happen, change nothing
#   --yes           do not ask before each system change
#   --go-live       switch the cron entries from dry-run to --live (needs config.json; refuses if auto_merge is on)
#   --root DIR      write everything under DIR instead of / (for tests)
#   --skip-system   skip apt, systemctl, loginctl, nmcli and sudo (for tests)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
DRY=0; YES=0; ROOT=""; SKIP_SYSTEM=0; GO_LIVE=0
USER_NAME="$(id -un)"; TOUCH_DEVICE=""; TOUCH_OUTPUT="DSI-1"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --root) ROOT="${2:?--root needs a directory}"; shift ;;
    --user) USER_NAME="${2:?--user needs a name}"; shift ;;
    --touch-device) TOUCH_DEVICE="${2:?--touch-device needs a name}"; shift ;;
    --touch-output) TOUCH_OUTPUT="${2:?--touch-output needs a name}"; shift ;;
    --skip-system) SKIP_SYSTEM=1 ;;
    --go-live) GO_LIVE=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "$ROOT" ] && [ "$USER_NAME" = "$(id -un)" ]; then HOME_DIR="$HOME"; else HOME_DIR="/home/$USER_NAME"; fi
PROJECTS="$HOME_DIR/projects"
HOSTNAME_VALUE="$(hostname 2>/dev/null || echo pi)"
SUDO=""
if [ -z "$ROOT" ] && [ "$SKIP_SYSTEM" = 0 ] && [ "$(id -u)" != 0 ]; then SUDO=sudo; fi
CRON_FILE="$ROOT$HOME_DIR/.pi-afterhours.crontab"   # only used with --root

P() { printf '%s%s' "$ROOT" "$1"; }
phase() { printf '\n== phase: %s\n' "$1"; }
# act WHAT CMD...: say what is about to happen; under --dry-run stop there
act() {
  local what="$1"; shift
  if [ "$DRY" = 1 ]; then echo "  would: $what"; return 0; fi
  echo "  $what"; "$@"
}
confirm() { [ "$YES" = 1 ] || [ "$DRY" = 1 ] || { read -r -p "  $1 [y/N] " answer; [ "$answer" = y ]; }; }
# put SRC DEST [MODE]: install a file (creating folders) unless it is already identical. /etc needs sudo on a real Pi.
put() {
  local src="$1" dest="$2" mode="${3:-644}" real; real="$(P "$dest")"
  if [ -f "$real" ] && cmp -s "$src" "$real"; then return 0; fi
  local elevate=()
  case "$dest" in /etc/*) [ -n "$SUDO" ] && elevate=("$SUDO") ;; esac
  act "write $dest" "${elevate[@]}" bash -c 'mkdir -p "$(dirname "$2")" && install -m "$3" "$1" "$2"' _ "$src" "$real" "$mode"
}
read_cron() { if [ -n "$ROOT" ]; then cat "$CRON_FILE" 2>/dev/null || true; else crontab -l 2>/dev/null || true; fi; }
write_cron() {
  if [ -n "$ROOT" ]; then mkdir -p "$(dirname "$CRON_FILE")"; printf '%s\n' "$1" > "$CRON_FILE"; else printf '%s\n' "$1" | crontab -; fi
}

phase preflight
command -v python3 >/dev/null || { echo "ERROR: python3 is required" >&2; exit 1; }
command -v claude >/dev/null || { echo "ERROR: 'claude' was not found on PATH. Install Claude Code first (docs/02-profiles-and-logins.md), then run this again." >&2; exit 1; }
if ! msgs="$(python3 "$REPO/scripts/detect.py" claude-check)"; then echo "$msgs" >&2; exit 1; fi
echo "$msgs" | sed 's/^/  /'
grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null || echo "  WARN: this does not look like a Raspberry Pi (tested: Pi 5, Raspberry Pi OS based on Debian 13)"

if [ "$GO_LIVE" = 1 ]; then
  phase go-live
  cfg="$(P "$HOME_DIR/maint/app/config.json")"
  [ -f "$cfg" ] || { echo "ERROR: $HOME_DIR/maint/app/config.json does not exist. Copy config.example.json to config.json, edit it, and watch a dry-run first (docs/05-maintenance-loop.md)." >&2; exit 1; }
  python3 -c 'import json,sys; sys.exit(1 if json.load(open(sys.argv[1])).get("auto_merge") else 0)' "$cfg" \
    || { echo "ERROR: auto_merge is on in config.json. Turn it off before going live." >&2; exit 1; }
  current="$(read_cron)"
  case "$current" in *"# BEGIN pi-afterhours"*) ;; *) echo "ERROR: no pi-afterhours cron entries found: run ./install.sh first" >&2; exit 1 ;; esac
  act "switch the cron entries to --live (the loop will post, and may open PRs)" write_cron "$(printf '%s\n' "$current" | python3 "$REPO/scripts/cron_block.py" live)"
  exit 0
fi

phase detect
if [ -z "$TOUCH_DEVICE" ] && [ "$SKIP_SYSTEM" = 0 ]; then TOUCH_DEVICE="$(python3 "$REPO/scripts/detect.py" touch | head -n 1)"; fi
if [ -z "$TOUCH_DEVICE" ]; then
  echo "  WARN: no touchscreen found. Find its name with 'libinput list-devices', then run again with --touch-device NAME"
  TOUCH_DEVICE="CHANGE-ME-touch-device"
else echo "  touchscreen: $TOUCH_DEVICE (output $TOUCH_OUTPUT)"; fi
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
python3 "$REPO/scripts/render.py" "$REPO/templates" "$STAGE" USER="$USER_NAME" HOME="$HOME_DIR" HOSTNAME="$HOSTNAME_VALUE" \
  PROJECTS="$PROJECTS" TOUCH_DEVICE="$TOUCH_DEVICE" TOUCH_OUTPUT="$TOUCH_OUTPUT" >/dev/null

phase packages
if [ "$SKIP_SYSTEM" = 1 ]; then echo "  skipped (--skip-system)"
elif confirm "Install packages with apt (jq pipx labwc grim lightdm chromium libinput-tools git curl)?"; then
  act "apt install" ${SUDO:+"$SUDO"} apt-get install -y jq pipx labwc grim lightdm chromium libinput-tools git curl
  act "pipx install pip-audit" pipx install pip-audit
else echo "  skipped"; fi

phase profiles
for f in cc cc-agents xdg-open; do put "$REPO/bin/$f" "$HOME_DIR/.local/bin/$f" 755; done
for p in work personal; do
  [ -e "$(P "$HOME_DIR/.claude-profiles/$p/CLAUDE.md")" ] || put "$STAGE/profiles/$p.CLAUDE.md" "$HOME_DIR/.claude-profiles/$p/CLAUDE.md"
  act "record workspace trust for $PROJECTS in profile $p" python3 "$REPO/scripts/seed_trust.py" "$(P "$HOME_DIR/.claude-profiles/$p")" "$PROJECTS"
done
act "create $PROJECTS and the loop's work folder" mkdir -p "$(P "$PROJECTS")" "$(P "$HOME_DIR/maint/work")"

phase app
act "copy the loop and dashboard to $HOME_DIR/maint/app (config.json, state and logs are never touched)" bash -c \
  'mkdir -p "$2" && tar -C "$1" --exclude=config.json --exclude="state.json*" --exclude="ledger*.csv" --exclude=events.jsonl --exclude=__pycache__ -cf - . | tar -C "$2" -xf - && chmod +x "$2/run.py" "$2/dash.py" "$2/push-maint" "$2/kiosk.sh"' \
  _ "$REPO/app" "$(P "$HOME_DIR/maint/app")"
echo "  next: copy app/config.example.json to config.json and edit it (docs/05-maintenance-loop.md)"

phase services
for u in claude-remote claude-remote-work maint-dash; do put "$STAGE/systemd/$u.service" "$HOME_DIR/.config/systemd/user/$u.service"; done
for f in claude-remote-settings.json claude-remote-work-settings.json; do put "$STAGE/etc/$f" "/etc/$f"; done
if [ "$SKIP_SYSTEM" = 0 ]; then
  act "enable lingering so the services start at boot" ${SUDO:+"$SUDO"} loginctl enable-linger "$USER_NAME"
  act "start the dashboard service" bash -c 'systemctl --user daemon-reload && systemctl --user enable --now maint-dash.service'
  echo "  the Remote Control services are enabled after both profiles are logged in (see the logins phase)"
fi

phase display
put "$STAGE/labwc/autostart" "$HOME_DIR/.config/labwc/autostart"
put "$STAGE/labwc/rc.xml" "$HOME_DIR/.config/labwc/rc.xml"
put "$STAGE/lightdm/50-afterhours.conf" "/etc/lightdm/lightdm.conf.d/50-afterhours.conf"
if [ "$SKIP_SYSTEM" = 0 ]; then
  if python3 "$REPO/scripts/detect.py" lightdm-override >/dev/null; then
    echo "  this Pi has no GPU render node, so lightdm would wait 90 s for it at every boot"
    if [ -f /usr/lib/systemd/system/lightdm.service ] && [ ! -f /etc/systemd/system/lightdm.service ] \
       && confirm "Install a copy of lightdm.service without that wait?"; then
      act "write /etc/systemd/system/lightdm.service" ${SUDO:+"$SUDO"} bash -c \
        'sed "s/ dev-dri-renderD128\.device//g" /usr/lib/systemd/system/lightdm.service > /etc/systemd/system/lightdm.service && systemctl daemon-reload'
    fi
  fi
  if confirm "Boot to the graphical session (lightdm autologin into the dashboard)?"; then
    act "set the graphical target" ${SUDO:+"$SUDO"} systemctl set-default graphical.target
    act "enable lightdm" ${SUDO:+"$SUDO"} systemctl enable lightdm
  fi
  wifi="$(nmcli -t -f NAME,TYPE con show --active 2>/dev/null | awk -F: '$2 ~ /wireless/ {print $1; exit}')"
  if [ -n "$wifi" ] && confirm "Switch Wi-Fi power saving off for '$wifi' (it drops incoming connections)?"; then
    act "wifi power save off" ${SUDO:+"$SUDO"} nmcli con mod "$wifi" 802-11-wireless.powersave 2
  fi
fi

phase cron
{ echo "# BEGIN pi-afterhours"; cat "$STAGE/crontab"; echo "# END pi-afterhours"; } > "$STAGE/block"
if [ -z "$ROOT" ] && [ "$SKIP_SYSTEM" = 1 ]; then echo "  skipped (--skip-system)"
else
  current="$(read_cron)"
  new="$(printf '%s\n' "$current" | python3 "$REPO/scripts/cron_block.py" replace "$STAGE/block")"
  if [ "$new" = "$current" ]; then echo "  cron entries already up to date (dry-run mode: nothing posts or merges)"
  else act "install the cron entries (dry-run mode: nothing posts or merges until --go-live)" write_cron "$new"; fi
fi

phase logins
cat <<'TXT'
  These steps need you (a browser or a phone), so the installer only prints them. Run them on the Pi, one at a time:
    cc personal auth login                              # your personal Claude account
    cc work auth login                                  # your work Claude account
    gh auth login -p ssh -w --insecure-storage -s repo -s read:org
    databricks auth login --profile <name>              # optional; over SSH use: ssh -L 8020:localhost:8020 <pi>
  then, once, answer yes to "Enable Remote Control?" with: cc personal remote-control   (stop it with Ctrl+C), same for work,
  and enable the phone and desktop services:
    systemctl --user enable --now claude-remote.service claude-remote-work.service
TXT

phase doctor
if [ "$DRY" = 1 ]; then echo "  would: run scripts/doctor.sh"
else bash "$REPO/scripts/doctor.sh" ${ROOT:+--root "$ROOT"} --user "$USER_NAME" || echo "  (the doctor found problems above: fix them and run ./install.sh again)"; fi
echo; echo "done. The cron entries are in dry-run mode. When you have watched a dry-run and read docs/07-security-model.md: ./install.sh --go-live"
