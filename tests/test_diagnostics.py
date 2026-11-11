import getpass
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect_diagnostics as D  # noqa: E402

J = "".join  # fake identifiers are assembled at run time so this file never contains one
USER, HOST = getpass.getuser(), socket.gethostname()
SAMPLES = {
    "<email>": J(["a", "@", "b.nl"]),
    "<ip>": J(["192.168.", "1.20"]),
    "<mac>": J(["44:15:24:", "da:3c:e8"]),
    "<token>": J(["ghp_", "a" * 30]),
}
IPV6 = J(["2001:1c03:5a07:", "8900:4f8f:805:70f3:c761"])


class Redact(unittest.TestCase):
    def test_redacts_each_kind(self):  # Review Focus 5
        for placeholder, value in SAMPLES.items():
            out = D.redact(f"x {value} y")
            self.assertNotIn(value, out)
            self.assertIn(placeholder, out)
        out = D.redact(f"addr {IPV6} up")
        self.assertNotIn(IPV6, out)
        self.assertIn("<ip>", out)

    def test_username_hostname_ssid_and_extras(self):
        out = D.redact(f"/home/{USER}/maint on {HOST} net Cafe-Net secret-thing", extra=["secret-thing"], ssids=["Cafe-Net"])
        for private in (USER, HOST, "Cafe-Net", "secret-thing"):
            self.assertNotIn(private, out)
        for placeholder in ("<user>", "<host>", "<ssid>", "<redacted>"):
            self.assertIn(placeholder, out)

    def test_useful_text_survives(self):
        text = "load 12:34:56 version 2.1.322 listening 127.0.0.1:8787 After=getty@tty1.service Raspberry Pi"
        self.assertEqual(D.redact(text, user="nobody-here", host="nowhere-box"), text)

    def test_kernel_versions_are_not_ip_addresses(self):
        text = J(["Linux 6.18.58.", "1-microsoft-standard-WSL2"]) + " and 1.2.3.4.5"  # four-number kernel version, five-number version
        self.assertEqual(D.redact(text, user="nobody-here", host="nowhere-box"), text)

    def test_idempotent_even_for_a_username_like_user(self):
        text = f"hello user at {SAMPLES['<email>']} {SAMPLES['<ip>']} {IPV6}"
        once = D.redact(text, user="user")
        self.assertEqual(D.redact(once, user="user"), once)
        self.assertNotIn("<<", once)

    def test_whole_words_only(self):  # a username like "pi" must not mangle "pip" or "api"
        self.assertEqual(D.redact("pipx and api use pi here", user="pi", host="nowhere-box"), "pipx and api use <user> here")


class Collect(unittest.TestCase):
    def test_collect_output_has_no_identifiers(self):
        planted = f"user {USER} host {HOST} ip {SAMPLES['<ip>']} mail {SAMPLES['<email>']} mac {SAMPLES['<mac>']} ssid Cafe-Net tok {SAMPLES['<token>']}"

        def fake_run(*args):
            return "yes:Cafe-Net" if args and args[0] == "nmcli" else planted

        out = D.collect(run=fake_run)
        for private in (USER, HOST, "Cafe-Net", *SAMPLES.values()):
            self.assertNotIn(private, out)
        self.assertIn("doctor", out.lower())


if __name__ == "__main__":
    unittest.main()
