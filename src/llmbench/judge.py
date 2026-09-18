"""Phase 3: score stored responses.

This phase never calls an answering model. It reads responses off disk, so the
rubric can change, the judge model can change, and a parsing bug can be fixed,
all without re-spending the generation budget. The raw judge text is stored on
every row precisely so a parser change does not require re-judging.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import BudgetExceeded, BudgetLedger
from .config import ExperimentConfig
from .ids import judge_prompt_hash, judgment_id
from .pricing import cost_usd, estimate_input_tokens, precall_estimate
from .prompts.build import build_judge_request, load_judge_template
from .providers.registry import build_provider
from .questions import load_questions
from .records import (
    ErrorInfo,
    JudgmentRecord,
    ParsedJudgment,
    PromptPayload,
    Usage,
    code_version,
    utcnow_iso,
)
from .retry import classify, with_retry
from .runner import _Timer
from .storage import (
    JsonlWriter,
    existing_judgment_ids,
    latest_ok_responses,
    new_judgment_path,
    write_manifest,
)

FENCE_PREFIXES = ("```json", "```JSON", "```")


def extract_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Pull one JSON object out of judge output.

    Handles the three things judges actually do: return clean JSON, wrap it in a
    code fence, or bracket it with prose. Returns (obj, error_message).
    """
    if not text or not text.strip():
        return None, "empty judge output"

    candidate = text.strip()
    for fence in FENCE_PREFIXES:
        if candidate.startswith(fence):
            candidate = candidate[len(fence) :]
            if candidate.rstrip().endswith("```"):
                candidate = candidate.rstrip()[:-3]
            candidate = candidate.strip()
            break

    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj, None
    except json.JSONDecodeError:
        pass

    # Scan for the first balanced object, ignoring braces inside strings.
    start = candidate.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(candidate[start : i + 1])
                        if isinstance(obj, dict):
                            return obj, None
                    except json.JSONDecodeError as exc:
                        return None, f"balanced object did not parse: {exc}"
                    break
        start = candidate.find("{", start + 1)

    return None, "no JSON object found in judge output"


def parse_judgment(text: str) -> tuple[ParsedJudgment | None, str | None]:
    obj, err = extract_json_object(text)
    if obj is None:
        return None, err
    try:
        return ParsedJudgment.model_validate(obj), None
    except Exception as exc:  # noqa: BLE001 - message is recorded on the row
        return None, f"schema validation failed: {exc}"


@dataclass
class JudgeStats:
    responses_available: int = 0
    skipped_done: int = 0
    planned: int = 0
    ok: int = 0
    parse_failed: int = 0
    failed: int = 0
    repairs_attempted: int = 0
    aborted_on_budget: bool = False
    cost_usd: float = 0.0
    output_path: Path | None = None
    errors_by_type: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["output_path"] = str(self.output_path) if self.output_path else None
        d["cost_usd"] = round(self.cost_usd, 6)
        return d


async def judge_phase(
    cfg: ExperimentConfig,
    run_dir: Path,
    limit: int | None = None,
    dry_run: bool = False,
    progress_every: int = 25,
    log=sys.stderr,
) -> JudgeStats:
    stats = JudgeStats()
    jcfg = cfg.judge

    questions = {
        q.question_id: q
        for q in load_questions(
            cfg.questions.path,
            limit=cfg.questions.limit,
            require_verified_negation=cfg.questions.require_verified_negation,
        )
    }
    template = load_judge_template(jcfg.prompt_path)
    responses = latest_ok_responses(run_dir)
    stats.responses_available = len(responses)
    if not responses:
        raise FileNotFoundError(
            f"no successful responses under {run_dir / 'responses'}. Run `llmbench run` first."
        )

    already = existing_judgment_ids(run_dir)

    work: list[tuple[str, Any]] = []
    for cell_id_value, rec in responses.items():
        jid = judgment_id(
            cell_id_value,
            jcfg.provider.id,
            jcfg.provider.model,
            jcfg.run_index,
            jcfg.rubric_version,
        )
        if jid in already:
            stats.skipped_done += 1
            continue
        work.append((jid, rec))

    if limit is not None:
        work = work[:limit]
    stats.planned = len(work)

    if dry_run:
        print(
            f"[dry-run] {stats.responses_available} responses, "
            f"{stats.skipped_done} already judged, {stats.planned} to judge",
            file=log,
        )
        return stats
    if not work:
        print("nothing to do: every response already has a parsed judgment", file=log)
        return stats

    ledger = BudgetLedger(
        max_total_usd=cfg.budget.max_total_usd,
        phase="judge",
        phase_cap_usd=cfg.budget.per_phase_usd.get("judge"),
        estimate_headroom=cfg.budget.estimate_headroom,
        abort_on_exceed=cfg.budget.abort_on_exceed,
    )
    provider = build_provider(jcfg.provider)
    out_path = new_judgment_path(run_dir, jcfg.provider.id, jcfg.run_index)
    stats.output_path = out_path

    queue: asyncio.Queue = asyncio.Queue()
    for item in work:
        queue.put_nowait(item)

    abort = asyncio.Event()
    write_lock = asyncio.Lock()
    counter = {"n": 0}
    judge_max_tokens = int(jcfg.provider.params.get("max_tokens", 500))

    print(
        f"judge: {stats.planned} responses with {jcfg.provider.model} "
        f"(rubric {jcfg.rubric_version}, run {jcfg.run_index}) -> {out_path.name}",
        file=log,
    )

    with JsonlWriter(out_path) as writer:

        async def emit(record: JudgmentRecord) -> None:
            async with write_lock:
                writer.write(record)
            counter["n"] += 1
            if progress_every and counter["n"] % progress_every == 0:
                print(
                    f"  {counter['n']}/{stats.planned} judged "
                    f"({stats.ok} parsed, {stats.parse_failed} unparseable, "
                    f"${ledger.committed_usd:.3f} spent)",
                    file=log,
                )

        def base_fields(jid: str, rec) -> dict[str, Any]:
            return {
                "judgment_id": jid,
                "cell_id": rec.cell_id,
                "question_id": rec.question_id,
                "polarity": rec.polarity,
                "perspective_id": rec.perspective_id,
                "provider_id": rec.provider_id,
                "run_index": rec.run_index,
                "response_line_ref": {"prompt_hash": rec.prompt_hash},
                "judge_provider_id": jcfg.provider.id,
                "judge_model_requested": jcfg.provider.model,
                "judge_run_index": jcfg.run_index,
                "rubric_version": jcfg.rubric_version,
                "config_hash": cfg.config_hash,
                "code_version": code_version(),
            }

        async def handle(jid: str, rec) -> None:
            question = questions.get(rec.question_id)
            if question is None:
                raise KeyError(
                    f"response references question_id {rec.question_id!r}, "
                    f"absent from {cfg.questions.path}"
                )
            claim = question.text(rec.polarity)
            answer = rec.response_text or ""

            repair_note: str | None = None
            total_usage = Usage()
            total_cost = 0.0
            last_raw: str | None = None
            last_error: str | None = None
            repairs = 0
            timer = _Timer()

            for attempt in range(jcfg.max_repair_attempts + 1):
                req = build_judge_request(
                    template,
                    claim,
                    answer,
                    max_tokens=judge_max_tokens,
                    temperature=float(jcfg.provider.params.get("temperature", 0.0)),
                    repair_note=repair_note,
                    meta={"cell_id": rec.cell_id},
                )
                payload = req.wire_payload()
                est_in = estimate_input_tokens(*(m["content"] for m in req.messages))
                reservation = await ledger.reserve(
                    precall_estimate(
                        est_in, req.max_tokens, jcfg.provider.pricing, cfg.budget.estimate_headroom
                    )
                )
                try:
                    result, _ = await with_retry(
                        lambda: timer.time(lambda: provider.complete(req)),
                        cfg.reliability,
                    )
                except BaseException as exc:  # noqa: BLE001 - recorded, not swallowed
                    if isinstance(exc, asyncio.CancelledError):
                        await ledger.release(reservation)
                        raise
                    await ledger.release(reservation)
                    cls = classify(exc, cfg.reliability)
                    stats.failed += 1
                    key = type(exc).__name__
                    stats.errors_by_type[key] = stats.errors_by_type.get(key, 0) + 1
                    await emit(
                        JudgmentRecord(
                            **base_fields(jid, rec),
                            judge_prompt=PromptPayload(**payload),
                            judge_prompt_hash=judge_prompt_hash(payload),
                            judge_raw_text=last_raw,
                            parse_ok=False,
                            parse_error=last_error,
                            repair_attempts=repairs,
                            usage=total_usage,
                            cost_usd_est=total_cost,
                            pricing_used=jcfg.provider.pricing.model_dump(),
                            latency_ms=timer.last_ms,
                            created_at=utcnow_iso(),
                            error=ErrorInfo(
                                type=key,
                                message=str(exc)[:2000],
                                http_status=cls.status,
                                retryable=cls.retryable,
                            ),
                        )
                    )
                    return

                call_cost = cost_usd(
                    result.input_tokens, result.output_tokens, jcfg.provider.pricing
                )
                await ledger.commit(reservation, call_cost)
                total_cost += call_cost
                total_usage = Usage(
                    input_tokens=total_usage.input_tokens + result.input_tokens,
                    output_tokens=total_usage.output_tokens + result.output_tokens,
                )
                last_raw = result.text
                parsed, err = parse_judgment(result.text)

                if parsed is not None:
                    stats.ok += 1
                    stats.cost_usd += total_cost
                    await emit(
                        JudgmentRecord(
                            **base_fields(jid, rec),
                            judge_model_reported=result.model_reported,
                            judge_raw_text=last_raw,
                            parse_ok=True,
                            repair_attempts=repairs,
                            parsed=parsed,
                            judge_prompt=PromptPayload(**payload),
                            judge_prompt_hash=judge_prompt_hash(payload),
                            usage=total_usage,
                            cost_usd_est=total_cost,
                            pricing_used=jcfg.provider.pricing.model_dump(),
                            latency_ms=timer.last_ms,
                            created_at=utcnow_iso(),
                        )
                    )
                    return

                last_error = err
                if attempt < jcfg.max_repair_attempts:
                    repair_note = err
                    repairs += 1
                    stats.repairs_attempted += 1

            # Repairs exhausted. The raw text is kept, so a parser fix can
            # recover this row later without another judge call.
            stats.parse_failed += 1
            stats.cost_usd += total_cost
            await emit(
                JudgmentRecord(
                    **base_fields(jid, rec),
                    judge_raw_text=last_raw,
                    parse_ok=False,
                    parse_error=last_error,
                    repair_attempts=repairs,
                    judge_prompt_hash=judge_prompt_hash({"claim": claim, "answer": answer}),
                    usage=total_usage,
                    cost_usd_est=total_cost,
                    pricing_used=jcfg.provider.pricing.model_dump(),
                    latency_ms=timer.last_ms,
                    created_at=utcnow_iso(),
                )
            )

        async def worker() -> None:
            while not abort.is_set():
                try:
                    jid, rec = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await handle(jid, rec)
                except BudgetExceeded as exc:
                    if not abort.is_set():
                        stats.aborted_on_budget = True
                        print(f"\nABORT: {exc}", file=log)
                        abort.set()
                    return
                finally:
                    queue.task_done()

        n_workers = min(jcfg.provider.max_concurrency + 2, max(1, stats.planned))
        tasks = [asyncio.create_task(worker()) for _ in range(n_workers)]
        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            abort.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print("\ninterrupted: partial judgments are on disk and resumable", file=log)
            raise
        finally:
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 - shutdown must not mask results
                pass

    stats.cost_usd = ledger.committed_usd
    write_manifest(
        run_dir,
        {
            "phase": "judge",
            "finished_at": utcnow_iso(),
            "config_hash": cfg.config_hash,
            "code_version": code_version(),
            "judge": jcfg.model_dump(mode="json"),
            "stats": stats.as_dict(),
            "budget": ledger.summary(),
        },
    )
    print(
        f"judge complete: {stats.ok} parsed, {stats.parse_failed} unparseable, "
        f"{stats.failed} call failures, ${ledger.committed_usd:.4f} spent -> {out_path}",
        file=log,
    )
    if stats.parse_failed:
        print(
            f"  {stats.parse_failed} rows kept their raw judge text; fix the parser "
            "and re-run judge to recover them without new calls",
            file=log,
        )
    return stats
