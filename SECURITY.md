# Security

This project runs AI agents unattended with credentials. Read [the security model](docs/07-security-model.md) first.

## Reporting a problem

Please report security problems **privately**, not in a public issue: use GitHub's "Report a vulnerability" button on the repository's Security tab (private vulnerability reporting). Include what you saw, what you expected, and the output of `python3 scripts/collect_diagnostics.py` (it redacts emails, IPs, MACs, tokens, your username and hostname, but read it before you send it).

This is a hobby project published as is. **No support, response time or fix is promised.** Reports are read when the author has time.

## Never put in an issue, PR or screenshot

Tokens, `config.json`, `state.json`, anything from `~/.claude-profiles`, `~/.config/gh`, `~/.databricks` or `~/.ssh`. If you leaked one, rotate it first, then report.
