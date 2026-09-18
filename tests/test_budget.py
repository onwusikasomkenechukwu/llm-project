"""Spend cap: reserved at dispatch so concurrency cannot overshoot it."""

from __future__ import annotations

import asyncio

import pytest

from llmbench.budget import BudgetExceeded, BudgetLedger
from llmbench.config import ExperimentConfig
from llmbench.grid import build_grid, write_grid
from llmbench.pricing import cost_usd, estimate_input_tokens, precall_estimate
from llmbench.config import PricingCfg
from llmbench.questions import load_questions
from llmbench.runner import run_phase
from llmbench.storage import iter_jsonl_dir

from .conftest import make_config_dict


async def test_reserve_then_commit_tracks_actual_spend():
    ledger = BudgetLedger(max_total_usd=1.0)
    r = await ledger.reserve(0.10)
    assert ledger.reserved_usd == pytest.approx(0.10)
    await ledger.commit(r, 0.04)
    assert ledger.reserved_usd == pytest.approx(0.0)
    assert ledger.committed_usd == pytest.approx(0.04)
    assert ledger.calls_committed == 1


async def test_release_returns_an_unspent_reservation():
    ledger = BudgetLedger(max_total_usd=1.0)
    r = await ledger.reserve(0.25)
    await ledger.release(r)
    assert ledger.reserved_usd == pytest.approx(0.0)
    assert ledger.committed_usd == pytest.approx(0.0)


async def test_cap_blocks_the_call_that_would_breach_it():
    ledger = BudgetLedger(max_total_usd=1.0)
    r = await ledger.reserve(0.9)
    await ledger.commit(r, 0.9)
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(0.2)


async def test_in_flight_reservations_count_against_the_cap():
    """The point of reserving at dispatch: C concurrent calls cannot all sail past."""
    ledger = BudgetLedger(max_total_usd=1.0)
    held = [await ledger.reserve(0.3) for _ in range(3)]
    assert ledger.outstanding == pytest.approx(0.9)
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(0.3)
    await ledger.release(held[0])
    await ledger.reserve(0.3)  # now there is room


async def test_concurrent_reservations_never_exceed_the_cap():
    ledger = BudgetLedger(max_total_usd=1.0)
    granted = 0

    async def grab():
        nonlocal granted
        try:
            await ledger.reserve(0.1)
            granted += 1
        except BudgetExceeded:
            pass

    await asyncio.gather(*[grab() for _ in range(50)])
    assert granted == 10
    assert ledger.outstanding <= 1.0 + 1e-9


async def test_phase_cap_binds_below_the_total():
    ledger = BudgetLedger(max_total_usd=100.0, phase="judge", phase_cap_usd=0.5)
    assert ledger.effective_cap == pytest.approx(0.5)
    r = await ledger.reserve(0.4)
    await ledger.commit(r, 0.4)
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(0.2)


async def test_double_commit_is_an_error():
    ledger = BudgetLedger(max_total_usd=1.0)
    r = await ledger.reserve(0.1)
    await ledger.commit(r, 0.1)
    with pytest.raises(RuntimeError):
        await ledger.commit(r, 0.1)


def test_precall_estimate_assumes_full_output_and_applies_headroom():
    pricing = PricingCfg(input_per_mtok=10.0, output_per_mtok=100.0)
    exact = cost_usd(1000, 500, pricing)
    est = precall_estimate(1000, 500, pricing, headroom=1.2)
    assert est == pytest.approx(exact * 1.2)
    assert est > exact, "the reservation must be conservative"


def test_input_token_estimate_scales_with_text():
    assert estimate_input_tokens("x" * 360) > estimate_input_tokens("x" * 36)
    assert estimate_input_tokens(None, "") >= 1


# -- integration ------------------------------------------------------------


async def test_run_aborts_cleanly_when_the_cap_is_hit(tmp_path, questions_file):
    """An abort must keep what it already wrote and stay resumable."""
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", max_total_usd=0.02)
    )
    run_dir = cfg.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_grid(run_dir / "grid.jsonl", build_grid(cfg, load_questions(cfg.questions.path)))

    stats = await run_phase(cfg, run_dir, progress_every=0)

    assert stats.aborted_on_budget
    assert stats.ok < stats.planned, "the cap should have stopped the run early"
    rows = list(iter_jsonl_dir(run_dir / "responses"))
    assert len(rows) == stats.ok, "rows written before the abort must survive"
    assert stats.cost_usd <= cfg.budget.max_total_usd
