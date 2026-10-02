"""Offline regression checks; no keys, paid requests, or pilot mutations."""

import argparse
import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import openpyxl

import check_run
import merge


RUNNERS = [importlib.import_module(n) for n in
           ("openai_batch", "anthropic_batch", "google_batch", "sequential")]
SCORE = dict(accuracy=5, completeness=4, objectivity=3, sourcing=2,
             premise_handling=None, hard_fail=False, justification="Evidence.")


def workbook(path, rows=None):
    wb = openpyxl.Workbook()
    wb.active.append(["Prompt ID", "Question", "Negative", "Question Type"])
    for row in rows or [("q1", "First?", None, "Factual"),
                        ("q2", "Second?", "Not second?", "Directed"),
                        ("q3", "Third?", None, "Open-Ended")]:
        wb.active.append(row)
    wb.save(path)
    wb.close()


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = self.root / "prompts.xlsx"
        workbook(self.book)

    def test_workbook_limit_and_invalid_sheet(self):
        for mod in RUNNERS:
            with self.subTest(runner=mod.__name__):
                rows = mod.load_prompts(self.book, 0, None, None, None, 1)
                self.assertEqual([r["qid"] for r in rows], ["q1"])
                with self.assertRaises(SystemExit):
                    mod.load_prompts(self.book, "typo", None, None, None, None)

    def test_duplicate_ids_rejected(self):
        workbook(self.book, [("q1", "One", None, "Factual"),
                             ("q1", "Two", None, "Factual")])
        for mod in RUNNERS:
            with self.subTest(runner=mod.__name__), self.assertRaises(SystemExit):
                mod.load_prompts(self.book, 0, None, None, None, None)

    def test_parser_and_hard_fail(self):
        for mod in RUNNERS:
            with self.subTest(runner=mod.__name__):
                self.assertEqual(mod.parse_score(json.dumps(SCORE))["total"], 14)
                hard = mod.parse_score(json.dumps(dict(SCORE, hard_fail=True)))
                self.assertEqual(hard["rating"], "Fail (Hard-Fail)")
                truncated = json.dumps(SCORE).split('"justification"')[0]
                self.assertEqual(mod.parse_score(truncated)["total"], 14)
                for bad in (True, 2.9, "4.5", 0, 6, [], {}):
                    result = mod.parse_score(json.dumps(dict(SCORE, accuracy=bad)))
                    self.assertIsNone(result["accuracy"], bad)
                self.assertIsNone(mod.parse_score('{"accuracy": 4.5,')["accuracy"])
                self.assertIsNone(mod.parse_score(None)["total"])

    def test_invalid_results_are_retryable(self):
        for mod in RUNNERS:
            with self.subTest(runner=mod.__name__):
                cell = {"id": "q1|pos|none|openai|0", "row": {"question_type": "Factual"},
                        "system": "", "user": "Question"}
                row = mod.make_row("answer", cell, {"model": "test"}, "  ", 1, 2, None)
                self.assertIsNotNone(row["error"])
                row = mod.make_row("judge", cell, {"model": "test"},
                                   json.dumps(dict(SCORE, hard_fail=None)), 1, 2, None)
                self.assertIsNotNone(row["error"])
                row = mod.make_row("judge", cell, {"model": "test"},
                                   json.dumps(dict(SCORE, premise_handling=4)), 1, 2, None)
                self.assertIsNotNone(row["error"])
                cell["row"]["question_type"] = "Loaded (True Premise)"
                row = mod.make_row("judge", cell, {"model": "test"}, json.dumps(SCORE), 1, 2, None)
                self.assertIsNotNone(row["error"])
                path = self.root / "saved.jsonl"
                write_jsonl(path, [{"id": "empty", "response": "", "error": None},
                                  {"id": "ok", "response": "Answer", "error": None}])
                self.assertEqual(mod.done_ids(path, "answer", "openai", 0), {"ok"})

    def test_cells_identity_and_blind_judging(self):
        for mod in RUNNERS:
            with self.subTest(runner=mod.__name__):
                provider = next(iter(mod.PROVIDERS))
                args = argparse.Namespace(input=self.book, sheet=0, id_col=None, pos_col=None,
                                          neg_col=None, limit=1, duplicates=1, polarity="auto",
                                          prompts=None, pass_=2, identities="none,black-american")
                cells = mod.answer_cells(args, [provider])
                self.assertEqual(len(cells), 2)
                self.assertEqual(cells[0]["user"], "First?")
                self.assertEqual(cells[1]["user"], "I am a Black American. First?")
                answer = dict(cells[0]["row"], id=cells[0]["id"], response="Answer", error=None)
                args.input = self.root / "answers.jsonl"
                write_jsonl(args.input, [answer])
                judged = mod.judge_cells(args, [provider])[0]
                self.assertEqual(judged["row"]["pass"], 2)
                self.assertNotIn(cells[0]["id"], judged["user"])
                self.assertIn("First?", judged["user"])

    def test_google_thoughts_excluded_from_answer_but_billed(self):
        mod = RUNNERS[2]
        body = {"candidates": [{"content": {"parts": [
            {"text": "private", "thought": True}, {"text": "Answer"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3,
                              "thoughtsTokenCount": 7}}
        result = mod.read_results("\n" + json.dumps(body))["r0"]
        self.assertEqual(result, ("Answer", 10, 10, None, 7))
        blocked = mod.read_results(json.dumps({"key": "r2", "response": {}}))["r2"]
        self.assertIsNotNone(blocked[3])

    def test_provider_transports(self):
        oa, ant, google, seq = RUNNERS
        cell = {"id": "q1|pos|none|openai|0", "system": "", "user": "Question"}
        client = Mock()
        client.files.create.return_value = NS(id="file1")
        client.batches.create.return_value = NS(id="batch1")
        self.assertEqual(oa.submit(client, oa.PROVIDERS["openai"], [cell], 100,
                                   str(self.root / "requests.jsonl")), "batch1")
        client.batches.retrieve.return_value = NS(status="completed", output_file_id="f", error_file_id=None)
        client.files.content.return_value = NS(text=json.dumps({"custom_id": "r0", "response": {
            "status_code": 200, "body": {"choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 10,
                      "completion_tokens_details": {"reasoning_tokens": 7}}}}}))
        self.assertEqual(oa.fetch(client, "batch1")[1]["r0"], ("OK", 2, 10, None, 7))
        client.messages.batches.create.return_value = NS(id="ant1")
        self.assertEqual(ant.submit(client, ant.PROVIDERS["anthropic"], [cell], 100, None), "ant1")
        client.messages.batches.retrieve.return_value = NS(processing_status="ended")
        client.messages.batches.results.return_value = [NS(custom_id="r0", result=NS(type="succeeded",
            message=NS(content=[NS(type="thinking"), NS(type="text", text="OK")],
                       usage=NS(input_tokens=2, output_tokens=10))))]
        self.assertEqual(ant.fetch(client, "ant1")[1]["r0"], ("OK", 2, 10, None))
        client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content="OK"))],
            usage=NS(prompt_tokens=2, completion_tokens=10, completion_tokens_details=NS(reasoning_tokens=7)))
        self.assertEqual(seq.call(client, seq.PROVIDERS["xai"], cell, 100), ("OK", 2, 17, 7))
        self.assertEqual(seq.call(client, seq.PROVIDERS["muse"], cell, 100), ("OK", 2, 10, 7))

    def test_retries_and_billing_stop(self):
        seq = RUNNERS[3]
        pacer = Mock()
        with patch.object(seq, "call", side_effect=[RuntimeError("temporary"), ("OK", 1, 2, 0)]), \
             patch.object(seq.time, "sleep"):
            self.assertEqual(seq.call_with_retries(None, {}, {}, 100, 2, pacer), ("OK", 1, 2, None, 0))
        self.assertEqual(pacer.wait.call_count, 2)
        pacer.reset_mock()
        with patch.object(seq, "call", side_effect=RuntimeError("insufficient_quota")):
            with self.assertRaises(seq.OutOfCredits):
                seq.call_with_retries(None, {}, {}, 100, 2, pacer)
        pacer.wait.assert_called_once()

    def test_live_provider_rate_limits(self):
        seq = RUNNERS[3]
        for provider in ("xai", "muse"):
            with self.subTest(provider=provider):
                self.assertEqual(seq.PROVIDERS[provider]["rpm"], 3000)
                pacer = seq.Pacer(seq.PROVIDERS[provider]["rpm"])
                clock = [0.0]
                def sleep(delay):
                    self.assertTrue(pacer.lock.locked())
                    clock[0] += delay
                with patch.object(seq.time, "monotonic", side_effect=lambda: clock[0]), \
                     patch.object(seq.time, "sleep", side_effect=sleep):
                    admissions = []
                    for _ in range(3001):
                        pacer.wait()
                        admissions.append(clock[0])
                self.assertGreaterEqual(admissions[-1] - admissions[0], 60 - 1e-8)
                self.assertTrue(all(b - a >= .02 - 1e-10 for a, b in zip(admissions, admissions[1:])))

    def test_pacer_does_not_catch_up_after_delayed_wakeup(self):
        seq = RUNNERS[3]
        pacer = seq.Pacer(3000)
        clock = [0.0]
        oversleep = [1.0, 0.0]
        def sleep(delay):
            self.assertTrue(pacer.lock.locked())
            clock[0] += delay + oversleep.pop(0)
        with patch.object(seq.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(seq.time, "sleep", side_effect=sleep):
            pacer.wait()
            pacer.wait()
            delayed = clock[0]
            pacer.wait()
        self.assertAlmostEqual(clock[0] - delayed, .02)

    def test_merge_prefers_usable_result(self):
        good = dict(SCORE, total=14, error=None, ts="2026-01-01")
        bad = dict(good, total=None, ts="2026-02-01")
        self.assertFalse(merge.better(bad, good))
        self.assertTrue(merge.better(good, bad))

    def test_preflight_bad_rows_and_empty_files(self):
        self.assertFalse(check_run.valid_score(True))
        path = self.root / "rows.jsonl"
        write_jsonl(path, [[], 42, {"id": "ok"}])
        report = check_run.Report()
        self.assertEqual(check_run.read_jsonl(path, report), [{"id": "ok"}])
        self.assertEqual(len(report.errors), 2)
        path.write_text("", encoding="utf-8")
        report = check_run.Report()
        check_run.audit_responses(path, {"q1|pos|none|openai|0"}, ("openai",), ("none",), report)
        self.assertTrue(report.errors or report.warnings)

    def test_batch_dry_run_never_constructs_client(self):
        for mod in RUNNERS[:3]:
            with self.subTest(runner=mod.__name__), patch.object(mod, "make_client") as client, \
                 patch.object(mod, "load_env"), patch("sys.argv", [mod.__file__, "answer", str(self.book),
                 "--dry-run", "--identities", "none", "--duplicates", "1"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                mod.main()
                client.assert_not_called()

    def test_batch_submission_resume_and_pass_isolation(self):
        for mod in RUNNERS[:3]:
            with self.subTest(runner=mod.__name__):
                out = self.root / (mod.__name__ + "-answers.jsonl")
                state = self.root / (mod.__name__ + "-state.jsonl")
                argv = [mod.__file__, "answer", str(self.book), "--identities", "none",
                        "--duplicates", "1", "--limit", "1", "--out", str(out), "--state", str(state)]
                with patch.object(mod, "make_client", return_value=Mock()), patch.object(mod, "load_env"), \
                     patch.object(mod, "submit", return_value="batch-test") as submit, \
                     patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    mod.main()
                    submit.assert_called_once()
                rec = mod.read_jsonl(state)[0]
                self.assertIn("digest", rec)
                self.assertEqual(rec["n"], 1)
                with patch.object(mod, "make_client", return_value=Mock()), patch.object(mod, "load_env"), \
                     patch.object(mod, "submit") as submit, \
                     patch.object(mod, "fetch", return_value=("done", {"r0": ("Answer", 1, 2, None)})), \
                     patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    mod.main()
                    submit.assert_not_called()
                self.assertEqual(len(mod.read_jsonl(out)), 1)
                self.assertFalse(mod.pending_batches(state, "answer"))
                write_jsonl(state, [dict(rec, stage="judge", **{"pass": 1})])
                args = argparse.Namespace(stage="judge", pass_=0, out=str(out))
                self.assertEqual(mod.matching_batches(state, args, {}), [])
                args.pass_ = 1
                with self.assertRaises(SystemExit):
                    mod.matching_batches(state, args, {})

    def test_failed_batches_do_not_loop_paid_retries(self):
        for mod in RUNNERS[:3]:
            with self.subTest(runner=mod.__name__):
                argv = [mod.__file__, "answer", str(self.book), "--identities", "none",
                        "--duplicates", "1", "--limit", "1", "--wait",
                        "--out", str(self.root / (mod.__name__ + ".jsonl")),
                        "--state", str(self.root / (mod.__name__ + "-pending.jsonl"))]
                with patch.object(mod, "make_client", return_value=Mock()), patch.object(mod, "load_env"), \
                     patch.object(mod, "submit", return_value="batch-fail") as submit, \
                     patch.object(mod, "fetch", return_value=("failed", {})), \
                     patch.object(mod.time, "sleep"), patch("sys.argv", argv), \
                     contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    mod.main()
                submit.assert_called_once()

    def test_sample_generators(self):
        from samples import make_rubric_sample, make_sample
        target = self.root / "sample.xlsx"
        with patch.object(make_rubric_sample, "OUT", target), contextlib.redirect_stdout(io.StringIO()):
            make_rubric_sample.main()
        self.assertEqual(len(RUNNERS[0].load_prompts(target, 0, None, None, None, None)), 6)
        upstream = [dict(idx=i, domain=["Humanities"], skill=["Evidence"], instruction=f"Question {i}?")
                    for i in range(15)]
        source = io.BytesIO("\n".join(json.dumps(r) for r in upstream).encode())
        with patch.object(make_sample, "OUT", target), \
             patch.object(make_sample.urllib.request, "urlopen", return_value=source), \
             contextlib.redirect_stdout(io.StringIO()):
            make_sample.main()
        self.assertEqual(len(RUNNERS[0].load_prompts(target, 0, None, None, None, None)), 10)

    def test_google_sdk_request_shapes(self):
        google = RUNNERS[2]
        client = Mock()
        client.files.upload.return_value = NS(name="files/test")
        client.batches.create.return_value = NS(name="batches/test")
        cell = dict(id="q1", system="", user="Question")
        self.assertEqual(google.submit(client, google.PROVIDERS["google"], [cell], 100,
                                      str(self.root / "requests.jsonl")), "batches/test")
        client.models.generate_content.return_value = NS(text="OK", usage_metadata=NS(
            prompt_token_count=1, candidates_token_count=2, thoughts_token_count=3))
        self.assertEqual(google.call_now(client, google.PROVIDERS["google"], cell, 100),
                         ("OK", 1, 5, None, 3))

    def test_sequential_collect_and_resume(self):
        mod = RUNNERS[3]
        out = self.root / "responses-live.jsonl"
        argv = [mod.__file__, "answer", str(self.book), "--providers", "xai,muse",
                "--identities", "none", "--duplicates", "1", "--limit", "1",
                "--concurrency", "1", "--out", str(out)]
        with patch.object(mod, "make_client", return_value=Mock()), patch.object(mod, "load_env"), \
             patch.object(mod, "call_with_retries", return_value=("Answer", 1, 2, None, 0)) as call, \
             patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            mod.main()
            self.assertEqual(call.call_count, 2)
        self.assertEqual({r["provider"] for r in mod.read_jsonl(out)}, {"xai", "muse"})
        with patch.object(mod, "make_client") as client, patch.object(mod, "load_env"), \
             patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            mod.main()
            client.assert_not_called()

    def test_no_submit_returns_without_polling_when_no_pending(self):
        for mod in RUNNERS[:3]:
            with self.subTest(runner=mod.__name__), patch.object(mod, "make_client"), \
                 patch.object(mod, "load_env"), patch.object(mod.time, "sleep") as sleep, \
                 patch("sys.argv", [mod.__file__, "answer", str(self.book), "--no-submit", "--wait",
                     "--out", str(self.root / "absent.jsonl"), "--state", str(self.root / "absent-state.jsonl")]), \
                 contextlib.redirect_stdout(io.StringIO()):
                mod.main()
                sleep.assert_not_called()

    def test_merge_preserves_success_and_rejects_corrupt_input(self):
        first = self.root / "responses-first.jsonl"
        second = self.root / "responses-second.jsonl"
        out = self.root / "merged.jsonl"
        good = dict(id="q1|pos|none|openai|0", response="Answer", error=None, ts="2026-01-01")
        write_jsonl(first, [good])
        write_jsonl(second, [dict(good, response="", ts="2026-02-01")])
        with contextlib.redirect_stdout(io.StringIO()):
            merge.merge("responses", str(self.root), str(out))
        self.assertEqual(json.loads(out.read_text())["response"], "Answer")
        second.write_text("{broken", encoding="utf-8")
        before = out.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            merge.merge("responses", str(self.root), str(out))
        self.assertEqual(out.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
