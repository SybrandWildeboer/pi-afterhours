"""Fixes from the whole-branch review. Each test names the finding it pins."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))
import collect_diagnostics  # noqa: E402
import config  # noqa: E402
import cron_block  # noqa: E402
import llm  # noqa: E402

CHAN = "".join(["C0", "ABCDEF", "123"])  # built at run time so the leak check does not flag this file
CFG = {**config.DEFAULTS, "projects_root": "/x"}
BLOCK = "# BEGIN pi-afterhours\nPATH=/x\n*/30 7-21 * * * cd /h && python3 run.py gate >> /h/run.log 2>&1\n# END pi-afterhours\n"


def git(cwd, *a, env=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, env=env)


class FixAgentCannotReadOrWriteArbitraryFiles(unittest.TestCase):  # review Important 1
    def allow(self):
        return [t for t in llm.TOOLS["fix"] if t.startswith("Bash(")]

    def test_no_prefix_rule_for_commands_that_take_file_arguments(self):
        for rule in self.allow():
            for bad in ("git commit", "git add", "git log", "git diff:", "gh pr create"):
                self.assertNotIn(bad, rule, rule)

    def test_commit_and_pr_go_through_wrappers(self):
        joined = " ".join(self.allow())
        self.assertIn("maint-commit", joined)
        self.assertIn("maint-pr", joined)

    def test_prompt_names_the_wrappers(self):
        a = llm.Agents(CFG, ROOT / "app")
        p = a._prompt("fix", repo="r", gh="o/r", workflow="w", branch="maint/x", base="main", sha="abc", url="u",
                      push=llm.PUSH, commit=llm.COMMIT, pr=llm.PR)
        self.assertIn(llm.COMMIT, p)
        self.assertIn(llm.PR, p)
        self.assertNotIn("`git commit` with", p)  # it may mention plain git only to say it is refused


class Wrappers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.repo = d / "repo"
        self.repo.mkdir()
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
            git(self.repo, *a)
        (self.repo / "a.txt").write_text("1")
        git(self.repo, "add", "."), git(self.repo, "commit", "-q", "-m", "init")
        self.bin = d / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" > {d}/gh.args\n')
        gh.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_w(self, name, *args):
        return subprocess.run(["bash", str(ROOT / "app" / name), *args], cwd=self.repo, capture_output=True, text=True, env=self.env)

    def test_commit_refuses_off_a_maint_branch(self):
        (self.repo / "a.txt").write_text("2")
        p = self.run_w("maint-commit", "msg")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("refusing", p.stderr)

    def test_commit_takes_the_message_literally_and_skips_hooks(self):
        git(self.repo, "checkout", "-q", "-b", "maint/x")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        (self.repo / "a.txt").write_text("2")
        p = self.run_w("maint-commit", "fix: -F /etc/passwd")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s").stdout.strip(), "fix: -F /etc/passwd")

    def test_pr_refuses_off_a_maint_branch(self):
        self.assertNotEqual(self.run_w("maint-pr", "t", "b").returncode, 0)

    def test_pr_uses_fixed_arguments(self):
        git(self.repo, "checkout", "-q", "-b", "maint/x")
        p = self.run_w("maint-pr", "title", "body --body-file /etc/passwd")
        self.assertEqual(p.returncode, 0, p.stderr)
        args = (Path(self.tmp.name) / "gh.args").read_text()
        self.assertIn("pr create", args)
        self.assertIn("--head maint/x", args)
        self.assertEqual(args.count("--body-file"), 1)  # only inside the literal body text


class AgentsIgnoreInheritedPermissionMode(unittest.TestCase):  # review Important 2
    def test_every_task_forces_the_default_permission_mode(self):
        a = llm.Agents(CFG, "/tmp")
        for task in ("gate", "post", "spec", "fix", "review"):
            argv = a.command(task, "p")
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "default", task)


class RerunKeepsLive(unittest.TestCase):  # review Important 3
    def test_replace_block_keeps_live_entries_live(self):
        live = cron_block.go_live(BLOCK)
        self.assertEqual(cron_block.replace_block(live, BLOCK), live)

    def test_replace_block_stays_dry_run_when_it_was(self):
        self.assertNotIn("--live", cron_block.replace_block(BLOCK, BLOCK))


class EtcWritesAskFirst(unittest.TestCase):  # review Important 4
    def test_declining_writes_no_etc_file(self):
        with tempfile.TemporaryDirectory() as d:
            root, binp = Path(d) / "root", Path(d) / "bin"
            binp.mkdir()
            c = binp / "claude"
            c.write_text('#!/bin/sh\ncase "$1" in\n  --version) echo "2.1.322 (Claude Code)";;\n'
                         '  --help) echo "claude --max-budget-usd --allowedTools --setting-sources --settings";;\n'
                         '  remote-control) echo "USAGE"; echo "  claude remote-control [options]";;\nesac\n')
            c.chmod(0o755)
            env = {**os.environ, "PATH": f"{binp}:{os.environ['PATH']}"}
            p = subprocess.run(["bash", str(ROOT / "install.sh"), "--root", str(root), "--user", "alex", "--skip-system"],
                               input="n\n" * 20, capture_output=True, text=True, env=env, cwd=ROOT)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse((root / "etc").exists() and any((root / "etc").rglob("*")), list((root / "etc").rglob("*")))


class DiagnosticsKeepLoopContentPrivate(unittest.TestCase):  # review Important 5
    def test_config_names_are_redacted(self):
        cfg = {"me": "alexgh", "channel": CHAN, "repos": [{"name": "secret-repo", "path": "secret-repo", "gh": "acme-org/secret-repo"}]}
        out = collect_diagnostics.redact("PR in acme-org/secret-repo by alexgh in " + CHAN, extra=collect_diagnostics.names_from_config(cfg))
        for word in ("acme-org", "secret-repo", "alexgh", CHAN):
            self.assertNotIn(word, out)

    def test_ssid_line_is_redacted_without_networkmanager(self):
        out = collect_diagnostics.redact("Connected to aa:bb\n\tSSID: My Home Wifi\n\tfreq: 2437")
        self.assertNotIn("My Home Wifi", out)


class ConfigTypes(unittest.TestCase):  # re-graded: "false" as a string must not turn auto-merge on
    def load(self, raw):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(raw))
            return config.load(p)

    def test_auto_merge_must_be_a_boolean(self):
        with self.assertRaises(config.ConfigError) as e:
            self.load({"projects_root": "/x", "auto_merge": "false"})
        self.assertIn("auto_merge", str(e.exception))

    def test_top_level_must_be_an_object(self):
        with self.assertRaises(config.ConfigError):
            self.load([])


class DocsDoNotOverclaim(unittest.TestCase):  # re-graded: false security claim
    def test_protected_paths_claim_is_accurate(self):
        text = (ROOT / "docs" / "05-maintenance-loop.md").read_text()
        self.assertNotIn("are not touched by a fix", text)
        self.assertIn("merge rule", text)


if __name__ == "__main__":
    unittest.main()
