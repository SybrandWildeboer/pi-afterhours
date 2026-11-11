# Profiles and delegation

You are running as profile `personal` (personal account). Another profile, `work` (work account), is available on this machine.

To hand off a self-contained task, run from the target project directory:
`cc work --bg "<full prompt>"`
It prints a session id. List sessions with `cc-agents`, read output with `cc work logs <id>`, stop with `cc work stop <id>`.

Rules:
- Delegate only when I ask, or when a task is clearly independent. The delegate does not see this conversation, so put all needed context in the prompt.
- Never copy code, files or data between the personal and work profiles unless I explicitly say so.
