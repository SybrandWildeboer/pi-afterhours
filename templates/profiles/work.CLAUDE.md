# Profiles and delegation

You are running as profile `work` (work account). Another profile, `personal` (personal account), is available on this machine.

To hand off a self-contained task, run from the target project directory:
`cc personal --bg "<full prompt>"`
It prints a session id. List sessions with `cc-agents`, read output with `cc personal logs <id>`, stop with `cc personal stop <id>`.

Rules:
- Delegate only when I ask, or when a task is clearly independent. The delegate does not see this conversation, so put all needed context in the prompt.
- Never copy code, files or data between the work and personal profiles unless I explicitly say so.
