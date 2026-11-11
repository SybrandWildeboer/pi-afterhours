"""Checks the docs: required files and phrases, working relative links, no private terms."""
import re
import sys
from pathlib import Path

REQUIRED_DOCS = (
    "01-hardware-and-os.md", "02-profiles-and-logins.md", "03-github.md",
    "04-remote-control.md", "05-maintenance-loop.md", "06-dashboard-and-screen.md",
    "07-security-model.md", "08-costs-and-limits.md", "09-troubleshooting.md",
)
README_PHRASES = ("untested from scratch", "not affiliated with Anthropic", "dry-run", "estimate")
SOFT_WALL_DOCS = ("04-remote-control.md", "07-security-model.md")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _links(md: Path):
    for target in LINK.findall(md.read_text()):
        if not re.match(r"^(https?:|mailto:|#)", target):
            yield target.split("#")[0]


def check(root: Path) -> list[str]:
    errors = []
    readme = root / "README.md"
    docs = root / "docs"
    if not readme.is_file():
        errors.append("README.md is missing")
    else:
        text = readme.read_text().lower()
        errors += [f"README.md lacks the phrase '{p}'" for p in README_PHRASES if p.lower() not in text]
    errors += [f"docs/{n} is missing" for n in REQUIRED_DOCS if not (docs / n).is_file()]
    for n in SOFT_WALL_DOCS:
        f = docs / n
        if f.is_file() and "soft wall" not in f.read_text().lower():
            errors.append(f"docs/{n} lacks the 'soft wall' caveat")
    pages = [p for p in [readme, root / "SECURITY.md", *sorted(docs.glob("*.md"))] if p.is_file()]
    for page in pages:
        for target in _links(page):
            if target and not (page.parent / target).exists():
                errors.append(f"broken link in {page.relative_to(root)}: {target}")
    terms_file = root / ".leakcheck-terms"
    if terms_file.is_file():
        terms = [t.strip().lower() for t in terms_file.read_text().splitlines() if t.strip() and not t.startswith("#")]
        for page in pages:
            body = page.read_text().lower()
            errors += [f"private term '{t}' in {page.relative_to(root)}" for t in terms if t in body]
    return errors


if __name__ == "__main__":
    problems = check(Path(__file__).resolve().parent.parent)
    print("\n".join(problems) or "docs ok")
    sys.exit(1 if problems else 0)
