# 03 GitHub

The loop uses the `gh` CLI to read PRs and CI, and (only when it fixes something) to push a branch and open a PR.

## Log in with the token in a file

```bash
gh auth login -p ssh -w --insecure-storage -s repo -s read:org
```

`--insecure-storage` keeps the token in `~/.config/gh/hosts.yml` instead of the desktop keyring. On a Pi that boots headless the keyring is locked after a reboot, `gh` then reports "not logged in", and every unattended run fails. The file is readable only by your user; treat the Pi like any machine holding a token.

Give the token only the scopes you need.

## A key for this device

Use a separate SSH key for the Pi, not your laptop's:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_github -N ""
gh ssh-key add ~/.ssh/id_ed25519_github.pub --title "pi"
```

If your organisation uses SAML single sign-on, open the key (and the token) in GitHub's settings and **authorise it for the organisation**; until then clones of private organisation repos fail with a confusing "repository not found".

## Branches and merging

`auto_merge` is `false` in `config.example.json` and `--go-live` refuses to run when it is on. A fix is a pull request for you to read, never a merge. Protect `main` on your repos; the fix agent may only push through `push-maint`, which pushes the current `maint/<name>` branch and nothing else, but branch protection is the backstop.
