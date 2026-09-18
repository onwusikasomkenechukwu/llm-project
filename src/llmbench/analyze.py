"""Phase 4: tidy frame and aggregates.

One statistical point drives the whole module: the same questions recur in every
cell, so rows are not independent. Every confidence interval here is bootstrapped
by resampling QUESTIONS, not rows. Resampling rows would produce intervals that
are far too narrow and would make trivial differences look significant.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import ExperimentConfig
from .storage import iter_jsonl_dir

TIDY_COLUMNS = [
    "judgment_id",
    "cell_id",
    "question_id",
    "polarity",
    "perspective_id",
    "provider_id",
    "run_index",
    "agreement_score",
    "refusal",
    "non_responsive",
    "justification_quality",
    "judge_provider_id",
    "judge_model_requested",
    "judge_run_index",
    "rubric_version",
    "parse_ok",
]


def load_tidy(run_dir: Path) -> pd.DataFrame:
    """One row per judgment, with every grid coordinate as a column."""
    judgments: list[dict[str, Any]] = []
    for row in iter_jsonl_dir(run_dir / "judgments"):
        parsed = row.get("parsed") or {}
        judgments.append(
            {
                "judgment_id": row.get("judgment_id"),
                "cell_id": row.get("cell_id"),
                "question_id": row.get("question_id"),
                "polarity": row.get("polarity"),
                "perspective_id": row.get("perspective_id"),
                "provider_id": row.get("provider_id"),
                "run_index": row.get("run_index"),
                "agreement_score": parsed.get("agreement_score"),
                # Coerced at construction: a parse-failed row has no parsed
                # object, and a None here would make the column object dtype.
                "refusal": bool(parsed.get("refusal", False)),
                "non_responsive": bool(parsed.get("non_responsive", False)),
                "justification_quality": parsed.get("justification_quality"),
                "rationale": parsed.get("rationale"),
                "judge_provider_id": row.get("judge_provider_id"),
                "judge_model_requested": row.get("judge_model_requested"),
                "judge_run_index": row.get("judge_run_index"),
                "rubric_version": row.get("rubric_version"),
                "parse_ok": bool(row.get("parse_ok")),
                "judge_cost_usd": row.get("cost_usd_est", 0.0),
                "judge_latency_ms": row.get("latency_ms", 0),
            }
        )
    if not judgments:
        raise FileNotFoundError(
            f"no judgments under {run_dir / 'judgments'}. Run `llmbench judge` first."
        )
    jdf = pd.DataFrame(judgments)

    # A re-judge appends a new row rather than rewriting the old one, so the
    # same judgment_id can appear in several files. Files are read in
    # chronological order, so the last row is the current state of that
    # judgment; keeping the earlier ones would double-count re-judged cells.
    jdf = jdf.drop_duplicates(subset="judgment_id", keep="last")

    responses: list[dict[str, Any]] = []
    for row in iter_jsonl_dir(run_dir / "responses"):
        if row.get("status") != "ok":
            continue
        usage = row.get("usage") or {}
        responses.append(
            {
                "cell_id": row.get("cell_id"),
                "model_reported": row.get("model_reported"),
                "finish_reason": row.get("finish_reason"),
                "attempts_used": row.get("attempts_used", 1),
                "latency_ms": row.get("latency_ms", 0),
                "cost_usd_est": row.get("cost_usd_est", 0.0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "response_chars": len(row.get("response_text") or ""),
            }
        )
    rdf = pd.DataFrame(responses).drop_duplicates(subset="cell_id", keep="last")

    tidy = jdf.merge(rdf, on="cell_id", how="left")
    tidy["truncated"] = tidy["finish_reason"].isin(["max_tokens", "length", "MAX_TOKENS"])
    return tidy


def _scored(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that carry a usable score: parsed, and an actual position taken."""
    return df[
        df["parse_ok"]
        & df["agreement_score"].notna()
        & ~df["refusal"]
        & ~df["non_responsive"]
    ]


def cluster_bootstrap_ci(
    df: pd.DataFrame,
    value_col: str,
    cluster_col: str = "question_id",
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile CI, resampling whole clusters.

    Returns (nan, nan) rather than a fake interval when there is too little data.
    """
    if df.empty or df[value_col].isna().all():
        return (float("nan"), float("nan"))
    groups = [g[value_col].to_numpy(dtype=float) for _, g in df.groupby(cluster_col, sort=False)]
    groups = [g[~np.isnan(g)] for g in groups]
    groups = [g for g in groups if g.size]
    if len(groups) < 2:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(seed)
    n = len(groups)
    means = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        pick = rng.integers(0, n, size=n)
        sample = np.concatenate([groups[i] for i in pick])
        means[b] = sample.mean()
    return (
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def score_by_provider(tidy: pd.DataFrame, n_boot: int = 2000) -> pd.DataFrame:
    rows = []
    for provider, g in tidy.groupby("provider_id", sort=True):
        s = _scored(g)
        lo, hi = cluster_bootstrap_ci(s, "agreement_score", n_boot=n_boot)
        rows.append(
            {
                "provider_id": provider,
                "n_judgments": len(g),
                "n_scored": len(s),
                "mean_agreement": s["agreement_score"].mean() if len(s) else float("nan"),
                "ci_lo": lo,
                "ci_hi": hi,
                "sd_agreement": s["agreement_score"].std(ddof=1) if len(s) > 1 else float("nan"),
                "refusal_rate": g["refusal"].mean(),
                "non_responsive_rate": g["non_responsive"].mean(),
                "parse_fail_rate": (~g["parse_ok"]).mean(),
                "truncation_rate": g["truncated"].fillna(False).astype(bool).mean(),
                "mean_justification_quality": g["justification_quality"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("provider_id").reset_index(drop=True)


def score_by_perspective(tidy: pd.DataFrame, n_boot: int = 2000) -> pd.DataFrame:
    rows = []
    for (provider, perspective), g in tidy.groupby(["provider_id", "perspective_id"], sort=True):
        s = _scored(g)
        lo, hi = cluster_bootstrap_ci(s, "agreement_score", n_boot=n_boot)
        rows.append(
            {
                "provider_id": provider,
                "perspective_id": perspective,
                "n_judgments": len(g),
                "n_scored": len(s),
                "mean_agreement": s["agreement_score"].mean() if len(s) else float("nan"),
                "ci_lo": lo,
                "ci_hi": hi,
                "refusal_rate": g["refusal"].mean(),
                "non_responsive_rate": g["non_responsive"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values(["provider_id", "perspective_id"]).reset_index(drop=True)


def perspective_spread(by_perspective: pd.DataFrame) -> pd.DataFrame:
    """How much the stated perspective moves a given provider."""
    rows = []
    for provider, g in by_perspective.groupby("provider_id", sort=True):
        means = g["mean_agreement"].dropna()
        hi_row = g.loc[g["mean_agreement"].idxmax()] if len(means) else None
        lo_row = g.loc[g["mean_agreement"].idxmin()] if len(means) else None
        rows.append(
            {
                "provider_id": provider,
                "n_perspectives": len(means),
                "mean_of_perspective_means": means.mean() if len(means) else float("nan"),
                "range": (means.max() - means.min()) if len(means) else float("nan"),
                "sd_across_perspectives": means.std(ddof=1) if len(means) > 1 else float("nan"),
                "max_perspective": hi_row["perspective_id"] if hi_row is not None else None,
                "min_perspective": lo_row["perspective_id"] if lo_row is not None else None,
                "refusal_rate_range": (
                    g["refusal_rate"].max() - g["refusal_rate"].min() if len(g) else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows).reset_index(drop=True)


def consistency(tidy: pd.DataFrame, n_boot: int = 2000) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agreement between a claim and its negation.

    Pairs are matched on run_index, so each of the D duplicates contributes one
    independent pair and the replicate structure survives into the variance
    analysis. A consistent model scores s on the claim and -s on its negation,
    so |s_pos + s_neg| is 0 when consistent and up to 4 when it agrees with both.

    The indeterminate rate is reported alongside, and is not optional: a model
    that refuses everything would otherwise post perfect consistency on an
    almost empty denominator.
    """
    keys = ["question_id", "perspective_id", "provider_id", "run_index"]
    df = tidy[tidy["parse_ok"]].copy()
    df["determinate"] = ~(df["refusal"] | df["non_responsive"]) & df["agreement_score"].notna()

    wide = df.pivot_table(
        index=keys,
        columns="polarity",
        values=["agreement_score", "determinate"],
        aggfunc="first",
    )
    if ("agreement_score", "pos") not in wide.columns or (
        "agreement_score",
        "neg",
    ) not in wide.columns:
        empty = pd.DataFrame()
        return empty, empty

    pairs = pd.DataFrame(
        {
            "s_pos": wide[("agreement_score", "pos")],
            "s_neg": wide[("agreement_score", "neg")],
            "det_pos": wide[("determinate", "pos")].fillna(False).astype(bool),
            "det_neg": wide[("determinate", "neg")].fillna(False).astype(bool),
        }
    ).reset_index()
    pairs["both_determinate"] = pairs["det_pos"] & pairs["det_neg"]
    pairs["inconsistency"] = (pairs["s_pos"] + pairs["s_neg"]).abs()
    pairs.loc[~pairs["both_determinate"], "inconsistency"] = np.nan
    pairs["fully_consistent"] = pairs["inconsistency"] == 0

    rows = []
    for provider, g in pairs.groupby("provider_id", sort=True):
        det = g[g["both_determinate"]]
        lo, hi = cluster_bootstrap_ci(det, "inconsistency", n_boot=n_boot)
        rows.append(
            {
                "provider_id": provider,
                "n_pairs": len(g),
                "n_determinate_pairs": len(det),
                "indeterminate_rate": 1.0 - (len(det) / len(g)) if len(g) else float("nan"),
                "mean_inconsistency": det["inconsistency"].mean() if len(det) else float("nan"),
                "ci_lo": lo,
                "ci_hi": hi,
                "fully_consistent_rate": (
                    det["fully_consistent"].mean() if len(det) else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows).reset_index(drop=True), pairs


def run_variance(tidy: pd.DataFrame) -> pd.DataFrame:
    """Run-to-run variance across the D duplicates of an identical cell."""
    keys = ["question_id", "polarity", "perspective_id", "provider_id"]
    s = _scored(tidy)
    if s.empty:
        return pd.DataFrame()
    grouped = s.groupby(keys)["agreement_score"]
    per_cell = pd.DataFrame(
        {
            "sd": grouped.std(ddof=1),
            "n_runs": grouped.count(),
            "range": grouped.max() - grouped.min(),
        }
    ).reset_index()
    per_cell = per_cell[per_cell["n_runs"] >= 2]
    if per_cell.empty:
        return pd.DataFrame()

    rows = []
    for provider, g in per_cell.groupby("provider_id", sort=True):
        rows.append(
            {
                "provider_id": provider,
                "n_cells_with_replicates": len(g),
                "mean_within_cell_sd": g["sd"].mean(),
                "median_within_cell_sd": g["sd"].median(),
                "mean_within_cell_range": g["range"].mean(),
                "pct_cells_identical_across_runs": float((g["sd"] == 0).mean()),
            }
        )
    return pd.DataFrame(rows).reset_index(drop=True)


def cost_latency(tidy: pd.DataFrame) -> pd.DataFrame:
    """Operational telemetry.

    Latency here is wall clock under whatever concurrency the run used, so it is
    not comparable across runs and is not a research variable. Cost is.
    """
    per_cell = tidy.drop_duplicates(subset="cell_id", keep="first")
    rows = []
    for provider, g in per_cell.groupby("provider_id", sort=True):
        rows.append(
            {
                "provider_id": provider,
                "n_calls": len(g),
                "total_cost_usd": g["cost_usd_est"].sum(),
                "mean_cost_usd": g["cost_usd_est"].mean(),
                "total_input_tokens": g["input_tokens"].sum(),
                "total_output_tokens": g["output_tokens"].sum(),
                "mean_output_tokens": g["output_tokens"].mean(),
                "p50_latency_ms": g["latency_ms"].quantile(0.5),
                "p95_latency_ms": g["latency_ms"].quantile(0.95),
                "mean_attempts": g["attempts_used"].mean(),
                "truncation_rate": g["truncated"].fillna(False).astype(bool).mean(),
            }
        )
    out = pd.DataFrame(rows).reset_index(drop=True)
    judge_total = tidy.drop_duplicates(subset="judgment_id")["judge_cost_usd"].sum()
    out.attrs["judge_total_cost_usd"] = float(judge_total)
    return out


def analyze_phase(
    cfg: ExperimentConfig,
    run_dir: Path,
    n_boot: int = 2000,
    log=sys.stderr,
) -> dict[str, pd.DataFrame]:
    tidy = load_tidy(run_dir)
    out_dir = run_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    by_provider = score_by_provider(tidy, n_boot=n_boot)
    by_perspective = score_by_perspective(tidy, n_boot=n_boot)
    spread = perspective_spread(by_perspective)
    cons, pairs = consistency(tidy, n_boot=n_boot)
    variance = run_variance(tidy)
    costs = cost_latency(tidy)

    tables = {
        "tidy": tidy,
        "score_by_provider": by_provider,
        "score_by_perspective": by_perspective,
        "perspective_spread": spread,
        "consistency": cons,
        "consistency_pairs": pairs,
        "run_variance": variance,
        "cost_latency": costs,
    }

    try:
        tidy.to_parquet(out_dir / "tidy.parquet", index=False)
    except Exception as exc:  # noqa: BLE001 - pyarrow is an optional extra
        print(f"  (parquet unavailable, CSV only: {exc})", file=log)
    for name, df in tables.items():
        if df is not None and not df.empty:
            df.to_csv(out_dir / f"{name}.csv", index=False)

    print(f"analysis written to {out_dir}", file=log)
    print(f"  {len(tidy)} judgments, {tidy['cell_id'].nunique()} cells", file=log)
    if not by_provider.empty:
        print("\nscore by provider (mean agreement, -2..+2):", file=log)
        print(
            by_provider[
                ["provider_id", "n_scored", "mean_agreement", "ci_lo", "ci_hi", "refusal_rate"]
            ].to_string(index=False),
            file=log,
        )
    if not spread.empty:
        print("\nperspective spread per provider:", file=log)
        print(
            spread[
                ["provider_id", "range", "sd_across_perspectives", "max_perspective",
                 "min_perspective"]
            ].to_string(index=False),
            file=log,
        )
    if not cons.empty:
        print("\nclaim/negation consistency (0 = perfect, 4 = agrees with both):", file=log)
        print(
            cons[
                ["provider_id", "n_determinate_pairs", "indeterminate_rate",
                 "mean_inconsistency", "fully_consistent_rate"]
            ].to_string(index=False),
            file=log,
        )
    if not variance.empty:
        print("\nrun-to-run variance across duplicates:", file=log)
        print(
            variance[
                ["provider_id", "mean_within_cell_sd", "pct_cells_identical_across_runs"]
            ].to_string(index=False),
            file=log,
        )
    if not costs.empty:
        print("\ncost and latency per provider:", file=log)
        print(
            costs[
                ["provider_id", "n_calls", "total_cost_usd", "p50_latency_ms", "p95_latency_ms"]
            ].to_string(index=False),
            file=log,
        )
        print(
            f"\njudge cost: ${costs.attrs.get('judge_total_cost_usd', 0.0):.4f}",
            file=log,
        )
    return tables
