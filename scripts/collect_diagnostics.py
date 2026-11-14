#!/usr/bin/env python3
"""Gather a support report (versions, doctor output, service states, loop log tail) with identifiers removed.

usage: collect_diagnostics.py > report.txt
READ report.txt before you send it to anyone: it removes the names, addresses, emails and tokens it knows about
(your username, hostname, Wi-Fi name, IPs, MACs, emails, tokens), but you are the final check.
"""
import getpass
import json
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_no_leaks import EMAIL, TOKEN, UNIT_SUFFIXES  # noqa: E402  same patterns as the leak check
from detect import run_cmd  # noqa: E402

HEX = r"[0-9a-fA-F]{1,4}"
MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
IPV6 = re.compile(rf"(?<![\w:])(?:{HEX}:){{4,7}}{HEX}(?![\w:])"                                   # five or more groups
                  rf"|(?<![\w:])(?:{HEX}(?::{HEX}){{0,6}})?::(?:{HEX}(?::{HEX}){{0,6}})?(?![\w:])")  # or compressed with ::
IPV4 = re.compile(r"(?<![\w.-])(?:\d{1,3}\.){3}\d{1,3}(?![\w-]|\.\d)")  # not a four-number kernel version followed by -name, nor a five-number version
KEEP_IPS = {"127.0.0.1", "0.0.0.0"}  # useful and harmless
SERVICES = ("maint-dash", "maint-screen", "claude-remote", "claude-remote-work")


SSID_LINE = re.compile(r"(?m)^(\s*SSID:\s*).+$")


def names_from_config(cfg):
    """Words from the loop's config.json that would identify the owner's repos, org, channel or GitHub login."""
    out = [cfg.get("me"), cfg.get("channel"), cfg.get("projects_root"), *cfg.get("workspaces", [])]
    for r in cfg.get("repos", []):
        out += [r.get("name"), r.get("path"), r.get("gh"), *r.get("gh", "").split("/"), *r.get("path", "").split("/")]
    return sorted({t.strip() for t in out if t and len(t.strip()) >= 3}, key=len, reverse=True)


def _word(text, word, placeholder):
    """Replace a whole word, but never inside an earlier placeholder like <user>, so redacting twice changes nothing."""
    if len(word) < 2:
        return text
    return re.sub(rf"(?<![<\w]){re.escape(word)}(?![\w>])", placeholder, text)


def redact(text, extra=(), ssids=(), user=None, host=None):
    user = getpass.getuser() if user is None else user
    host = socket.gethostname() if host is None else host
    text = SSID_LINE.sub(r"\1<ssid>", text)
    text = TOKEN.sub("<token>", text)
    text = EMAIL.sub(lambda m: m.group(0) if m.group(1).lower().endswith(UNIT_SUFFIXES) else "<email>", text)
    text = MAC.sub("<mac>", text)
    text = IPV6.sub("<ip>", text)
    text = IPV4.sub(lambda m: m.group(0) if m.group(0) in KEEP_IPS else "<ip>", text)
    for s in ssids:
        text = _word(text, s, "<ssid>")
    for e in extra:
        text = _word(text, e, "<redacted>")
    return _word(_word(text, user, "<user>"), host, "<host>")


def collect(run=run_cmd):
    ssids = [l.split(":", 1)[1].replace("\\:", ":") for l in
             run("nmcli", "-t", "-f", "active,ssid", "dev", "wifi").splitlines() if l.startswith("yes:")]
    here = Path(__file__).resolve().parent
    sections = [
        ("system", [run("uname", "-a"), run("cat", "/proc/device-tree/model"), run("df", "-h", "/"), run("free", "-m")]),
        ("versions", [run(c, "--version").splitlines()[0] if run(c, "--version") else f"{c}: not found"
                      for c in ("claude", "python3", "gh", "node", "databricks")]),
        ("doctor", [run("bash", str(here / "doctor.sh"))]),
        ("services", [f"{u}: {run('systemctl', '--user', 'is-active', u).strip() or 'unknown'}" for u in SERVICES]),
        ("wifi", [run("iw", "dev", "wlan0", "link")]),
        ("loop log (last 20 lines)", [run("tail", "-n", "20", str(Path.home() / "maint" / "run.log"))]),
    ]
    out = [f"pi-afterhours diagnostics, generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
    for title, parts in sections:
        out += ["", f"== {title} ==", *[p.rstrip() for p in parts if p.strip()]]
    try:
        names = names_from_config(json.loads((Path.home() / "maint" / "app" / "config.json").read_text()))
    except (OSError, ValueError, AttributeError):
        names = []
    return redact("\n".join(out) + "\n", extra=names, ssids=ssids)


if __name__ == "__main__":
    sys.stdout.write(collect())
    print("\nReview this before you share it: it removes names, IPs, emails and tokens it knows about, but you are the final check.")
