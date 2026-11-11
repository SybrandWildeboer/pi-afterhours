import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import render  # noqa: E402

J = "".join  # the owner's real names are assembled at run time so this file never contains them
OWNER_USER, OWNER_HOST = J(["syb", "rand"]), J(["syb", "pi"])
MAP = {"USER": "alex", "HOME": "/home/alex", "HOSTNAME": "pi-alex", "PROJECTS": "/home/alex/projects",
       "TOUCH_DEVICE": "Some Touch Panel", "TOUCH_OUTPUT": "DSI-1"}


class Render(unittest.TestCase):
    def test_replaces_placeholders(self):
        self.assertEqual(render.render("a @USER@ b @HOME@", MAP), "a alex b /home/alex")

    def test_unknown_placeholder_raises_and_names_it(self):
        with self.assertRaises(render.RenderError) as cm:
            render.render("x @NOPE@ y", MAP)
        self.assertIn("NOPE", str(cm.exception))

    def test_unit_names_with_at_signs_are_left_alone(self):
        self.assertEqual(render.render("After=getty@tty1.service", MAP), "After=getty@tty1.service")


class Templates(unittest.TestCase):
    def render_all(self, d):
        return render.render_tree(ROOT / "templates", Path(d) / "out", MAP)

    def test_render_for_other_user_leaves_no_owner_path(self):  # the friend's name and home differ from the owner's
        with tempfile.TemporaryDirectory() as d:
            written = self.render_all(d)
            self.assertTrue(written)
            for f in written:
                low = f.read_text().lower()
                self.assertNotIn(OWNER_USER, low, f.name)
                self.assertNotIn(OWNER_HOST, low, f.name)
            auto = next(f for f in written if f.name == "autostart").read_text()
            self.assertIn("/home/alex/maint/app/kiosk.sh", auto)

    def test_templates_have_no_literal_homes(self):
        for f in (ROOT / "templates").rglob("*"):
            if f.is_file():
                self.assertNotIn("/home/", f.read_text().replace("@HOME@", ""), f.name)

    def test_touch_device_is_a_placeholder(self):
        rc = (ROOT / "templates" / "labwc" / "rc.xml").read_text()
        self.assertIn("@TOUCH_DEVICE@", rc)
        self.assertNotIn("Goodix", rc)

    def test_every_placeholder_in_templates_is_known(self):
        used = set()
        for f in (ROOT / "templates").rglob("*"):
            if f.is_file():
                used |= set(re.findall(r"@([A-Z][A-Z_]*)@", f.read_text()))
        self.assertLessEqual(used, set(MAP))

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    def test_units_have_valid_syntax(self):
        with tempfile.TemporaryDirectory() as d:
            for f in self.render_all(d):
                if f.suffix == ".service":
                    p = subprocess.run(["systemd-analyze", "verify", str(f)], capture_output=True, text=True)
                    bad = [l for l in p.stderr.splitlines() if re.search(r"Unknown (section|key)|Failed to parse|Invalid", l)]
                    self.assertEqual(bad, [], f.name)  # missing binaries on this machine are fine; syntax errors are not


if __name__ == "__main__":
    unittest.main()
