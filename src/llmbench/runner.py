"""Phase 2: execute API calls and append raw responses.

Guarantees this module is responsible for:
  * resume -- a cell with an ok row is never called again
  * append-only -- every attempt becomes a row, successes and failures alike
  * spend cap -- budget is reserved before dispatch and reconciled after
  * concurrency -- capped per provider, by the provider's own semaphore
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import BudgetExceeded, BudgetLedger
from .config import ExperimentConfig
from .grid import execution_order, load_grid
from .ids import prompt_hash
from .pricing import cost_usd, estimate_input_tokens, precall_estimate
from .prompts.build import build_answer_request
from .providers.base import BaseProvider, CompletionResult
from .providers.registry import build_provider
from .questions import Question, load_questions
from .records import (
    ErrorInfo,
    PromptPayload,
    ResponseRecord,
    Usage,
    code_version,
    utcnow_iso,
)
from .retry import classify, with_retry
from .storage import JsonlWriter, ResumeIndex, new_response_path, write_manifest


@dataclass
class RunStats:
    planned: int = 0
    skipped_done: int = 0
    retry_after_error: int = 0
    ok: int = 0
    failed: int = 0
    truncated: int = 0
    aborted_on_budget: bool = False
    cost_usd: float = 0.0
    output_path: Path | None = None
    errors_by_type: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        d["output_path"] = str(self.output_path) if self.output_path else None
        d["cost_usd"] = round(self.cost_usd, 6)
        return d


class _Timer:
    """Records the duration of the most recent attempt only."""

    def __init__(self) -> None:
        self.last_ms = 0

    async def time(self, coro_fn):
        start = time.perf_counter()
        try:
            return await coro_fn()
        finally:
            self.last_ms = int((time.perf_counter() - start) * 1000)


async def run_phase(
    cfg: ExperimentConfig,
    run_dir: Path,
    limit: int | None = None,
    dry_run: bool = False,
    progress_every: int = 25,
    log=sys.stderr,
) -> RunStats:
    stats = RunStats()

    questions = {
        q.question_id: q
        for q in load_questions(
            cfg.questions.path,
            limit=cfg.questions.limit,
            require_verified_negation=cfg.questions.require_verified_negation,
        )
    }
    cells = load_grid(run_dir / "grid.jsonl")
    resume = ResumeIndex.from_responses(run_dir)

    pending = [c for c in cells if not resume.is_done(c.cell_id)]
    stats.skipped_done = len(cells) - len(pending)
    stats.retry_after_error = sum(1 for c in pending if c.cell_id in resume.error_cells)

    pending = execution_order(pending, cfg.run.shuffle_seed)
    if limit is not None:
        pending = pending[:limit]
    stats.planned = len(pending)

    if dry_run:
        print(
            f"[dry-run] {len(cells)} cells, {stats.skipped_done} already ok, "
            f"{stats.planned} to call ({stats.retry_after_error} retries after error)",
            file=log,
        )
        return stats

    if not pending:
        print("nothing to do: every cell already has an ok row", file=log)
        return stats

    ledger = BudgetLedger(
        max_total_usd=cfg.budget.max_total_usd,
        phase="run",
        phase_cap_usd=cfg.budget.per_phase_usd.get("run"),
        estimate_headroom=cfg.budget.estimate_headroom,
        abort_on_exceed=cfg.budget.abort_on_exceed,
    )

    providers: dict[str, BaseProvider] = {}
    for pcfg in cfg.providers:
        if any(c.provider_id == pcfg.id for c in pending):
            providers[pcfg.id] = build_provider(pcfg)

    out_path = new_response_path(run_dir)
    stats.output_path = out_path

    queue: asyncio.Queue = asyncio.Queue()
    for cell in pending:
        queue.put_nowait(cell)

    abort = asyncio.Event()
    write_lock = asyncio.Lock()
    done_counter = {"n": 0}

    print(
        f"run: {stats.planned} cells across {len(providers)} providers -> {out_path.name} "
        f"(cap ${ledger.effective_cap:.2f})",
        file=log,
    )

    with JsonlWriter(out_path) as writer:

        async def emit(record: ResponseRecord) -> None:
            async with write_lock:
                writer.write(record)
            done_counter["n"] += 1
            if progress_every and done_counter["n"] % progress_every == 0:
                print(
                    f"  {done_counter['n']}/{stats.planned} done "
                    f"({stats.ok} ok, {stats.failed} failed, "
                    f"${ledger.committed_usd:.3f} spent)",
                    file=log,
                )

        async def handle(cell) -> None:
            provider = providers[cell.provider_id]
            pcfg = cfg.provider_by_id(cell.provider_id)
            question: Question = questions[cell.question_id]
            perspective = cfg.perspective_by_id(cell.perspective_id)
            epoch = resume.next_epoch(cell.cell_id)

            req = build_answer_request(
                cfg,
                question,
                cell.polarity,
                perspective,
                meta={
                    "cell_id": cell.cell_id,
                    "question_id": cell.question_id,
                    "polarity": cell.polarity,
                    "perspective_id": cell.perspective_id,
                    "provider_id": cell.provider_id,
                    "run_index": cell.run_index,
                    "attempt_epoch": epoch,
                },
            )
            payload = req.wire_payload()
            phash = prompt_hash(payload)

            est_in = estimate_input_tokens(req.system, *(m["content"] for m in req.messages))
            estimate = precall_estimate(
                est_in, req.max_tokens, pcfg.pricing, cfg.budget.estimate_headroom
            )

            reservation = await ledger.reserve(estimate)  # raises BudgetExceeded

            started = utcnow_iso()
            timer = _Timer()
            attempts = 1
            try:
                result, outcome = await with_retry(
                    lambda: timer.time(lambda: provider.complete(req)),
                    cfg.reliability,
                )
                attempts = outcome.attempts_used
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
                    ResponseRecord(
                        cell_id=cell.cell_id,
                        question_id=cell.question_id,
                        polarity=cell.polarity,
                        perspective_id=cell.perspective_id,
                        provider_id=cell.provider_id,
                        run_index=cell.run_index,
                        status="error",
                        attempt_epoch=epoch,
                        attempts_used=cfg.reliability.max_attempts if cls.retryable else 1,
                        prompt=PromptPayload(**payload),
                        prompt_hash=phash,
                        model_requested=pcfg.model,
                        latency_ms=timer.last_ms,
                        started_at=started,
                        finished_at=utcnow_iso(),
                        error=ErrorInfo(
                            type=key,
                            message=str(exc)[:2000],
                            http_status=cls.status,
                            retryable=cls.retryable,
                        ),
                        config_hash=cfg.config_hash,
                        code_version=code_version(),
                    )
                )
                return

            assert isinstance(result, CompletionResult)
            actual = cost_usd(result.input_tokens, result.output_tokens, pcfg.pricing)
            await ledger.commit(reservation, actual)
            stats.ok += 1
            stats.cost_usd += actual
            if result.finish_reason in {"max_tokens", "length", "MAX_TOKENS"}:
                stats.truncated += 1

            await emit(
                ResponseRecord(
                    cell_id=cell.cell_id,
                    question_id=cell.question_id,
                    polarity=cell.polarity,
                    perspective_id=cell.perspective_id,
                    provider_id=cell.provider_id,
                    run_index=cell.run_index,
                    status="ok",
                    attempt_epoch=epoch,
                    attempts_used=attempts,
                    prompt=PromptPayload(**payload),
                    prompt_hash=phash,
                    response_text=result.text,
                    finish_reason=result.finish_reason,
                    model_requested=pcfg.model,
                    model_reported=result.model_reported,
                    provider_request_id=result.provider_request_id,
                    usage=Usage(
                        input_tokens=result.input_tokens, output_tokens=result.output_tokens
                    ),
                    cost_usd_est=actual,
                    pricing_used=pcfg.pricing.model_dump(),
                    latency_ms=timer.last_ms,
                    started_at=started,
                    finished_at=utcnow_iso(),
                    config_hash=cfg.config_hash,
                        code_version=code_version(),
                )
            )

        async def worker() -> None:
            while not abort.is_set():
                try:
                    cell = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await handle(cell)
                except BudgetExceeded as exc:
                    if not abort.is_set():
                        stats.aborted_on_budget = True
                        print(f"\nABORT: {exc}", file=log)
                        abort.set()
                    return
                finally:
                    queue.task_done()

        n_workers = min(
            sum(p.max_concurrency for p in cfg.providers if p.id in providers) + 2,
            max(1, stats.planned),
        )
        tasks = [asyncio.create_task(worker()) for _ in range(n_workers)]
        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            abort.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print("\ninterrupted: partial results are on disk and resumable", file=log)
            raise
        finally:
            for provider in providers.values():
                try:
                    await provider.aclose()
                except Exception:  # noqa: BLE001 - shutdown must not mask results
                    pass

    stats.cost_usd = ledger.committed_usd
    write_manifest(
        run_dir,
        {
            "phase": "run",
            "finished_at": utcnow_iso(),
            "config_hash": cfg.config_hash,
            "code_version": code_version(),
            "config": cfg.semantic_dict(),
            "stats": stats.as_dict(),
            "budget": ledger.summary(),
        },
    )
    print(
        f"run complete: {stats.ok} ok, {stats.failed} failed, "
        f"${ledger.committed_usd:.4f} spent -> {out_path}",
        file=log,
    )
    if stats.failed:
        print(
            f"  {stats.failed} failed cells are recorded as error rows; "
            "re-run the same command to retry only those",
            file=log,
        )
    if stats.truncated:
        print(
            f"  {stats.truncated} responses hit the max_tokens ceiling "
            "(finish_reason=max_tokens) -- raise answer_prompt.max_tokens",
            file=log,
        )
    return stats
