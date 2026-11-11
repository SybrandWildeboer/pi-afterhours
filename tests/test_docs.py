import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_docs  # noqa: E402

README = ("# T\nThe installer is untested from scratch. This project is not affiliated with Anthropic. "
          "Everything starts in dry-run. Costs are an estimate.\n[guide](docs/01-hardware-and-os.md)\n")


def valid_tree(d):
    root = Path(d)
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text(README)
    for name in check_docs.REQUIRED_DOCS:
        (root / "docs" / name).write_text(f"# {name}\nsoft wall\n")
    return root


class Check(unittest.TestCase):
    def errors(self, mutate=None):
        with tempfile.TemporaryDirectory() as d:
            root = valid_tree(d)
            if mutate:
                mutate(root)
            return check_docs.check(root)

    def test_a_valid_tree_passes(self):
        self.assertEqual(self.errors(), [])

    def test_required_phrase_missing_is_reported(self):
        errs = self.errors(lambda r: (r / "README.md").write_text(README.replace("untested from scratch", "tested")))
        self.assertTrue(any("untested from scratch" in e for e in errs), errs)

    def test_missing_doc_is_reported(self):
        errs = self.errors(lambda r: (r / "docs" / "09-troubleshooting.md").unlink())
        self.assertTrue(any("09-troubleshooting" in e for e in errs), errs)

    def test_broken_link_is_reported(self):
        errs = self.errors(lambda r: (r / "README.md").write_text(README + "[x](docs/nope.md)\n"))
        self.assertTrue(any("broken link" in e and "nope.md" in e for e in errs), errs)

    def test_external_and_anchor_links_are_ignored(self):
        self.assertEqual(self.errors(lambda r: (r / "README.md").write_text(README + "[a](https://example.com) [b](#top)\n")), [])

    def test_private_term_in_a_doc_is_reported(self):
        def plant(r):
            (r / ".leakcheck-terms").write_text("acme-secret\n")
            (r / "docs" / "01-hardware-and-os.md").write_text("# x\nsoft wall\nsee ACME-secret here\n")
        errs = self.errors(plant)
        self.assertTrue(any("acme-secret" in e.lower() for e in errs), errs)

    def test_soft_wall_missing_in_security_doc_is_reported(self):
        errs = self.errors(lambda r: (r / "docs" / "07-security-model.md").write_text("# no caveat here\n"))
        self.assertTrue(any("soft wall" in e and "07-security-model" in e for e in errs), errs)


class RealDocs(unittest.TestCase):
    def test_the_real_docs_pass(self):
        self.assertEqual(check_docs.check(ROOT), [])

    def test_delegation_caveat_sits_next_to_delegation(self):
        lines = (ROOT / "docs" / "04-remote-control.md").read_text().lower().splitlines()
        bg = [i for i, l in enumerate(lines) if "--bg" in l]
        wall = [i for i, l in enumerate(lines) if "soft wall" in l]
        self.assertTrue(bg, "docs/04 must explain delegation with `--bg`")
        self.assertTrue(any(abs(b - w) <= 30 for b in bg for w in wall), "the soft-wall caveat must be within 30 lines of --bg")


if __name__ == "__main__":
    unittest.main()
