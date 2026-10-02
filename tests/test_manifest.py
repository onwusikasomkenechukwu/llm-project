import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import run_manifest as manifest
import openai_batch
from test_pipeline import workbook


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = self.root / "input.xlsx"
        workbook(self.book)
        self.path = self.root / "run" / "manifest.json"
        self.args = NS(out=self.path, prompts=self.book, providers="openai", judges="openai",
                       identities="none", duplicates=1, passes=2, polarity="pos", sheet="0",
                       id_col=None, pos_col=None, neg_col=None, limit=1, operator="tester", label="fixture")

    def create(self):
        manifest.create_manifest(self.args)
        return manifest.load_manifest(self.path)

    def test_create_verify_and_mutation_detection(self):
        run = self.create()
        self.assertEqual(run["operator"], "tester")
        self.assertEqual(run["grid"]["duplicates"], 1)
        self.assertEqual(run["settings"]["openai_batch.py"]["PROVIDERS"]["openai"]["model"], "gpt-5.5")
        self.assertNotIn("api_key", json.dumps(run))
        self.assertEqual(manifest.load_manifest(self.path, artifacts=True)["run_id"], run["run_id"])
        (self.path.parent / "prompts.xlsx").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "workbook"):
            manifest.load_manifest(self.path)

    def test_manifest_and_event_tampering(self):
        self.create()
        original = self.path.read_bytes()
        self.path.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "manifest hash"):
            manifest.load_manifest(self.path)
        self.path.write_bytes(original)
        manifest.record_event(self.path.parent, {"event": "note"})
        log = self.path.parent / "events.jsonl"
        lines = log.read_text().splitlines()
        log.write_text(lines[0] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "head mismatch"):
            manifest.load_manifest(self.path)

    def test_code_and_environment_changes_are_rejected(self):
        self.create()
        with patch.object(manifest, "source_hashes", return_value={}):
            with self.assertRaisesRegex(ValueError, "source code changed"):
                manifest.load_manifest(self.path)
        with patch.object(manifest, "environment", return_value={}):
            with self.assertRaisesRegex(ValueError, "versions changed"):
                manifest.load_manifest(self.path)

    def test_runner_plan_and_dry_run_record(self):
        run = self.create()
        args = NS(provider="openai", stage="answer", pass_=0, dry_run=True,
                  now=False, wait=False, no_submit=False)
        cmd, artifacts = manifest.runner_command(run, self.path.parent, args)
        self.assertIn("--limit", cmd)
        self.assertEqual(manifest.execute(self.path, run, cmd, artifacts, "dry-answer"), 0)
        events = manifest.read_events(self.path.parent)
        self.assertEqual(events[-1]["exit_code"], 0)
        self.assertEqual(events[-2]["invocation_id"], events[-1]["invocation_id"])
        self.assertEqual(events[-1]["artifacts"], {})
        manifest.load_manifest(self.path, artifacts=True)
        args.stage = "judge"
        cmd, _ = manifest.runner_command(run, self.path.parent, args)
        self.assertNotIn("--limit", cmd)
        with self.assertRaisesRegex(ValueError, "merge responses"):
            manifest.execute(self.path, run, cmd, [], "judge")

    def test_foreign_output_and_lock_are_rejected(self):
        run = self.create()
        out = self.path.parent / "responses-openai.jsonl"
        out.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "unrecorded"):
            manifest.execute(self.path, run, ["unused"], [out], "output")
        with manifest.lock(self.path.parent / ".output.lock"):
            with self.assertRaisesRegex(ValueError, "lock exists"):
                manifest.execute(self.path, run, ["unused"], [], "output")

    def test_nonzero_exit_and_provenance(self):
        run = self.create()
        with patch.object(manifest.subprocess, "run", return_value=NS(returncode=7)) as process:
            self.assertEqual(manifest.execute(self.path, run, ["test"], [], "failure"), 7)
        self.assertEqual(manifest.read_events(self.path.parent)[-1]["exit_code"], 7)
        self.assertEqual(process.call_args.kwargs["env"]["BENCHMARK_RUN_ID"], run["run_id"])
        with patch.dict(os.environ, {"BENCHMARK_RUN_ID": "run", "BENCHMARK_INVOCATION_ID": "inv"}):
            row = openai_batch.make_row("answer", dict(id="q1", row={}, system="", user="Q"),
                                       dict(model="test"), "Answer", 1, 2, None)
        self.assertEqual((row["run_id"], row["invocation_id"]), ("run", "inv"))

    def test_create_rejects_existing_directory_and_invalid_grid(self):
        self.create()
        with self.assertRaisesRegex(ValueError, "empty run directory"):
            manifest.create_manifest(self.args)
        self.args.out = self.root / "bad" / "manifest.json"
        self.args.duplicates = 0
        with self.assertRaisesRegex(ValueError, "preflight failed"):
            manifest.create_manifest(self.args)
        self.assertFalse(self.args.out.exists())

    def test_complete_pipeline_with_mocked_collection(self):
        run = self.create()
        directory = self.path.parent
        response = dict(id="q1|pos|none|openai|0", qid="q1", polarity="pos", identity="none",
                        provider="openai", run=0, question_type="Factual", model="test",
                        response="Answer", error=None, run_id=run["run_id"])
        scores = dict(accuracy=5, completeness=4, objectivity=3, sourcing=2, total=14,
                      premise_handling=None, hard_fail=False, raw="grader output", judge="openai",
                      judge_model="test", error=None, run_id=run["run_id"])
        def collect(command, **kwargs):
            (directory / "responses-openai.jsonl").write_text(json.dumps(response) + "\n")
            grades = [dict(response, **{"pass": p}) | scores for p in range(2)]
            (directory / "judgments-openai.jsonl").write_text("".join(json.dumps(r) + "\n" for r in grades))
            return NS(returncode=0)
        with patch.object(manifest.subprocess, "run", side_effect=collect):
            manifest.execute(self.path, run, ["fixture-collection"],
                             [directory / "responses-openai.jsonl", directory / "judgments-openai.jsonl"],
                             "fixture")
        self.assertEqual(manifest.finish(self.path, run), 0)
        manifest.load_manifest(self.path, artifacts=True)
        self.assertEqual(manifest.read_events(directory)[-1]["event"], "complete")
        self.assertTrue((directory / "analysis" / "summary.json").is_file())

    def test_interrupted_invocation_recovery_preserves_audit(self):
        run = self.create()
        directory = self.path.parent
        manifest.record_event(directory, dict(event="started", invocation_id="interrupted",
            run_id=run["run_id"], lock=".responses-openai.lock", artifact_targets=["responses-openai.jsonl"]))
        with self.assertRaisesRegex(ValueError, "active or interrupted"):
            manifest.load_manifest(self.path, artifacts=True)
        with manifest.lock(directory / ".responses-openai.lock"):
            with self.assertRaisesRegex(ValueError, "lock remains"):
                manifest.recover(self.path, run, "interrupted", "fixture interruption")
        (directory / "responses-openai.jsonl").write_text("{}\n")
        manifest.recover(self.path, run, "interrupted", "fixture interruption")
        manifest.load_manifest(self.path, artifacts=True)
        self.assertEqual(manifest.read_events(directory)[-1]["failure"], "recovered_interruption")


if __name__ == "__main__":
    unittest.main()
