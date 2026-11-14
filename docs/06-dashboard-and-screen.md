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

## The loop card

Under "Working on now", the **Loop** card shows the loop as a whole:

- **Status:** running (which part and for how long), idle or paused, whether the crontab entries are
  live or dry-run, and today's runs and failures.
- **One column per scheduled part** (gate, full, dbx): the last run (✓ or ✕, time, duration) and the next
  run, worked out from your crontab (`crontab -l`, read once a minute).
- **Pause / Resume:** pausing writes `app/paused.json`; `run.py gate|full|dbx` then skips at once
  (`[paused] ... run skipped` in `run.log`), before reading its config. A run already going finishes.
  Manual `run.py spec` and `run.py cost` are not affected. The button calls `POST /api/loop`, guarded
  like the settings menu.

## Screen: dim, off and tap to wake

`maint-screen.service` runs `~/maint/app/screen.py`. It only changes the touchscreen's backlight
(`/sys/class/backlight/*`, writable by the `video` group); the Pi and the dashboard keep running.

- **Day:** the normal brightness.
- **Evening** (from 20:00): dimmed.
- **Night** (22:00 to 07:00): off. A tap turns it on, dimmed, for 2 minutes.
- **No input for an hour:** off. Any touch, key or mouse movement turns it on again (it reads the
  keyboard, mouse and touch devices under `/dev/input`, so your user must be in the `input` group;
  the power button and HDMI events do not count).

While the screen is off, the first tap only wakes it: the page lays a transparent layer over itself,
so that tap does not press a button underneath.

## Settings menu

The ⚙ button at the top right opens the settings:

- **Brightness** and **Evening brightness**.
- **Dim from**, **Off from**, **Back on at**, and **Off after no touch** (15 min to 2 hours, or never).
- **Screen off now**.
- **Restart dashboard**, **Restart Pi** and **Shut down Pi**. Restart and shut down need a second tap
  within 4 seconds. After a shut down the Pi stays off until you press its power button (Pi 5) or
  reconnect power.

The settings are saved in `app/screen.json` (local, not committed). The buttons call `POST /api/screen`
and `POST /api/power` on the dashboard, which answers only on 127.0.0.1 and only to requests carrying the
page's `X-Afterhours` header, so another website open in the kiosk browser cannot trigger them. Restart
and shut down run `systemctl reboot`/`poweroff`, and fall back to `sudo -n` if the session may not.

Check the decision for right now without changing anything: `python3 ~/maint/app/screen.py --once`.

If you lock the desktop with a leftover Chromium window, close it over SSH: `pkill chromium`;
`kiosk.sh` starts it again.
