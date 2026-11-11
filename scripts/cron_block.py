#!/usr/bin/env python3
"""Replace pi-afterhours' own block in a crontab, or switch that block to --live. Standard library only.

usage: cron_block.py replace BLOCK_FILE < current > new      cron_block.py live < current > new
Only the lines between the BEGIN and END markers are ever touched; the rest of the crontab is left alone.
"""
import re
import sys

BEGIN, END = "# BEGIN pi-afterhours", "# END pi-afterhours"


def _without_block(text):
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            skipping = True
        elif line.strip() == END:
            skipping = False
        elif not skipping:
            out.append(line)
    return out


def replace_block(current, block):
    """The crontab with exactly one fresh copy of `block` at the end (so its PATH= line cannot affect other entries)."""
    was_live = BEGIN in current and "--live" in current[current.index(BEGIN):]  # a re-run must not undo --go-live
    rest = _without_block(current)
    while rest and not rest[-1].strip():
        rest.pop()
    out = "\n".join(rest + ([""] if rest else []) + block.rstrip("\n").splitlines()) + "\n"
    return go_live(out) if was_live else out


def go_live(text):
    """Add --live to the loop's cron entries inside the block. Safe to repeat."""
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            inside = True
        elif line.strip() == END:
            inside = False
        elif inside and not line.lstrip().startswith("#") and "run.py" in line and "--live" not in line:
            line = re.sub(r"(run\.py (?:gate|full|dbx))", r"\1 --live", line)
        out.append(line)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "replace" and len(sys.argv) == 3:
        sys.stdout.write(replace_block(sys.stdin.read(), open(sys.argv[2]).read()))
    elif mode == "live":
        sys.stdout.write(go_live(sys.stdin.read()))
    else:
        sys.exit(__doc__)
