#!/usr/bin/env python3
"""Descriptive and reliability statistics for an identity-cue run.

    python cue_stats.py cues-responses.jsonl cues-judgments.jsonl --out-dir analysis/cue-stats [--lenient]

Alongside analyze.py (means, intervals, judge matrix, self-preference) and
cue_model.py (mixed models), this writes report.md and a CSV per section:

  judge_agreement     each pair of judges on the same answers: Pearson and
                      Spearman on the total, Cohen's kappa on hard fails; and
                      Krippendorff's alpha (interval) for the whole panel, per
                      criterion
  criteria            Spearman correlations between the four criteria and the
                      total, grade by grade
  length              answer length in words against the total, per judge and
                      per answering model, raw and within question (both
                      centred on the question's mean), as a check on length bias
  by_group            per cue group against the baseline: panel score, words,
                      share of answers that address the asker, hard-fail share
  model_correlation   each pair of answering models: correlation of their
                      per-question panel scores, i.e. whether they find the
                      same questions hard
  test_retest         the baseline's three replicates, pair by pair, across
                      every question and model: how far a score repeats
  gap_by_question     the education gap (no high school - doctorate) and race
                      gap (Black - White) on each question: spread, how often
                      negative, correlation with the question's baseline score,
                      and between answering models

The panel score of an answer is the mean of its usable grades. Question-level
correlations carry Fisher intervals over questions; grade-level ones carry n
only, since their intervals are trivially narrow and the grades are clustered.
--lenient keeps grades whose only fault is a stray premise score, as
analyze.py --ignore-stray-premise.
"""

import argparse
import json
import math
import re
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
RUNNER_INVALID = "Empty answer or invalid rubric result; raw output retained."
# words that show the answer was tailored to the stated asker, as cue_report.py
ADDRESSED = re.compile(r"\b(you|your|as an? (black|white|african american|caucasian)|"
                       r"hbcu|historically black)\b", re.I)


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def usable(g, lenient):
    error = g.get("error")
    if error is not None and not (lenient and error == RUNNER_INVALID):
        return False
    if any(type(g.get(k)) is not int or not 1 <= g[k] <= 5 for k in CRITERIA):
        return False
    if g.get("total") != sum(g[k] for k in CRITERIA) or type(g.get("hard_fail")) is not bool:
        return False
    premise = g.get("premise_handling")
    if str(g.get("question_type", "")).startswith("Loaded"):
        return type(premise) is int and 1 <= premise <= 5
    if premise is None:
        return error is None
    return lenient


def load(responses, judgments, lenient):
    answers = {}
    for a in responses:
        text = a.get("response") or ""
        if a.get("error") is None and text.strip():
            answers[a["id"]] = {
                "id": a["id"], "qid": a["qid"], "provider": a["provider"], "run": a.get("run", 0),
                "question_type": a.get("question_type"), "group": a.get("group") or "baseline",
                "block": a.get("block") or "baseline", "words": len(text.split()),
                "addressed": bool(ADDRESSED.search(text))}
    best = {}
    for g in judgments:
        key = (g["id"], g["judge"], g.get("pass", 0))
        rank = (usable(g, lenient), g.get("ts") or "")
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, g)
    grades = pd.DataFrame([{"id": g["id"], "judge": g["judge"], "hard_fail": int(g["hard_fail"]),
                            "total": g["total"], **{k: g[k] for k in CRITERIA}}
                           for (ok, _), g in best.values() if ok and g["id"] in answers])
    ans = pd.DataFrame(answers.values()).set_index("id")
    panel = grades.groupby("id").agg(score=("total", "mean"), hard_fail=("hard_fail", "mean"))
    ans = ans.join(panel, how="inner")
    grades = grades.join(ans[["qid", "provider", "words", "group"]], on="id")
    return ans, grades


def fisher(r, n):
    if n < 4 or r is None or not np.isfinite(r) or abs(r) >= 1:
        return (None, None)
    z, se = math.atanh(r), 1 / math.sqrt(n - 3)
    return (math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se))


def wilson(k, n):
    if n == 0:
        return (None, None)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def kappa(a, b):
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    po = (a == b).mean()
    pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
    return (po - pe) / (1 - pe) if pe < 1 else None


def alpha_interval(grades, value):
    """Krippendorff's alpha, interval metric, missing grades allowed."""
    m = grades.groupby("id")[value].transform("size")
    v = grades.loc[m >= 2, value].astype(float)
    ids = grades.loc[m >= 2, "id"]
    n = len(v)
    if n < 2:
        return None
    # sum over answers of 2 m SS / (m - 1), taken grade by grade
    size = v.groupby(ids).transform("size")
    dev2 = (v - v.groupby(ids).transform("mean")) ** 2
    within = (2 * size * dev2 / (size - 1)).sum() / n
    expected = 2 * ((v - v.mean()) ** 2).sum() / (n - 1)
    return 1 - within / expected if expected else None


def judge_agreement(grades):
    wide = grades.pivot_table(index="id", columns="judge", values="total")
    hf = grades.pivot_table(index="id", columns="judge", values="hard_fail", aggfunc="max")
    rows = []
    for a, b in combinations(sorted(wide.columns), 2):
        both = wide[[a, b]].dropna()
        hb = hf[[a, b]].dropna()
        rows.append({"judge_a": a, "judge_b": b, "answers": len(both),
                     "pearson": both[a].corr(both[b]), "spearman": both[a].corr(both[b], method="spearman"),
                     "mean_difference": (both[a] - both[b]).mean(),
                     "hard_fail_kappa": kappa(hb[a], hb[b]) if len(hb) else None})
    alphas = [{"measure": k, "krippendorff_alpha": alpha_interval(grades, k)} for k in ("total", *CRITERIA)]
    return pd.DataFrame(rows), pd.DataFrame(alphas)


def length(grades):
    g = grades.copy()
    g["log_words"] = np.log(g["words"].clip(lower=1))
    g["total_c"] = g["total"] - g.groupby("qid")["total"].transform("mean")
    g["log_words_c"] = g["log_words"] - g.groupby("qid")["log_words"].transform("mean")
    rows = []
    for by in ("judge", "provider"):
        for level, part in [("all", g)] + list(g.groupby(by)):
            if by == "provider" and level == "all":
                continue
            rows.append({"by": by, "level": level, "grades": len(part),
                         "spearman_words_total": part["words"].corr(part["total"], method="spearman"),
                         "pearson_within_question": part["log_words_c"].corr(part["total_c"])})
    return pd.DataFrame(rows)


def by_group(ans):
    base = ans[ans["group"] == "baseline"]
    rows = []
    for group, part in ans.groupby("group"):
        lo, hi = wilson(int((part["hard_fail"] >= 0.5).sum()), len(part))
        rows.append({"group": group, "answers": len(part), "score": part["score"].mean(),
                     "score_minus_baseline": part["score"].mean() - base["score"].mean(),
                     "words": part["words"].mean(), "words_minus_baseline": part["words"].mean() - base["words"].mean(),
                     "addresses_asker": part["addressed"].mean(),
                     "majority_hard_fail": (part["hard_fail"] >= 0.5).mean(),
                     "hard_fail_ci_low": lo, "hard_fail_ci_high": hi})
    return pd.DataFrame(rows).sort_values("score_minus_baseline")


def model_correlation(ans):
    per_q = ans.pivot_table(index="qid", columns="provider", values="score")
    rows = []
    for a, b in combinations(sorted(per_q.columns), 2):
        both = per_q[[a, b]].dropna()
        r = both[a].corr(both[b]) if len(both) > 2 else None
        lo, hi = fisher(r, len(both))
        rows.append({"model_a": a, "model_b": b, "questions": len(both), "pearson": r,
                     "ci_low": lo, "ci_high": hi,
                     "spearman": both[a].corr(both[b], method="spearman") if len(both) > 2 else None})
    return pd.DataFrame(rows)


def test_retest(ans):
    base = ans[ans["group"] == "baseline"].pivot_table(index=["qid", "provider"], columns="run", values="score")
    rows = []
    for a, b in combinations(sorted(base.columns), 2):
        both = base[[a, b]].dropna()
        r = both[a].corr(both[b]) if len(both) > 2 else None
        lo, hi = fisher(r, len(both))
        rows.append({"run_a": a, "run_b": b, "question_model_pairs": len(both), "pearson": r,
                     "ci_low": lo, "ci_high": hi, "mean_abs_difference": (both[a] - both[b]).abs().mean()})
    return pd.DataFrame(rows)


GAPS = {"education": ("did not finish high school", "doctorate"),
        "race": (("Black woman", "Black man"), ("White woman", "White man"))}


def gaps(ans):
    base = ans[ans["group"] == "baseline"].groupby("qid")["score"].mean()
    rows, per_model = [], {}
    for name, (lo_groups, hi_groups) in GAPS.items():
        lo_groups = lo_groups if isinstance(lo_groups, tuple) else (lo_groups,)
        hi_groups = hi_groups if isinstance(hi_groups, tuple) else (hi_groups,)
        lo = ans[ans["group"].isin(lo_groups)].groupby(["qid", "provider"])["score"].mean()
        hi = ans[ans["group"].isin(hi_groups)].groupby(["qid", "provider"])["score"].mean()
        gap = (lo - hi).dropna()
        per_model[name] = gap.unstack("provider")
        q = gap.groupby("qid").mean()
        joined = pd.concat([q, base], axis=1, join="inner")
        r = joined.iloc[:, 0].corr(joined.iloc[:, 1]) if len(joined) > 2 else None
        ci = fisher(r, len(joined))
        rows.append({"gap": name, "questions": len(q), "mean": q.mean(), "sd": q.std(),
                     "share_negative": (q < 0).mean(), "min": q.min(), "max": q.max(),
                     "corr_with_baseline_score": r, "ci_low": ci[0], "ci_high": ci[1]})
    pairs = []
    for name, wide in per_model.items():
        for a, b in combinations(sorted(wide.columns), 2):
            both = wide[[a, b]].dropna()
            r = both[a].corr(both[b]) if len(both) > 2 else None
            lo, hi = fisher(r, len(both))
            pairs.append({"gap": name, "model_a": a, "model_b": b, "questions": len(both),
                          "pearson": r, "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows), pd.DataFrame(pairs)


def md(df, title):
    def cell(x):
        if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
            return ""
        return f"{x:.3f}" if isinstance(x, (float, np.floating)) else x
    fmt = df.map(cell) if hasattr(df, "map") else df.applymap(cell)
    head = "| " + " | ".join(fmt.columns) + " |\n|" + "---|" * len(fmt.columns) + "\n"
    body = "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in fmt.itertuples(index=False))
    return f"## {title}\n\n{head}{body}\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("responses", type=Path)
    ap.add_argument("judgments", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--lenient", action="store_true")
    args = ap.parse_args()
    ans, grades = load(read(args.responses), read(args.judgments), args.lenient)
    if ans.empty:
        raise SystemExit("no usable grades")
    pairs, alphas = judge_agreement(grades)
    crit = grades[list(CRITERIA) + ["total"]].corr(method="spearman").reset_index(names="criterion")
    gap_summary, gap_pairs = gaps(ans)
    tables = {"judge_agreement": pairs, "panel_alpha": alphas, "criteria": crit,
              "length": length(grades), "by_group": by_group(ans),
              "model_correlation": model_correlation(ans), "test_retest": test_retest(ans),
              "gap_by_question": gap_summary, "gap_between_models": gap_pairs}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rule = "lenient" if args.lenient else "strict"
    report = (f"# Cue run statistics ({rule} premise rule)\n\n{len(grades)} grades of {len(ans)} answers, "
              f"{ans['qid'].nunique()} questions, {grades['judge'].nunique()} judges.\n\n")
    for name, table in tables.items():
        table.to_csv(args.out_dir / f"{name}.csv", index=False)
        report += md(table, name.replace("_", " "))
    (args.out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
