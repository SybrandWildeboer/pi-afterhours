"""Slack text. Built in code so the LLM never has to be asked to 'format'."""
from rules import redact


def fmt_spec(s):
    lines = [f"🧭 *Spec: {s.get('title', 'Untitled')}*", s.get("summary", ""), ""]
    if s.get("plan"):
        lines += ["*Plan*"] + [f"{i}. {x}" for i, x in enumerate(s["plan"][:5], 1)]
    for key, label, cap in (("assumptions", "Assuming", 2), ("open_questions", "Open questions", 3), ("risks", "Risk", 1)):
        if s.get(key):
            lines += ["", f"*{label}*"] + [f"• {x}" for x in s[key][:cap]]
    lines += ["", f"Effort: {s.get('effort', '?')} · reply in this thread to change it. "
                  "(Building it is not automated yet.)"]
    return redact("\n".join(lines))[:3500]


def _tok(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(int(n))


def fmt_cost(stats, label):
    """One Slack line: calls, tokens, estimated dollars, and where the dollars went. '' if nothing ran."""
    if not stats:
        return ""
    t = {k: sum(s[k] for s in stats.values()) for k in ("calls", "usd", "input", "output", "cache_write", "cache_read")}
    per = ", ".join(f"{k} ${v['usd']:.3f}" for k, v in sorted(stats.items(), key=lambda kv: -kv[1]["usd"]))
    return (f"💰 {label}: {int(t['calls'])} call{'s' if t['calls'] != 1 else ''} · "
            f"{_tok(t['input'] + t['cache_write'])} in + {_tok(t['cache_read'])} cached · {_tok(t['output'])} out · "
            f"${t['usd']:.3f} est. ({per})")


HELP = ("🧭 I handle two kinds of requests: describe new work and I will reply with a short spec, "
        "or say `scan <repo|databricks|all>` to check something now.")
