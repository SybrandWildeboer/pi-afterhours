import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402


def write(d, obj):
    p = Path(d) / "config.json"
    p.write_text(json.dumps(obj))
    return p


class Load(unittest.TestCase):
    def test_minimal_config_gets_defaults(self):  # the friend's smallest possible file
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load(write(d, {"projects_root": "/x"}))
        self.assertEqual((cfg["workspaces"], cfg["repos"], cfg["channel"], cfg["me"]), ([], [], "", ""))
        self.assertIs(cfg["auto_merge"], False)
        self.assertEqual(cfg["models"]["spec"], "sonnet")
        self.assertEqual(cfg["budget_usd"]["fix"], 1.5)
        self.assertEqual(cfg["plugins"], {"off": [], "spec": [], "fix": []})

    def test_nested_values_merge_with_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config.load(write(d, {"projects_root": "/x", "models": {"fix": "opus"}}))
        self.assertEqual((cfg["models"]["fix"], cfg["models"]["gate"]), ("opus", "haiku"))

    def test_missing_projects_root_names_the_key(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(config.ConfigError) as cm:
            config.load(write(d, {}))
        self.assertIn("projects_root", str(cm.exception))

    def test_repo_entry_missing_key_names_it(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(config.ConfigError) as cm:
            config.load(write(d, {"projects_root": "/x", "repos": [{"name": "a", "path": "a"}]}))
        self.assertIn("gh", str(cm.exception))

    def test_invalid_json_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text("{not json")
            with self.assertRaises(config.ConfigError):
                config.load(p)

    def test_missing_file_points_at_the_example(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.load(Path("/nonexistent/config.json"))
        self.assertIn("config.example.json", str(cm.exception))

    def test_example_config_loads_with_slack_off(self):
        cfg = config.load(ROOT / "app" / "config.example.json")
        self.assertEqual(cfg["channel"], "")
        self.assertTrue(cfg["repos"])
        self.assertIs(cfg["auto_merge"], False)


class RunPy(unittest.TestCase):
    def test_run_without_config_explains_what_to_do(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / "app", Path(d) / "app", ignore=shutil.ignore_patterns("config.json", "__pycache__"))
            p = subprocess.run([sys.executable, str(Path(d) / "app" / "run.py"), "full"], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("config.example.json", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
