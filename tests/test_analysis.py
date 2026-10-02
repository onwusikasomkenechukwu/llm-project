import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze


def grade(qid="q1", provider="a", identity="none", judge="a", run=0, score=3, **extra):
    row = dict(id=f"{qid}|pos|{identity}|{provider}|{run}", qid=qid, polarity="pos",
               identity=identity, provider=provider, judge=judge, question_type="Factual",
               judge_model=judge + "-v1", accuracy=score, completeness=score, objectivity=score,
               sourcing=score, total=score * 4, hard_fail=False, premise_handling=None,
               error=None, **{"pass": 0})
    return row | extra


class AnalysisTests(unittest.TestCase):
    def test_questions_are_equal_weight_and_bootstrap_deterministic(self):
        clusters = {"q1": [4] * 100, "q2": [20]}
        result = analyze.estimate(clusters, 500, 42)
        self.assertEqual(result["mean"], 12)
        self.assertEqual(result["n_questions"], 2)
        self.assertEqual(result, analyze.estimate(clusters, 500, 42))
        self.assertEqual((result["ci_low"], result["ci_high"]), (4, 20))
        self.assertIsNone(analyze.estimate({"q1": [4, 20]}, 500, 42)["ci_low"])

    def test_identity_comparison_uses_matched_cells(self):
        rows = [grade("q1", score=2), grade("q1", identity="black-american", score=4),
                grade("q2", score=4), grade("q2", identity="black-american", score=5),
                grade("q3", identity="black-american", score=1)]
        result = next(r for r in analyze.paired_comparisons(rows, "identity", 100, 42)
                      if r["metric"] == "total")
        self.assertEqual(result["mean"], 6)
        self.assertEqual(result["n_questions"], 2)
        self.assertEqual(result["unmatched_cells"], 1)

    def test_self_preference_matches_same_answer(self):
        rows = [grade("q1", judge="a", score=5), grade("q1", judge="b", score=3),
                grade("q2", provider="b", judge="a", score=1)]
        result = analyze.self_preference(rows, 100, 42)
        self.assertEqual(result[0]["mean"], 8)
        self.assertEqual(result[0]["n_observations"], 1)

    def test_replicates_use_common_judges(self):
        rows = [grade(run=0, judge="a", score=2), grade(run=1, judge="a", score=4),
                grade(run=1, judge="b", score=1)]
        result = analyze.replicate_variability(rows)[0]
        self.assertEqual(result["mean_total"], 12)
        self.assertAlmostEqual(result["sd_total"], 32 ** .5)
        self.assertEqual(result["n_common_judge_passes"], 1)

    def test_hard_fail_is_not_silently_rescored(self):
        rows = [grade(hard_fail=True, score=5)]
        result = {r["metric"]: r["mean"] for r in analyze.group_summary(rows, ("provider",), 100, 42)}
        self.assertEqual(result["total"], 20)
        self.assertEqual(result["hard_fail"], 1)

    def test_invalid_duplicate_and_mixed_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grades.jsonl"
            def save(rows):
                path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            save([grade(), grade("q2", accuracy=True)])
            rows, report = analyze.load_grades(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(report["excluded"], {"invalid_scores": 1})
            save([grade(), grade()])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                analyze.load_grades(path)
            save([grade(), grade("q2", judge_model="new")])
            with self.assertRaisesRegex(ValueError, "versions"):
                analyze.load_grades(path)

    def test_end_to_end_exports_and_missing_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "grades.jsonl"
            rows = [grade("q1", judge="a"), grade("q1", judge="b"), grade("q2", judge="a")]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with patch("sys.argv", ["analyze.py", str(path), "--bootstrap", "100",
                                    "--out-dir", str(root / "analysis")]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(analyze.main(), 0)
            report = json.loads((root / "analysis" / "summary.json").read_text())
            self.assertEqual(report["coverage"]["answers_missing_observed_panel"], 1)
            self.assertEqual(len(list((root / "analysis").glob("*.csv"))), 10)


if __name__ == "__main__":
    unittest.main()
