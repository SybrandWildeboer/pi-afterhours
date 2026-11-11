#!/usr/bin/env python3
"""Fail if anything personal or secret-looking would be committed. Standard library only.

usage: check_no_leaks.py [ROOT]
ROOT defaults to the repo root. Private words come from ROOT/.leakcheck-terms (untracked, one per line).
In a git repo it scans what git would commit (tracked + untracked, minus ignored); otherwise every file.
"""
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprse][.-][A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}"
    r"|dapi[0-9a-f]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IDS = re.compile(r"\bC0[A-Z0-9]{8,}\b|\bdbc-[0-9a-f]{8}-[0-9a-f]{4}|\benv_01[A-Za-z0-9]{20,}\b")
OK_EMAIL_DOMAINS = {"users.noreply.github.com", "example.com", "example.org", "example.net"}
UNIT_SUFFIXES = (".service", ".socket", ".target", ".mount", ".timer", ".slice")  # getty@tty1.service is not an email
OK_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}
OK_IP_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")  # documentation ranges
SKIP_DIRS = {".git", ".superpowers", "__pycache__", "node_modules"}


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    match: str


def scan_text(text, terms):
    """Return (kind, match) for everything in `text` that looks private or secret."""
    out = [("token", m.group(0)) for m in TOKEN.finditer(text)]
    for m in EMAIL.finditer(text):
        domain = m.group(1).lower()
        if domain not in OK_EMAIL_DOMAINS and not domain.endswith(UNIT_SUFFIXES) and m.group(0) != "git@github.com":
            out.append(("email", m.group(0)))
    for m in IPV4.finditer(text):
        ip = m.group(0)
        if all(int(p) <= 255 for p in ip.split(".")) and ip not in OK_IPS and not ip.startswith(OK_IP_PREFIXES):
            out.append(("ip", ip))
    out += [("id", m.group(0)) for m in IDS.finditer(text)]
    low = text.lower()
    for term in terms:
        t, i = term.lower(), 0
        while t and (i := low.find(t, i)) != -1:
            out.append(("term", text[i:i + len(t)]))
            i += len(t)
    return out


def load_terms(root):
    f = Path(root) / ".leakcheck-terms"
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")]


def candidate_files(root):
    root = Path(root)
    if (root / ".git").exists():
        p = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                           capture_output=True)
        if p.returncode == 0:
            return [root / n for n in p.stdout.decode().split("\0") if n]
    return [f for f in sorted(root.rglob("*")) if f.is_file() and not SKIP_DIRS & set(f.relative_to(root).parts)]


def scan_paths(root, terms):
    root, found = Path(root), []
    for f in candidate_files(root):
        if f.name == ".leakcheck-terms" or not f.is_file():
            continue
        data = f.read_bytes()
        if b"\x00" in data[:2048]:  # binary (images etc.)
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for kind, match in scan_text(line, terms):
                found.append(Finding(str(f.relative_to(root)), n, kind, match))
    return found


def main(argv):
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    findings = scan_paths(root, load_terms(root))
    for f in findings:
        print(f"{f.path}:{f.line} {f.kind} {f.match}")
    print(f"leak check: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
