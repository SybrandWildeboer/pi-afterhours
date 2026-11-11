"""Append-only event log (one JSON object per line) that the dashboard tails. Logging must never break a run."""
import json
import os
import time
import uuid
from pathlib import Path

PATH = Path(os.environ.get("MAINT_EVENTS", Path.home() / "maint" / "events.jsonl"))
MAX_BYTES = 400_000
KEEP_LINES = 1500


def _write(rec):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **rec}) + "\n")
        if PATH.stat().st_size > MAX_BYTES:  # keep the file small: newest lines only
            lines = PATH.read_text().splitlines()[-KEEP_LINES:]
            tmp = PATH.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n")
            os.replace(tmp, PATH)
    except Exception:
        pass


def emit(kind, text, ok=True, source="loop"):
    """A finished, one-line fact: shows up in the dashboard table."""
    _write({"kind": kind, "text": str(text)[:200], "ok": ok, "source": source, "phase": "done"})


def begin(kind, text, source="loop"):
    """Work that has started: shows in the 'now' panel until end() is called with the returned id."""
    eid = uuid.uuid4().hex[:8]
    _write({"kind": kind, "text": str(text)[:200], "source": source, "phase": "start", "id": eid})
    return eid


def end(eid, text, ok=True, source="loop"):
    _write({"kind": "end", "text": str(text)[:200], "ok": ok, "source": source, "phase": "end", "id": eid})
