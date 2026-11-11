#!/usr/bin/env python3
"""Record 'workspace trusted' for a folder in a Claude profile, so headless services never hit the trust prompt.

usage: seed_trust.py PROFILE_DIR PROJECT_PATH
Keeps every other key in the profile's .claude.json. Safe to repeat: an unchanged file is not rewritten.
"""
import json
import sys
from pathlib import Path


def seed(profile_dir, project):
    f = Path(profile_dir) / ".claude.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    data.setdefault("projects", {}).setdefault(project, {})["hasTrustDialogAccepted"] = True
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if f.exists() and f.read_text() == text:
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.chmod(0o600)
    tmp.replace(f)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    seed(Path(sys.argv[1]), sys.argv[2])
