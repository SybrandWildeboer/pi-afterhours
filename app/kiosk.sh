#!/bin/sh
# Full-screen dashboard on the Pi's touchscreen. Started by labwc at login; restarts Chromium if it ever exits.
URL=http://127.0.0.1:8787/
until curl -sf -o /dev/null "$URL"; do sleep 2; done
while true; do
  chromium --kiosk --ozone-platform=wayland --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
    --no-first-run --check-for-update-interval=31536000 --disable-pinch --overscroll-history-navigation=0 \
    --password-store=basic --user-data-dir="$HOME/.cache/kiosk-chromium" "$URL"
  sleep 3
done
