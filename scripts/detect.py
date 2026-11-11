#!/usr/bin/env python3
"""Detect instead of assume: what this Pi and this Claude Code actually look like. Standard library only.

usage: detect.py claude-check | lightdm-override | touch
  claude-check      exit 1 if this Claude Code lacks something the loop needs (version differences are only warnings)
  lightdm-override  exit 0 if the display login must not wait for a GPU render node (it does not exist here)
  touch             print the name of each touchscreen, one per line
"""
import re
import subprocess
import sys
from pathlib import Path

TESTED_VERSION = (2, 1, 322)
REQUIRED_FLAGS = ("--max-budget-usd", "--allowedTools", "--settings", "--setting-sources")


def needs_lightdm_override(dri_entries):
    """lightdm waits 90 s for /dev/dri/renderD128; on a Pi without the v3d driver it never appears."""
    return "renderD128" not in dri_entries


def touch_devices(libinput_text):
    """Names of the devices whose `libinput list-devices` block lists the touch capability."""
    names = []
    for block in re.split(r"\n\s*\n", libinput_text.strip()):
        name = caps = None
        for line in block.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "Device":
                name = value.strip()
            elif key.strip() == "Capabilities":
                caps = value.split()
        if name and caps and "touch" in caps:
            names.append(name)
    return names


def missing_flags(help_text, required):
    return [f for f in required if f not in help_text]


def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in m.groups()) if m else None


def check_claude(version_text, help_text, rc_help_text):
    """Messages for the reader: 'ERROR: ...' stops the install, 'WARN: ...' does not."""
    msgs, tested = [], ".".join(map(str, TESTED_VERSION))
    v = parse_version(version_text)
    if v is None:
        msgs.append("WARN: could not read the Claude Code version (claude --version)")
    elif v != TESTED_VERSION:
        msgs.append(f"WARN: Claude Code {'.'.join(map(str, v))} is not the version this was tested with ({tested}); "
                    "if something below fails, try the tested version")
    for flag in missing_flags(help_text, REQUIRED_FLAGS):
        msgs.append(f"ERROR: this Claude Code has no {flag} option, which the loop needs. Update Claude Code (tested with {tested}).")
    if "remote-control [options]" not in rc_help_text:
        msgs.append(f"ERROR: the `claude remote-control` command is missing. Update Claude Code (tested with {tested}) "
                    "and make sure you are logged in with a subscription account.")
    return msgs


def run_cmd(*args):
    """Output of a command (stdout and stderr), or '' if it cannot be run."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "claude-check":
        msgs = check_claude(run_cmd("claude", "--version"), run_cmd("claude", "--help"),
                            run_cmd("claude", "remote-control", "--help"))
        print("\n".join(msgs) if msgs else "claude: ok")
        return 1 if any(m.startswith("ERROR") for m in msgs) else 0
    if cmd == "lightdm-override":
        dri = Path("/dev/dri")
        needed = needs_lightdm_override([p.name for p in dri.iterdir()] if dri.exists() else [])
        print("yes" if needed else "no")
        return 0 if needed else 1
    if cmd == "touch":
        print("\n".join(touch_devices(run_cmd("libinput", "list-devices"))))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
