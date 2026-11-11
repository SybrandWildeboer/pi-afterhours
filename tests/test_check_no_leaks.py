import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_leaks as L  # noqa: E402
import make_leak_terms as M  # noqa: E402

J = "".join  # fake leaks are assembled at run time, so this file never contains one itself


def kinds(text, terms=()):
    return {k for k, _ in L.scan_text(text, terms)}


class ScanText(unittest.TestCase):
    def test_token_kinds(self):
        for fake in (J(["ghp_", "a" * 30]), J(["xoxb-", "1" * 12, "-abc"]), J(["dapi", "0" * 32]),
                     J(["AKIA", "A" * 16]), J(["-----BEGIN ", "RSA PRIVATE KEY-----"])):
            self.assertIn("token", kinds(fake), fake)

    def test_email(self):
        self.assertIn("email", kinds(J(["a", "@", "b.nl"])))
        self.assertEqual(kinds("1+octo@users.noreply.github.com, me@example.com, git@github.com:x/y.git"), set())

    def test_systemd_unit_names_are_not_emails(self):
        self.assertEqual(kinds("After=getty@tty1.service and user@1000.service and sshd@.socket"), set())

    def test_ip(self):
        self.assertIn("ip", kinds(J(["192.168.", "178.143"])))
        self.assertEqual(kinds("127.0.0.1 0.0.0.0 192.0.2.7 198.51.100.4 203.0.113.9"), set())

    def test_ids(self):
        for fake in (J(["C0", "ABCDEF123"]), J(["dbc-", "1234abcd", "-5678"]), J(["env_01", "A" * 20])):
            self.assertIn("id", kinds(fake), fake)

    def test_terms_case_insensitive(self):
        hit = J(["PRO", "Sus"])
        self.assertEqual(L.scan_text("About " + hit + " today", [J(["pro", "sus"])]), [("term", hit)])

    def test_clean_text_passes(self):
        self.assertEqual(L.scan_text("Plain docs about a Raspberry Pi, version 2.1.322, port 8787.", ["secret-term"]), [])


class ScanPaths(unittest.TestCase):
    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            root, buf = Path(d), io.StringIO()
            (root / "a.md").write_text("all clean here\n")
            with redirect_stdout(buf):
                self.assertEqual(L.main([d]), 0)
            (root / "b.md").write_text("line1\nmail " + J(["x", "@", "y.nl"]) + "\n")
            with redirect_stdout(buf):
                self.assertEqual(L.main([d]), 1)
            self.assertIn("b.md:2 email", buf.getvalue())

    def test_terms_file_is_used_and_not_itself_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".leakcheck-terms").write_text("# private words\nzzsecretzz\n")
            (root / "a.md").write_text("this mentions ZZSecretZZ once\n")
            findings = L.scan_paths(root, L.load_terms(root))
            self.assertEqual([(f.path, f.line, f.kind) for f in findings], [("a.md", 1, "term")])

    def test_skips_git_dir_and_binary_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("mail " + J(["x", "@", "y.nl"]) + "\n")
            (root / "pic.png").write_bytes(b"\x00\x01" + J(["x", "@", "y.nl"]).encode())
            self.assertEqual(L.scan_paths(root, []), [])


class Terms(unittest.TestCase):
    def test_terms_from_config(self):
        cfg = {"channel": "chan-test-1", "me": "octo-user", "projects_root": "/home/zed/projects",
               "repos": [{"name": "acme-widgets", "path": "acme/acme-widgets", "gh": "AcmeCorp/acme-widgets"}],
               "workspaces": ["acme-dev"]}
        terms = M.terms_from_config(cfg, ["extra-word"])
        for want in ("acme-widgets", "AcmeCorp/acme-widgets", "AcmeCorp", "chan-test-1", "acme-dev",
                     "/home/zed/projects", "extra-word"):
            self.assertIn(want, terms)
        self.assertNotIn("octo-user", terms)  # the public GitHub login is the publishing identity, not a secret


if __name__ == "__main__":
    unittest.main()
