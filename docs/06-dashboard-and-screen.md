# 06 Dashboard and screen

## The dashboard

`maint-dash.service` runs `~/maint/app/dash.py`, a small Python standard-library web server on **127.0.0.1:8787** (this machine only, never exposed). It shows live runs for both profiles, tokens and estimated cost per run, a chip for the two Remote Control services, and a table of one-line events ("what is it working on"). It reads `ledger.csv`, `events.jsonl` and the profiles' session files; it does not need Slack.

Try it anywhere, with synthetic data:

```bash
python3 app/dash.py --demo --port 8787
```

If a profile has no cost data the page shows "n/a" instead of a dollar figure.

## The kiosk

On the Pi, lightdm logs in automatically, starts the `labwc` Wayland compositor, which runs `~/maint/app/kiosk.sh`: Chromium in `--kiosk` mode pointed at the dashboard, restarted if it ever exits. The installer asks before it makes the Pi boot to the graphical session.

## Touch mapping

`~/.config/labwc/rc.xml` maps the touchscreen to the screen so a touch lands where you tap:

```xml
<touch deviceName="<your touch device>" mapToOutput="DSI-1" mouseEmulation="yes"/>
```

The installer finds the device with `libinput list-devices` (`scripts/detect.py touch`). If it finds none, or the wrong one, pass `--touch-device "<name>"` and `--touch-output "<output>"` (list outputs with `wlr-randr`, if installed) and run it again. Touch is not needed to view the dashboard, only to scroll it.

## The lightdm 90 second wait

On a Pi 5 without the GPU render node `/dev/dri/renderD128` (the author's has none), the stock `lightdm.service` waits 90 seconds at every boot for that device. A systemd drop-in cannot remove a dependency, so the installer, **only when it detects this case and you agree**, writes a full copy of the unit to `/etc/systemd/system/lightdm.service` with that one dependency removed (derived with `sed` from your own system's unit). Autologin itself goes in `/etc/lightdm/lightdm.conf.d/50-afterhours.conf`.

If a later OS upgrade changes the stock unit, delete the copy to go back to the packaged one: `sudo rm /etc/systemd/system/lightdm.service && sudo systemctl daemon-reload`.

## Screen blanking

The screen does not blank in the kiosk. If you lock the desktop with a leftover Chromium window, close it over SSH: `pkill chromium`; `kiosk.sh` starts it again.
