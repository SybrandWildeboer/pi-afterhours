#!/usr/bin/env python3
"""Build the untracked .leakcheck-terms file from a real config.json.

usage: make_leak_terms.py CONFIG [--out FILE] [--extra TERM ...]
The GitHub login in `me` is the public publishing identity and is deliberately not a term.
"""
import argparse
import json
from pathlib import Path


def terms_from_config(cfg, extra=()):
    out = []

    def add(t):
        t = (t or "").strip()
        if len(t) >= 4 and t not in out:
            out.append(t)

    add(cfg.get("channel"))
    add(cfg.get("projects_root"))
    for w in cfg.get("workspaces", []):
        add(w)
    for r in cfg.get("repos", []):
        add(r.get("name"))
        add(r.get("path"))
        add(r.get("gh"))
        for part in r.get("gh", "").split("/") + r.get("path", "").split("/"):
            add(part)
    for t in extra:
        add(t)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / ".leakcheck-terms"))
    ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args(argv)
    terms = terms_from_config(json.loads(Path(a.config).read_text()), a.extra)
    Path(a.out).write_text("# private words: never commit this file\n" + "\n".join(terms) + "\n")
    print(f"wrote {len(terms)} terms to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
