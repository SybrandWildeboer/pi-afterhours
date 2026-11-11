#!/usr/bin/env bash
# Render the dashboard in demo mode (synthetic data) to docs/images/dashboard-demo.png, 720 px wide.
# Prefers Playwright's chrome-headless-shell (exact 720x1280). Regular Chromium counts its own toolbar in the
# window height, so it gets a 1380 px window and the image has a blank strip at the bottom; set CHROMIUM=... to choose.
set -euo pipefail
cd "$(dirname "$0")/.."
SHELL_BIN="$(ls ~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell 2>/dev/null | tail -1 || true)"
if [ -n "${CHROMIUM:-}" ]; then CHROME="$CHROMIUM"; MODE="--headless=new"; H=1380
elif [ -n "$SHELL_BIN" ]; then CHROME="$SHELL_BIN"; MODE="--headless"; H=1280
else CHROME="$(command -v chromium chromium-browser google-chrome 2>/dev/null | head -1 || true)"; MODE="--headless=new"; H=1380
fi
[ -n "$CHROME" ] || { echo "no Chromium found: set CHROMIUM=/path/to/chrome" >&2; exit 1; }
mkdir -p docs/images
python3 app/dash.py --demo --port 8788 & SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for _ in $(seq 1 20); do curl -sf -o /dev/null http://127.0.0.1:8788/api/state && break; sleep 0.3; done
"$CHROME" $MODE --no-sandbox --disable-gpu --hide-scrollbars --window-size=720,$H \
  --virtual-time-budget=4000 --screenshot=docs/images/dashboard-demo.png http://127.0.0.1:8788/ >/dev/null 2>&1
ls -la docs/images/dashboard-demo.png
