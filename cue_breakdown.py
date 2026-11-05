#!/usr/bin/env python3
"""Cue effects by question type, and question by question.

    python cue_breakdown.py responses.jsonl judgments.jsonl --prompts prompts.xlsx --out-dir analysis/breakdown [--lenient]

Each comparison is a focal set of cue groups against a comparison set: every
group against the templated baseline, and the pooled contrasts (Black - White,
woman - man, no high school - doctorate). Within a question it is taken model by
model, then averaged over models, on the total out of 20 and each of the four
criteria.

  by_type.csv        each question type's mean scores, all answers
  type_gaps.csv      each comparison within each question type, with a 95%
                     interval over questions, and a permutation test of whether
                     the gap differs between types (the cue x type interaction)
  question_gaps.csv  each comparison on each question, with a t-test on the
                     answers (stratified by model, variance pooled over cue groups) and Benjamini-Hochberg
                     q across the questions, per comparison and measure
  report.md          the tables, and the questions with q < 0.05

An answer's score is the mean of its usable grades. Questions weigh equally.
--lenient keeps grades whose only fault is a stray premise score, as cue_stats.py.
Pure Python, so it runs on the laptop.
"""

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import fmean, stdev

import openpyxl

CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
MEASURES = ("total", *CRITERIA)
RUNNER_INVALID = "Empty answer or invalid rubric result; raw output retained."
TYPES = ("Factual", "Directed", "Loaded (False Premise)", "Loaded (True Premise)", "Open-Ended")
PERMUTATIONS = 2000

# pooled contrasts for the 15 October cue sheet; ones whose groups are missing are skipped
CONTRASTS = {
    "Black - White": (("Black man", "Black woman"), ("White man", "White woman")),
    "woman - man": (("Black woman", "White woman"), ("Black man", "White man")),
    "no high school - doctorate": (("did not finish high school",), ("doctorate",)),
}


def rows(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def usable(g, lenient):
    """cue_stats.py's rule: strict drops a stray premise score's whole grade."""
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


def topics(path):
    if not path:
        return {}
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    head = [str(c or "").strip().lower() for c in next(it)]
    pid, topic = head.index("prompt id"), head.index("topic")
    return {str(r[pid]).strip(): str(r[topic]).strip() for r in it if r[pid]}


def load(responses, judgments, lenient):
    """-> {answer id: (qid, qtype, provider, group, {measure: score}, hard_fail share)}"""
    answers = {}
    for a in rows(responses):
        if a.get("error") is None and (a.get("response") or "").strip():
            answers[a["id"]] = (a["qid"], a.get("question_type") or "Unspecified",
                                a["provider"], a.get("group") or "baseline")
    best = {}
    for g in rows(judgments):
        if g["id"] not in answers:
            continue
        key = (g["id"], g["judge"], g.get("pass", 0))
        rank = (usable(g, lenient), g.get("ts") or "")
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, tuple(g.get(m) for m in MEASURES), g.get("hard_fail"),
                         g.get("premise_handling"))
    grades = defaultdict(list)
    for (aid, _, _), ((ok, _), scores, hf, premise) in best.items():
        if ok:
            grades[aid].append((scores, hf, premise))
    out = {}
    for aid, gs in grades.items():
        score = {m: fmean(s[i] for s, _, _ in gs) for i, m in enumerate(MEASURES)}
        prem = [p for _, _, p in gs if p is not None]
        if prem and answers[aid][1].startswith("Loaded"):
            score["premise_handling"] = fmean(prem)
        out[aid] = (*answers[aid], score, fmean(bool(h) for _, h, _ in gs))
    return out


def tcdf_two_sided(t, df):
    """Two-sided p for Student's t, via the regularised incomplete beta."""
    x = df / (df + t * t)
    return betainc(df / 2, 0.5, x)


def betainc(a, b, x):
    if x <= 0 or x >= 1:
        return 0.0 if x <= 0 else 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x))
    if x > (a + 1) / (a + b + 2):
        return 1 - betainc(b, a, 1 - x)
    # Lentz's continued fraction, as Numerical Recipes betacf
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1 + num * d
            d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1 + num / c if abs(1 + num / c) > 1e-30 else 1e-30
            h *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return front * h / a


def bh(ps):
    """Benjamini-Hochberg q-values, in input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    q, running = [0.0] * len(ps), 1.0
    for rank in range(len(ps), 0, -1):
        i = order[rank - 1]
        running = min(running, ps[i] * len(ps) / rank)
        q[i] = running
    return q


def question_gap(cell, focal, comparison, measure):
    """cell: provider -> group -> [scores]. Gap averaged over models, t on the answers.

    The answer-level variance is pooled over every cue group of the model on this
    question: the baseline has only three answers per model, often identical, and
    its own variance would make tiny gaps look certain."""
    diffs, var, df = [], 0.0, 0
    for by_group in cell.values():
        f = [s[measure] for g in focal for s in by_group.get(g, ()) if measure in s]
        c = [s[measure] for g in comparison for s in by_group.get(g, ()) if measure in s]
        if not f or not c:
            continue
        ss, n = 0.0, 0
        for v in by_group.values():
            x = [s[measure] for s in v if measure in s]
            if len(x) > 1:
                ss += sum((a - fmean(x)) ** 2 for a in x)
                n += len(x) - 1
        if not n:
            continue
        diffs.append(fmean(f) - fmean(c))
        var += ss / n * (1 / len(f) + 1 / len(c))
        df += n
    if not diffs:
        return None
    var /= len(diffs) ** 2
    if var == 0:
        return fmean(diffs), 0.0, 1.0
    t = fmean(diffs) / math.sqrt(var)
    return fmean(diffs), math.sqrt(var), tcdf_two_sided(t, df)


def interval(values):
    n = len(values)
    if n < 3:
        return None, None
    half = 1.96 * stdev(values) / math.sqrt(n)
    m = fmean(values)
    return m - half, m + half


def between_types(gaps_by_type, rng):
    """Permutation test: does the per-question gap differ between question types?"""
    labels = [t for t, v in gaps_by_type.items() for _ in v]
    values = [x for v in gaps_by_type.values() for x in v]
    grand = fmean(values)

    def stat(lab):
        groups = defaultdict(list)
        for t, x in zip(lab, values):
            groups[t].append(x)
        return sum(len(v) * (fmean(v) - grand) ** 2 for v in groups.values())

    observed = stat(labels)
    hits = sum(stat(rng.sample(labels, len(labels))) >= observed for _ in range(PERMUTATIONS))
    return (hits + 1) / (PERMUTATIONS + 1)


def fmt(x, digits=2, sign=True):
    return "" if x is None else f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses")
    p.add_argument("judgments")
    p.add_argument("--prompts", help="prompts workbook, for each question's topic")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--lenient", action="store_true")
    p.add_argument("--seed", type=int, default=20261102)
    args = p.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    topic = topics(args.prompts)
    answers = load(args.responses, args.judgments, args.lenient)

    # qid -> provider -> group -> [score dicts]
    cells = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    qtype, hard = {}, defaultdict(list)
    for qid, qt, prov, group, score, hf in answers.values():
        cells[qid][prov][group].append(score)
        qtype[qid] = qt
        hard[qt].append(hf > 0.5)
    groups = sorted({g for c in cells.values() for pg in c.values() for g in pg} - {"baseline"})
    comparisons = {f"{g} - baseline": ((g,), ("baseline",)) for g in groups}
    comparisons.update({k: v for k, v in CONTRASTS.items() if set(v[0] + v[1]) <= set(groups)})
    types = [t for t in TYPES if t in qtype.values()] + sorted(set(qtype.values()) - set(TYPES))

    # question-type means: per question over everything, then over questions
    by_type = []
    for t in types:
        qs = [q for q in cells if qtype[q] == t]
        row = {"question_type": t, "questions": len(qs),
               "answers": sum(len(v) for q in qs for pg in cells[q].values() for v in pg.values())}
        for m in (*MEASURES, "premise_handling"):
            per_q = [fmean(s[m] for pg in cells[q].values() for v in pg.values() for s in v if m in s)
                     for q in qs if any(m in s for pg in cells[q].values() for v in pg.values() for s in v)]
            row[m] = round(fmean(per_q), 3) if per_q else None
        base = [fmean(s["total"] for pg in cells[q].values() for s in pg.get("baseline", ()))
                for q in qs if any(pg.get("baseline") for pg in cells[q].values())]
        row["baseline_total"] = round(fmean(base), 3) if base else None
        row["hard_fail_rate"] = round(fmean(hard[t]), 4)
        by_type.append(row)

    # question by question
    qrows = []
    for name, (focal, comp) in comparisons.items():
        for m in MEASURES:
            block = []
            for q in sorted(cells):
                r = question_gap(cells[q], focal, comp, m)
                if r:
                    block.append({"qid": q, "topic": topic.get(q, ""), "question_type": qtype[q],
                                  "comparison": name, "measure": m, "gap": r[0], "se": r[1], "p": r[2]})
            for r, q in zip(block, bh([r["p"] for r in block])):
                r["q"] = q
            qrows += block

    # by type, with the interaction test
    trows = []
    for name in comparisons:
        for m in MEASURES:
            gaps = defaultdict(list)
            for r in qrows:
                if r["comparison"] == name and r["measure"] == m:
                    gaps[r["question_type"]].append(r["gap"])
            for t in types:
                lo, hi = interval(gaps[t])
                trows.append({"comparison": name, "measure": m, "question_type": t,
                              "questions": len(gaps[t]), "gap": fmean(gaps[t]) if gaps[t] else None,
                              "lo": lo, "hi": hi})
            trows.append({"comparison": name, "measure": m, "question_type": "difference between types (p)",
                          "questions": sum(map(len, gaps.values())),
                          "gap": between_types(gaps, rng) if len(gaps) > 1 else None})

    def write(name, data):
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()} for r in data)

    write("by_type.csv", by_type)
    write("type_gaps.csv", trows)
    write("question_gaps.csv", qrows)

    rule = "lenient" if args.lenient else "strict"
    lines = [f"# Cue effects by question type and by question ({rule} rule)", "",
             f"{len(answers):,} answers with a usable grade, {len(cells)} questions. "
             "Gap = focal minus comparison, in rubric points; total out of 20, criteria out of 5.", "",
             "## Scores by question type", "",
             "| type | questions | total | accuracy | completeness | objectivity | sourcing | premise | hard-fail |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in by_type:
        lines.append(f"| {r['question_type']} | {r['questions']} | " + " | ".join(
            fmt(r[m], sign=False) for m in (*MEASURES, "premise_handling")) + f" | {r['hard_fail_rate']:.1%} |")
    lines += ["", "## Gap by question type", "",
              "Mean over the type's questions; `*` marks a 95% interval that excludes zero. "
              "The last column is a permutation p for whether the gap differs between types.", ""]
    for m in MEASURES:
        lines += [f"### {m}", "", "| comparison | " + " | ".join(types) + " | between types p |",
                  "|---|" + "---:|" * (len(types) + 1)]
        for name in comparisons:
            cell = {r["question_type"]: r for r in trows if r["comparison"] == name and r["measure"] == m}
            parts = []
            for t in types:
                r = cell[t]
                star = "*" if r["lo"] is not None and (r["lo"] > 0 or r["hi"] < 0) else ""
                parts.append(fmt(r["gap"]) + star)
            pt = cell["difference between types (p)"]["gap"]
            lines.append(f"| {name} | " + " | ".join(parts) + f" | {'' if pt is None else f'{pt:.3f}'} |")
        lines.append("")
    lines += ["## Questions with a gap (q < 0.05)", "",
              "Count of questions whose gap is distinguishable from zero after Benjamini-Hochberg "
              "across questions, below / above zero.", "",
              "| comparison | " + " | ".join(MEASURES) + " |", "|---|" + "---:|" * len(MEASURES)]
    for name in comparisons:
        parts = []
        for m in MEASURES:
            sig = [r for r in qrows if r["comparison"] == name and r["measure"] == m and r["q"] < 0.05]
            parts.append(f"{sum(r['gap'] < 0 for r in sig)} / {sum(r['gap'] > 0 for r in sig)}")
        lines.append(f"| {name} | " + " | ".join(parts) + " |")
    lines += ["", "### Which questions", ""]
    for name in comparisons:
        sig = sorted((r for r in qrows if r["comparison"] == name and r["q"] < 0.05),
                     key=lambda r: (r["qid"], MEASURES.index(r["measure"])))
        if not sig:
            continue
        lines += [f"**{name}**", "", "| question | type | topic | measure | gap | q |", "|---|---|---|---|---:|---:|"]
        lines += [f"| {r['qid']} | {r['question_type']} | {r['topic']} | {r['measure']} | {fmt(r['gap'])} | "
                  f"{r['q']:.3f} |" for r in sig]
        lines.append("")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(answers):,} answers, {len(cells)} questions -> {out}")


if __name__ == "__main__":
    main()
