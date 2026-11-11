import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cron_block  # noqa: E402
import seed_trust  # noqa: E402

INSTALL, DOCTOR = str(ROOT / "install.sh"), str(ROOT / "scripts" / "doctor.sh")
BLOCK = "# BEGIN pi-afterhours\nPATH=/x\n*/30 7-21 * * * cd /h && python3 run.py gate >> /h/run.log 2>&1\n# END pi-afterhours\n"


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
            h.update(str(os.access(p, os.X_OK)).encode())
    return h.hexdigest()


class Helpers(unittest.TestCase):
    def test_replace_block_is_idempotent_and_keeps_other_lines(self):
        mine = "0 5 * * * backup.sh\n"
        once = cron_block.replace_block(mine, BLOCK)
        self.assertIn("backup.sh", once)
        self.assertEqual(cron_block.replace_block(once, BLOCK), once)
        newer = BLOCK.replace("/x", "/y")
        self.assertEqual(cron_block.replace_block(once, newer).count("# BEGIN pi-afterhours"), 1)
        self.assertIn("PATH=/y", cron_block.replace_block(once, newer))

    def test_go_live_touches_only_our_block_and_only_once(self):
        text = "0 5 * * * python3 run.py gate\n" + BLOCK
        live = cron_block.go_live(text)
        self.assertIn("run.py gate --live >>", live)
        self.assertIn("0 5 * * * python3 run.py gate\n", live)  # someone else's line is untouched
        self.assertEqual(cron_block.go_live(live), live)

    def test_seed_trust_is_idempotent_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".claude.json"
            f.write_text(json.dumps({"theme": "dark", "projects": {"/other": {"x": 1}}}))
            seed_trust.seed(Path(d), "/home/alex/projects")
            first = f.read_bytes()
            seed_trust.seed(Path(d), "/home/alex/projects")
            self.assertEqual(f.read_bytes(), first)
            data = json.loads(first)
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["projects"]["/other"], {"x": 1})
            self.assertTrue(data["projects"]["/home/alex/projects"]["hasTrustDialogAccepted"])


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.root = self.d / "root"
        self.bin = self.d / "bin"
        self.bin.mkdir()
        self.stub()
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, with_settings=True):
        flags = "--max-budget-usd --allowedTools --setting-sources" + (" --settings" if with_settings else "")
        script = ('#!/bin/sh\ncase "$1" in\n  --version) echo "2.1.322 (Claude Code)";;\n'
                  f'  --help) echo "Usage: claude {flags}";;\n  remote-control) echo "USAGE"; echo "  claude remote-control [options]";;\nesac\n')
        f = self.bin / "claude"
        f.write_text(script)
        f.chmod(0o755)

    def install(self, *extra, env=None):
        args = ["--root", str(self.root), "--user", "alex", "--skip-system", "--yes", *extra]
        return subprocess.run(["bash", INSTALL, *args], capture_output=True, text=True, env=env or self.env, cwd=ROOT)

    def home(self, *p):
        return self.root / "home" / "alex" / Path(*p)

    def test_dry_run_writes_nothing_and_prints_plan(self):
        p = self.install("--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.root.exists() and any(self.root.rglob("*")))
        self.assertIn("would", p.stdout)
        self.assertIn("phase", p.stdout)

    def test_run_twice_changes_nothing(self):  # Review Focus 3
        a = self.install()
        self.assertEqual(a.returncode, 0, a.stderr)
        first = tree_hash(self.root)
        b = self.install()
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(tree_hash(self.root), first)

    def test_rendered_files_use_the_given_user(self):
        self.assertEqual(self.install().returncode, 0)
        unit = (self.home(".config", "systemd", "user", "claude-remote.service")).read_text()
        self.assertIn("/home/alex/projects", unit)
        self.assertIn("autologin-user=alex", (self.root / "etc/lightdm/lightdm.conf.d/50-afterhours.conf").read_text())
        self.assertTrue((self.root / "etc/claude-remote-settings.json").exists())

    def test_never_installs_a_real_config(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertTrue(self.home("maint", "app", "config.example.json").exists())
        self.assertFalse(self.home("maint", "app", "config.json").exists())

    def test_cron_is_dry_run_by_default(self):
        self.assertEqual(self.install().returncode, 0)
        lines = [l for l in self.home(".pi-afterhours.crontab").read_text().splitlines() if "run.py" in l]
        self.assertEqual(len(lines), 3)
        self.assertFalse([l for l in lines if "--live" in l])

    def test_go_live_needs_config_and_no_auto_merge(self):
        self.assertEqual(self.install().returncode, 0)
        cron = self.home(".pi-afterhours.crontab")
        refused = self.install("--go-live")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("config.json", refused.stderr)
        self.assertNotIn("--live", cron.read_text())
        cfg = self.home("maint", "app", "config.json")
        cfg.write_text(json.dumps({"projects_root": "/x", "auto_merge": True}))
        self.assertNotEqual(self.install("--go-live").returncode, 0)  # auto_merge on: refuse
        cfg.write_text(json.dumps({"projects_root": "/x", "auto_merge": False}))
        self.assertEqual(self.install("--go-live").returncode, 0)
        self.assertEqual(cron.read_text().count("--live"), 3)

    def test_missing_flag_stops_with_message(self):  # Review Focus 4
        self.stub(with_settings=False)
        p = self.install()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--settings", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(self.root.exists() and any(self.root.rglob("*")))

    def test_claude_missing_is_explained(self):
        p = self.install(env={**os.environ, "PATH": "/usr/bin:/bin"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("claude", p.stderr.lower())
        self.assertNotIn("Traceback", p.stderr)

    def test_doctor_fails_on_an_empty_root(self):
        p = subprocess.run(["bash", DOCTOR, "--root", str(self.root), "--user", "alex"], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL", p.stdout)

    def test_doctor_sees_what_the_installer_wrote(self):
        self.assertEqual(self.install().returncode, 0)
        p = subprocess.run(["bash", DOCTOR, "--root", str(self.root), "--user", "alex"], capture_output=True, text=True, env=self.env)
        self.assertIn("OK   app installed", p.stdout)
        self.assertIn("OK   cron entries", p.stdout)
        self.assertIn("FAIL config.json", p.stdout)  # the user has not created it yet
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main()
