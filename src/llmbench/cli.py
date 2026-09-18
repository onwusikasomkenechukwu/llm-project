"""Command line: generate-grid | run | judge | analyze, each runnable alone."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from . import __version__
from .analyze import analyze_phase
from .config import ExperimentConfig, load_config
from .grid import build_grid, write_grid
from .judge import judge_phase
from .questions import load_questions
from .runner import run_phase
from .storage import write_manifest
from .records import utcnow_iso


def _resolve(args) -> tuple[ExperimentConfig, Path]:
    cfg = load_config(args.config)
    run_dir = cfg.run_dir(getattr(args, "output_root", None))
    return cfg, run_dir


def cmd_validate(args) -> int:
    cfg, run_dir = _resolve(args)
    questions = load_questions(
        cfg.questions.path,
        limit=cfg.questions.limit,
        require_verified_negation=cfg.questions.require_verified_negation,
    )
    total = len(questions) * cfg.cells_per_question()
    print(f"config OK          {args.config}")
    print(f"config_hash        {cfg.config_hash}")
    print(f"run dir            {run_dir}")
    print(f"questions          {len(questions)}")
    print(
        f"grid               {len(questions)} x {len(cfg.questions.polarities)} polarities "
        f"x {len(cfg.perspectives)} perspectives x {len(cfg.providers)} providers "
        f"x {cfg.run.duplicates} duplicates"
    )
    print(f"total cells        {total:,}")
    print(f"generation + judge {total * 2:,} API calls")
    print(f"spend cap          ${cfg.budget.max_total_usd:.2f}")
    for phase, cap in cfg.budget.per_phase_usd.items():
        print(f"  {phase:<16} ${cap:.2f}")

    warnings: list[str] = []
    for p in list(cfg.providers) + [cfg.judge.provider]:
        if "REPLACE" in p.model.upper():
            warnings.append(f"provider {p.id}: model is still a placeholder ({p.model})")
        if p.pricing.input_per_mtok == 0 and p.pricing.output_per_mtok == 0:
            warnings.append(
                f"provider {p.id}: pricing is zero, so cost estimates and the spend "
                "cap are meaningless for it"
            )
        if p.adapter != "mock":
            if not p.api_key_env:
                warnings.append(f"provider {p.id}: no api_key_env set")
            elif not os.environ.get(p.api_key_env):
                warnings.append(f"provider {p.id}: ${p.api_key_env} is unset in this shell")
    if not any(q.human_verified for q in questions):
        warnings.append("no question has human_verified=true")

    if warnings:
        print("\nwarnings:")
        for w in warnings:
            print(f"  ! {w}")
        print("\nfix these before a paid run.")
    return 0


def cmd_generate_grid(args) -> int:
    cfg, run_dir = _resolve(args)
    questions = load_questions(
        cfg.questions.path,
        limit=cfg.questions.limit,
        require_verified_negation=cfg.questions.require_verified_negation,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "grid.jsonl"
    count = write_grid(path, build_grid(cfg, questions))
    write_manifest(
        run_dir,
        {
            "phase": "generate-grid",
            "finished_at": utcnow_iso(),
            "config_hash": cfg.config_hash,
            "config": cfg.semantic_dict(),
            "questions": len(questions),
            "cells": count,
        },
    )
    print(f"wrote {count:,} cells to {path}")
    print(f"config_hash {cfg.config_hash}")
    return 0


def cmd_run(args) -> int:
    cfg, run_dir = _resolve(args)
    stats = asyncio.run(
        run_phase(cfg, run_dir, limit=args.limit, dry_run=args.dry_run)
    )
    return 2 if stats.aborted_on_budget else 0


def cmd_judge(args) -> int:
    cfg, run_dir = _resolve(args)
    stats = asyncio.run(
        judge_phase(cfg, run_dir, limit=args.limit, dry_run=args.dry_run)
    )
    return 2 if stats.aborted_on_budget else 0


def cmd_analyze(args) -> int:
    cfg, run_dir = _resolve(args)
    analyze_phase(cfg, run_dir, n_boot=args.bootstrap)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmbench",
        description="LLM agreement benchmarking harness (AI4PC Lab)",
    )
    parser.add_argument("--version", action="version", version=f"llmbench {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("-c", "--config", default="configs/experiment.yaml")
        p.add_argument(
            "--output-root",
            default=None,
            help="override run.output_root from the config",
        )
        return p

    common(sub.add_parser("validate", help="check config and questions, print grid size")).set_defaults(
        func=cmd_validate
    )
    common(
        sub.add_parser("generate-grid", help="phase 1: write the full cell list to disk")
    ).set_defaults(func=cmd_generate_grid)

    p_run = common(sub.add_parser("run", help="phase 2: call models, append raw responses"))
    p_run.add_argument("--limit", type=int, default=None, help="cap cells this invocation")
    p_run.add_argument("--dry-run", action="store_true", help="report what would be called")
    p_run.set_defaults(func=cmd_run)

    p_judge = common(sub.add_parser("judge", help="phase 3: score stored responses"))
    p_judge.add_argument("--limit", type=int, default=None)
    p_judge.add_argument("--dry-run", action="store_true")
    p_judge.set_defaults(func=cmd_judge)

    p_an = common(sub.add_parser("analyze", help="phase 4: tidy frame and aggregates"))
    p_an.add_argument("--bootstrap", type=int, default=2000, help="bootstrap resamples")
    p_an.set_defaults(func=cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
