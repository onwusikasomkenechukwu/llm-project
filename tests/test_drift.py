import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_drift


ROOT = Path(__file__).resolve().parents[1]


class DriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for filename in (*check_drift.RUNNERS, "check_run.py", "analyze.py", "run_manifest.py",
                         "check_drift.py", "drift-baseline.json"):
            shutil.copyfile(ROOT / filename, self.root / filename)

    def check(self, *extra):
        with patch("sys.argv", ["check_drift.py", "--root", str(self.root), *extra]), \
             contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return check_drift.main()

    def replace(self, filename, old, new):
        path = self.root / filename
        original = path.read_text(encoding="utf-8")
        self.assertIn(old, original)
        path.write_text(original.replace(old, new), encoding="utf-8")

    def test_current_tree_and_comments_pass(self):
        self.assertEqual(self.check(), 0)
        with (self.root / "openai_batch.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# Comments do not alter the benchmark contract.\n")
        self.assertEqual(self.check(), 0)

    def test_rubric_drift_fails_and_cannot_be_baselined(self):
        self.replace("google_batch.py", "accuracy - are the factual claims true?",
                     "accuracy - a different rubric")
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.check("--write-baseline"), 1)

    def test_synchronized_changes_need_explicit_baseline(self):
        for name in check_drift.RUNNERS:
            self.replace(name, "ANSWER_TOKENS = 4000", "ANSWER_TOKENS = 4001")
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.check("--write-baseline"), 0)
        self.assertEqual(self.check(), 0)

    def test_provider_models_are_pinned_separately(self):
        self.replace("openai_batch.py", 'model="gpt-5.5"', 'model="different-model"')
        self.assertEqual(self.check(), 1)

    def test_preflight_contract_drift(self):
        self.replace("check_run.py", '"black-american"', '"changed-identity"')
        self.assertEqual(self.check(), 1)

    def test_runner_stops_before_clients_on_drift(self):
        self.replace("openai_batch.py", "ANSWER_TOKENS = 4000", "ANSWER_TOKENS = 4001")
        result = subprocess.run([sys.executable, str(self.root / "openai_batch.py"),
                                 "answer", str(self.root / "absent.xlsx"), "--dry-run"],
                                capture_output=True, text=True, cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DRIFT:", result.stderr)


if __name__ == "__main__":
    unittest.main()
