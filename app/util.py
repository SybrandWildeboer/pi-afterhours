"""Tiny helpers: subprocesses never use a shell, always have a timeout, and die with all their children."""
import json
import os
import signal
import subprocess


def sh(cmd, timeout=120, cwd=None, env=None, ok=(0,)):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=env,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)  # the whole group, so MCP/bash children do not linger
        p.communicate()
        raise
    if p.returncode not in ok:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {(err or out).strip()[:300]}")
    return out


def jsh(cmd, **kw):
    return json.loads(sh(cmd, **kw) or "null")


def extract_json(text):
    """First {...} block in an LLM answer, or None."""
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except ValueError:
        return None


def fill(template, **kw):
    for k, v in kw.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template
