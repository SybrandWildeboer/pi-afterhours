#!/usr/bin/env python3
"""Fill @NAME@ placeholders in template files. Standard library only.

usage: render.py SRC_DIR DST_DIR USER=alex HOME=/home/alex HOSTNAME=pi PROJECTS=/home/alex/projects TOUCH_DEVICE=... TOUCH_OUTPUT=DSI-1
"""
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"@([A-Z][A-Z_]*)@")  # unit names like getty@tty1.service are lower-case: left alone


class RenderError(Exception):
    pass


def render(text, mapping):
    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in mapping})
    if missing:
        raise RenderError("no value for placeholder(s): " + ", ".join(f"@{m}@" for m in missing))
    return PLACEHOLDER.sub(lambda m: mapping[m.group(1)], text)


def render_tree(src, dst, mapping):
    """Render every file under src into dst, keeping the folder layout. Returns the written paths."""
    written = []
    for f in sorted(Path(src).rglob("*")):
        if f.is_file():
            out = Path(dst) / f.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render(f.read_text(), mapping))
            written.append(out)
    return written


if __name__ == "__main__":
    src, dst, *pairs = sys.argv[1:]
    try:
        files = render_tree(src, dst, dict(p.split("=", 1) for p in pairs))
    except RenderError as e:
        sys.exit(f"render error: {e}")
    print(f"rendered {len(files)} files into {dst}")
