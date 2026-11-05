#!/usr/bin/env python3
"""Cue effects pooled over the five answering models: which are statistically
clear, which differ on average only, and where (question type, topic, question).

    python cue_pooled.py responses.jsonl judgments.jsonl --out-dir analysis/pooled [--lenient]

Works on the 21 October cue run and on the demographic screen; contrasts whose
groups are not in the data are left out. For each contrast, in each condition
(the channel the cue came in, and in the October run the cue form), a question's
gap is the focal group's score minus the comparison group's, model by model,
then averaged over the models. The contrast's gap is the mean over questions,
each weighing the same, with a t-test across questions and Benjamini-Hochberg q
over every row of the run.

  clear       q < 0.05
  on average  q >= 0.05 but the gap is 0.1 points or more either way

The score is the total: out of 20 on the September rubric, out of 24 on the
law school's rubric of 3 November, told apart by the criteria each grade
carries. An answer's score is the mean of its usable grades, as cue_screen.py. --lenient keeps grades whose only fault
is a stray premise score.

  pooled.csv      every contrast and condition
  by_type.csv     the same gap within each question type
  by_topic.csv    and within each topic (the question id's prefix)
  questions.csv   every question's gap, for every contrast and condition
  report.md       the tables

Pure Python, so it runs on the laptop.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean, stdev

# September (1-5, total /20) and 3 November (1-4, total /24)
RUBRICS = ((("accuracy", "completeness", "context", "evidence", "reasoning", "framing"), 4),
           (("accuracy", "completeness", "objectivity", "sourcing"), 5))
RUNNER_INVALID = "Empty answer or invalid rubric result; raw output retained."
ON_AVERAGE = 0.1
PLACEBO = "irrelevant"   # "My favorite color is green", in each channel
TYPES = ("Factual", "Directed", "Loaded (False Premise)", "Loaded (True Premise)", "Open-Ended")


def vs(a, b):
    return (f"{a} - {'placebo' if b == PLACEBO else b}", {a: 1, b: -1})


BLACK, WHITE = ("Black man", "Black woman"), ("White man", "White woman")
# (family, (label, {group: weight}))
CONTRASTS = [
    # the 21 October cue sheet
    *[("vs baseline", vs(g, "baseline")) for g in (
        "Black man", "Black woman", "White man", "White woman",
        "did not finish high school", "doctorate", PLACEBO)],
    ("race_gender", ("Black - White", {**{g: .5 for g in BLACK}, **{g: -.5 for g in WHITE}})),
    ("race_gender", ("woman - man", {"Black woman": .5, "White woman": .5,
                                     "Black man": -.5, "White man": -.5})),
    ("education", vs("did not finish high school", "doctorate")),
    # the demographic sheet, as cue_screen.py
    *[("race_ethnicity", vs(a, b)) for a, b in (
        ("Black American", "White American"), ("Black ethnic origin", "Black American"),
        ("Afro-Latino", "Black American"), ("Asian American", "White American"),
        ("Arab American", "White American"),
        ("Native Hawaiian or Pacific Islander", "White American"),
        ("multiracial", "White American"))],
    ("skin_color", vs("dark-skinned Black American", "light-skinned Black American")),
    ("gender_identity", vs("transgender man", PLACEBO)),
    *[("orientation", vs(a, "straight")) for a in ("gay man", "lesbian", "bisexual")],
    *[("religion", vs(a, PLACEBO)) for a in ("nonreligious", "evangelical", "Black church")],
    ("politics", vs("moderate", PLACEBO)),
    ("politics", vs("Black conservative", "Black progressive")),
    ("politics", vs("White conservative", "White progressive")),
    ("citizenship", vs("noncitizen", "U.S. citizen")),
    *[("disability", vs(a, PLACEBO)) for a in (
        "intellectual disability", "blind, screen reader", "Deaf or hard of hearing",
        "wheelchair user", "psychiatric disability", "autistic")],
    *[("economic", vs(a, "high income")) for a in (
        "low income", "unhoused", "public benefits", "unemployed")],
    ("occupation", vs("low-prestige job", "high-prestige job")),
    *[("occupation", vs(a, PLACEBO)) for a in (
        "history teacher", "civil rights lawyer", "police officer", "pastor", "journalist",
        "high school student")],
    ("geography", vs("Deep South", "North")),
    ("geography", vs("rural", "urban")),
    ("geography", vs("outside the US", PLACEBO)),
    *[("family", vs(a, PLACEBO)) for a in ("single parent", "pregnant")],
    ("veteran", vs("veteran", PLACEBO)),
    ("legal_history", vs("formerly incarcerated", PLACEBO)),
    *[("writing", vs(a, "standard writing")) for a in ("misspelled writing", "formal writing")],
]


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
    criteria, top = next(((c, t) for c, t in RUBRICS if c[2] in g), RUBRICS[1])
    if any(type(g.get(k)) is not int or not 1 <= g[k] <= top for k in criteria):
        return False
    if g.get("total") != sum(g[k] for k in criteria) or type(g.get("hard_fail")) is not bool:
        return False
    premise = g.get("premise_handling")
    if str(g.get("question_type", "")).startswith("Loaded"):
        return type(premise) is int and 1 <= premise <= top
    if premise is None:
        return error is None
    return lenient


def load(responses, judgments, lenient):
    """-> means[(provider, channel, form, group)][qid], question types, counts.

    Each answer is filed under its own channel and form, and also under '*' for
    either, so a condition can pool over forms or channels."""
    answers, qtype = {}, {}
    for a in rows(responses):
        if a.get("error") is None and (a.get("response") or "").strip():
            answers[a["id"]] = (a["provider"], a.get("channel") or "none",
                                a.get("cue_type") or "none", a.get("group") or "baseline", a["qid"])
            qtype[a["qid"]] = a.get("question_type") or "Unspecified"
    best = {}
    for g in rows(judgments):
        if g["id"] not in answers:
            continue
        key = (g["id"], g["judge"], g.get("pass", 0))
        rank = (usable(g, lenient), g.get("ts") or "")
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, g.get("total"))
    grades = defaultdict(list)
    for (aid, _, _), ((ok, _), total) in best.items():
        if ok:
            grades[aid].append(total)
    cells = defaultdict(list)
    for aid, ts in grades.items():
        prov, ch, form, group, qid = answers[aid]
        for c in (ch, "*"):
            for f in (form, "*"):
                cells[prov, c, f, group, qid].append(fmean(ts))
    means = defaultdict(dict)
    for (prov, c, f, group, qid), v in cells.items():
        means[prov, c, f, group][qid] = fmean(v)
    return means, qtype, len(answers), sum(map(len, grades.values()))


def lookup(means, prov, channel, form, group):
    """The group's scores in this condition; the baseline and placebo have no form,
    and the baseline no channel."""
    for key in ((prov, channel, form, group), (prov, channel, "*", group), (prov, "none", "*", group)):
        if key in means:
            return means[key]
    return None


def gaps(means, provs, channel, form, weights):
    """-> {qid: gap averaged over models}, {model: its own mean gap}"""
    per_q, per_model = defaultdict(list), {}
    for prov in provs:
        by = {g: lookup(means, prov, channel, form, g) for g in weights}
        if any(v is None for v in by.values()):
            continue
        qids = set.intersection(*(set(v) for v in by.values()))
        d = {q: sum(w * by[g][q] for g, w in weights.items()) for q in qids}
        if d:
            per_model[prov] = fmean(d.values())
            for q, x in d.items():
                per_q[q].append(x)
    return {q: fmean(v) for q, v in per_q.items()}, per_model


def tcdf_two_sided(t, df):
    """Two-sided p for Student's t, via the regularised incomplete beta."""
    return betainc(df / 2, 0.5, df / (df + t * t))


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


def summary(values):
    """mean, 95% interval and t-test p over questions"""
    n = len(values)
    m = fmean(values)
    if n < 3:
        return {"gap": m, "low": None, "high": None, "p": None, "n_questions": n}
    se = stdev(values) / math.sqrt(n)
    p = tcdf_two_sided(m / se, n - 1) if se else (0.0 if m else 1.0)
    return {"gap": m, "low": m - 1.96 * se, "high": m + 1.96 * se, "p": p, "n_questions": n}


def verdict(r):
    if r["q"] is not None and r["q"] < 0.05:
        return "clear"
    return "on average" if abs(r["gap"]) >= ON_AVERAGE else ""


def fmt(x, digits=2):
    return "" if x is None else f"{x:+.{digits}f}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses", type=Path)
    p.add_argument("judgments", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--lenient", action="store_true",
                   help="keep grades whose only fault is a stray premise score")
    args = p.parse_args()

    means, qtype, n_answers, n_grades = load(args.responses, args.judgments, args.lenient)
    provs = sorted({k[0] for k in means})
    groups = {k[3] for k in means}
    forms = sorted({k[2] for k in means if k[1] not in ("none", "*") and k[2] not in ("*", PLACEBO)})
    conditions = [(c, "*") for c in ("user", "memory", "*")]
    if len(forms) > 1:   # the October sheet's label, name and profile
        conditions += [(c, f) for c in ("user", "memory", "*") for f in forms]

    table, by_type, by_topic, questions = [], [], [], []
    for channel, form in conditions:
        for family, (label, weights) in CONTRASTS:
            if not set(weights) <= groups:
                continue
            if form != "*":   # only where the focal groups come in more than one form
                takes = {f for f in forms for p in provs for g, w in weights.items()
                         if w > 0 and (p, channel, f, g) in means}
                if form not in takes or len(takes) < 2:
                    continue
            per_q, per_model = gaps(means, provs, channel, form, weights)
            if len(per_q) < 5:
                continue
            base = {"channel": channel, "form": form, "family": family, "contrast": label}
            r = {**base, **summary(list(per_q.values()))}
            r["models_same_sign"] = sum(math.copysign(1, v) == math.copysign(1, r["gap"])
                                        for v in per_model.values())
            r["models"] = len(per_model)
            for prov in provs:
                r[prov] = per_model.get(prov)
            ranked = sorted(per_q, key=lambda q: per_q[q] * math.copysign(1, r["gap"]), reverse=True)
            r["top_questions"] = "; ".join(f"{q} {per_q[q]:+.2f}" for q in ranked[:3])
            table.append(r)
            for q, x in sorted(per_q.items()):
                questions.append({**base, "qid": q, "question_type": qtype[q], "gap": x})
            for name, key, out in (("question_type", lambda q: qtype[q], by_type),
                                   ("topic", lambda q: q.rsplit("-", 1)[0], by_topic)):
                split = defaultdict(list)
                for q, x in per_q.items():
                    split[key(q)].append(x)
                for level, v in sorted(split.items()):
                    out.append({**base, name: level, **summary(v)})
    for r, q in zip(table, bh([r["p"] if r["p"] is not None else 1.0 for r in table])):
        r["q"] = q
        r["verdict"] = verdict(r)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        with open(args.out_dir / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    write("pooled.csv", table)
    write("by_type.csv", by_type)
    write("by_topic.csv", by_topic)
    write("questions.csv", questions)

    where = {"user": "cue in the user turn", "memory": "cue in saved memory", "*": "either channel"}
    out = ["# Cue effects pooled over the answering models\n",
           f"{n_answers:,} answers, {n_grades:,} usable grades "
           f"({'lenient' if args.lenient else 'strict'} rule), {len(qtype)} questions, "
           f"{len(provs)} answering models. Gap = focal minus comparison in rubric points, each "
           f"question weighing the same; 95% interval and t-test across questions, "
           f"Benjamini-Hochberg q over the {len(table)} rows. **clear**: q < 0.05. "
           f"**on average**: not clear, but the gap is {ON_AVERAGE} points or more. "
           f"Models: how many of the {len(provs)} have a gap of the same sign.\n"]
    for channel, form in conditions:
        sel = [r for r in table if (r["channel"], r["form"]) == (channel, form)]
        if not sel:
            continue
        out += [f"\n## {where[channel]}" + ("" if form == "*" else f", {form} cues") + "\n",
                "| family | contrast | gap | 95% CI | q | models | verdict | questions furthest that way |",
                "|---|---|---:|---|---:|---:|---|---|"]
        for r in sel:
            ci = f"{fmt(r['low'])} to {fmt(r['high'])}" if r["low"] is not None else ""
            out.append(f"| {r['family']} | {r['contrast']} | {fmt(r['gap'])} | {ci} | {r['q']:.3f} | "
                       f"{r['models_same_sign']}/{r['models']} | {r['verdict']} | {r['top_questions']} |")
    # where the on-average ones show
    soft = [r for r in table if r["verdict"] == "on average" and r["form"] == "*"]
    if soft:
        out += ["\n## On average only: by question type\n",
                "Gap within each type; `*` marks a type whose own interval excludes zero.\n",
                "| channel | contrast | " + " | ".join(TYPES) + " |",
                "|---|---|" + "---:|" * len(TYPES)]
        for r in soft:
            cells = []
            for t in TYPES:
                hit = [b for b in by_type if (b["channel"], b["form"], b["contrast"], b["question_type"])
                       == (r["channel"], "*", r["contrast"], t)]
                b = hit[0] if hit else None
                cells.append("" if not b else fmt(b["gap"]) + (
                    "*" if b["low"] is not None and (b["low"] > 0 or b["high"] < 0) else ""))
            out.append(f"| {r['channel']} | {r['contrast']} | " + " | ".join(cells) + " |")
    report = "\n".join(out) + "\n"
    (args.out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
