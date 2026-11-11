import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import llm  # noqa: E402


def agents(**plugins):
    cfg = {**config.DEFAULTS, "projects_root": "/x", "plugins": {**config.DEFAULTS["plugins"], **plugins}}
    return llm.Agents(cfg, "/tmp")


def enabled(argv):
    return json.loads(argv[argv.index("--settings") + 1])["enabledPlugins"]


class Plugins(unittest.TestCase):
    def test_unlisted_plugins_stay_out(self):
        a = agents(off=["a@m", "b@m"], spec=["a@m"])
        self.assertEqual(enabled(a.command("spec", "p", plugins=a.plugins_for("spec"))), {"a@m": True, "b@m": False})

    def test_no_plugins_configured(self):
        argv = agents().command("gate", "p")
        self.assertEqual(enabled(argv), {})
        self.assertIn("--disable-slash-commands", argv)

    def test_slack_tasks_keep_connectors_others_do_not(self):
        a = agents()
        for task in ("gate", "post"):
            self.assertNotIn("--strict-mcp-config", a.command(task, "p"))
        self.assertIn("--strict-mcp-config", a.command("spec", "p"))

    def test_each_agent_reads_its_own_list(self):
        a = agents(spec=["s@m"], fix=["f@m"])
        self.assertEqual((a.plugins_for("spec"), a.plugins_for("fix"), a.plugins_for("gate")), (["s@m"], ["f@m"], []))


if __name__ == "__main__":
    unittest.main()
