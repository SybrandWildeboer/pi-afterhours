"""State between runs: one small JSON file. Survives a power cut: fsync, atomic replace, one backup."""
import json
import os
import shutil
from pathlib import Path

DEFAULT = {"last_ts": None, "posted": {}, "fix_attempts": {}, "prs_today": {},
           "reviewed": {}, "specs": {}, "last_scan_sha": {}, "last_sweep": None}


def load(path):
    path = Path(path)
    s = {}
    for p in (path, Path(str(path) + ".bak")):  # a torn write falls back to the last good copy
        try:
            s = json.loads(p.read_text())
            break
        except (OSError, ValueError):
            continue
    for k, v in DEFAULT.items():
        s.setdefault(k, type(v)() if v is not None else None)
    return s


def save(path, s):
    path = Path(path)
    tmp = Path(str(path) + ".tmp")
    with tmp.open("w") as f:
        json.dump(s, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        shutil.copy2(path, str(path) + ".bak")
    os.replace(tmp, path)
