import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import detect  # noqa: E402

LIBINPUT = """Device:           Example USB Keyboard
Kernel:           /dev/input/event2
Capabilities:     keyboard

Device:           10-005d Example Touch Panel
Kernel:           /dev/input/event6
Capabilities:     touch

Device:           Example Touchpad
Kernel:           /dev/input/event7
Capabilities:     pointer gesture
"""
FLAGS = "\n".join(f"  {f} <value>" for f in detect.REQUIRED_FLAGS)
HELP = "Usage: claude [options]\n" + FLAGS + "\n"
RC_HELP = "Remote Control - control local sessions\n\nUSAGE\n  claude remote-control [options]\n"


class Detect(unittest.TestCase):
    def test_override_needed_without_render_node(self):
        self.assertTrue(detect.needs_lightdm_override(["card0", "by-path"]))

    def test_override_not_needed_with_render_node(self):
        self.assertFalse(detect.needs_lightdm_override(["card0", "renderD128"]))

    def test_touch_devices_found(self):
        self.assertEqual(detect.touch_devices(LIBINPUT), ["10-005d Example Touch Panel"])

    def test_no_touch_device(self):
        self.assertEqual(detect.touch_devices("Device: K\nCapabilities: keyboard\n"), [])

    def test_missing_flags_named(self):
        text = HELP.replace("--max-budget-usd", "--something-else")
        self.assertEqual(detect.missing_flags(text, detect.REQUIRED_FLAGS), ["--max-budget-usd"])

    def test_version_parse(self):
        self.assertEqual(detect.parse_version("2.1.322 (Claude Code)"), (2, 1, 322))
        self.assertIsNone(detect.parse_version("garbage"))

    def test_tested_version_with_everything_is_clean(self):
        self.assertEqual(detect.check_claude("2.1.322 (Claude Code)", HELP, RC_HELP), [])

    def test_other_version_is_a_warning_not_an_error(self):
        msgs = detect.check_claude("2.9.0 (Claude Code)", HELP, RC_HELP)
        self.assertTrue(msgs and all(m.startswith("WARN") for m in msgs))

    def test_missing_flag_is_an_error_naming_it(self):  # Review Focus 4
        msgs = detect.check_claude("2.1.322 (Claude Code)", HELP.replace("--settings <value>", ""), RC_HELP)
        errors = [m for m in msgs if m.startswith("ERROR")]
        self.assertTrue(any("--settings" in m for m in errors), msgs)

    def test_missing_remote_control_command_is_an_error(self):  # Review Focus 4
        msgs = detect.check_claude("2.1.322 (Claude Code)", HELP, "error: unknown command 'remote-control'")
        self.assertTrue(any(m.startswith("ERROR") and "remote-control" in m for m in msgs), msgs)

    def test_main_claude_check_exit_codes(self):
        outputs = {("claude", "--version"): "2.1.322 (Claude Code)", ("claude", "--help"): HELP,
                   ("claude", "remote-control", "--help"): RC_HELP}
        real = detect.run_cmd
        try:
            detect.run_cmd = lambda *args: outputs.get(args, "")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(detect.main(["claude-check"]), 0)
            outputs[("claude", "--help")] = "Usage: claude"
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(detect.main(["claude-check"]), 1)
            self.assertIn("--max-budget-usd", buf.getvalue())
        finally:
            detect.run_cmd = real


if __name__ == "__main__":
    unittest.main()
