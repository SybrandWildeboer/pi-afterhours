# 01 Hardware and OS

## What this was built and tested on

- Raspberry Pi 5, 4 GB, with a 7-inch DSI touchscreen (720x1280, portrait, Goodix touch controller).
- Raspberry Pi OS based on Debian 13 ("trixie"), booting to the graphical target.
- Wi-Fi only. See the warning below.

Anything else is untested. A Pi 4 or a different screen will probably work; the installer detects the touchscreen and asks you to name it if it cannot.

## Set up the OS

1. Flash Raspberry Pi OS with Raspberry Pi Imager. In the advanced options set a hostname, your user, Wi-Fi and **enable SSH**. You will have no keyboard on the Pi most of the time.
2. Boot, then from your laptop: `ssh <user>@<hostname>.local`.
3. `sudo apt update && sudo apt full-upgrade`, then reboot.
4. Install Claude Code on the Pi (the official installer from Anthropic's documentation). `install.sh` stops with a clear error if `claude` is not on `PATH` or is a version without the flags the loop needs.

The installer's `claude-check` warns when your `claude` is newer or older than the tested version; newer usually works, older may lack flags.

## Wi-Fi is the weak point

On the author's Pi the link was 2.4 GHz only with a weak signal, and Wi-Fi power saving made it much worse (about 72 % inbound packet loss until it was turned off; about 32 % remained). Symptoms of a bad link:

- `scp -r` of a directory fails with "Connection closed".
- The `.local` name times out over IPv6.
- Slack reads take minutes instead of seconds.

What helps, in order: **plug in an Ethernet cable** (the real fix), move the Pi or use 5 GHz, and turn Wi-Fi power saving off. The installer offers that last one (`nmcli con mod <wifi> 802-11-wireless.powersave 2`). See [troubleshooting](09-troubleshooting.md) for working around a bad link.

## Things the installer touches

`~/maint`, `~/.claude-profiles`, `~/.config/labwc`, user systemd units, `/etc/claude-remote*-settings.json`, a lightdm drop-in, optionally a local `lightdm.service` copy, your crontab (between marked lines) and optionally Wi-Fi power save. Each system change asks first unless you pass `--yes`.
