#!/usr/bin/env python3
"""Pairwise contrasts for a cue run: two answers form a pair when they match on
every factor except one, and the pair's difference is that factor's effect.

    python cue_pairs.py responses.jsonl judgments.jsonl
    python cue_pairs.py responses.jsonl judgments.jsonl --by provider

Factors: model, channel (user turn or memory), cue type (label, name, profile),
race, gender, education, exemplar, and replicate run. Pairs differing only in
run measure replicate noise, the floor any other effect has to clear.

An answer's score is the mean of its graders. Intervals resample questions when
there are several, otherwise pairs.
"""

import argparse
import json
import random
from collections import defaultdict
from statistics import fmean

FACTORS = ("provider", "channel", "cue_type", "race", "gender", "education", "exemplar", "run")
METRICS = ("total", "accuracy", "completeness", "objectivity", "sourcing")
# Differences are reported as second level minus first.
ORDER = {"race": ["White", "Black"], "gender": ["man", "woman"], "channel": ["user", "memory"],
         "education": ["no diploma", "doctorate"],
         "cue_type": ["label", "name", "profile"]}


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def factors(a):
    group = a.get("group") or ""
    race, gender = group.split() if a.get("block") == "race_gender" else (None, None)
    return {"provider": a["provider"], "channel": a.get("channel") or "none",
            "cue_type": a.get("cue_type") or "none", "race": race, "gender": gender,
            "education": ({"did not finish high school": "no diploma"}.get(group, group)
                          if a.get("block") == "education" else None),
            "exemplar": a.get("exemplar"), "run": a["run"], "qid": a["qid"]}


def interval(pairs, draws, seed):
    """95% bootstrap interval of the mean difference, resampling questions if
    there are several and pairs otherwise."""
    by_q = defaultdict(list)
    for p in pairs:
        by_q[p["qid"]].append(p["diff"])
    rng = random.Random(seed)
    units = list(by_q.values()) if len(by_q) > 1 else [[p["diff"]] for p in pairs]
    means = sorted(fmean([d for u in rng.choices(units, k=len(units)) for d in u])
                   for _ in range(draws))
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses")
    p.add_argument("judgments")
    p.add_argument("--by", choices=FACTORS, help="also split each contrast by this factor")
    p.add_argument("--bootstrap", type=int, default=5000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    answers = {a["id"]: a for a in read(args.responses) if a.get("error") is None}
    grades = defaultdict(lambda: defaultdict(list))
    for g in read(args.judgments):
        if g.get("error") is None and g.get("total") is not None and g["id"] in answers:
            for m in METRICS:
                grades[g["id"]][m].append(g[m])
    rows = [dict(factors(answers[i]), **{m: fmean(v) for m, v in grades[i].items()})
            for i in answers if grades[i]]

    print(f"{len(rows)} graded answers\n")
    print(f"{'contrast':<60}{'pairs':>6}{'total':>8}{'95% interval':>18}{'2nd higher':>12}{'sourcing':>10}")
    for factor in FACTORS:
        others = [f for f in FACTORS if f != factor]
        cells = defaultdict(dict)
        for r in rows:
            if r[factor] is not None:
                cells[tuple(r[f] for f in others) + (r["qid"],)][r[factor]] = r
        levels = ORDER.get(factor) or sorted({lv for c in cells.values() for lv in c}, key=str)
        for i, a in enumerate(levels):
            for b in levels[i + 1:]:
                pairs = [{"qid": key[-1], "ctx": dict(zip(others, key)),
                          "diff": c[b]["total"] - c[a]["total"],
                          "src": c[b]["sourcing"] - c[a]["sourcing"]}
                         for key, c in cells.items() if a in c and b in c]
                if not pairs:
                    continue
                splits = [("", pairs)]
                if args.by and args.by != factor:
                    split = defaultdict(list)
                    for q in pairs:
                        split[q["ctx"][args.by]].append(q)
                    splits += [(f"  {args.by}={k}", v) for k, v in sorted(split.items(), key=str)]
                for suffix, ps in splits:
                    lo, hi = interval(ps, args.bootstrap, args.seed)
                    higher = sum(q["diff"] > 0 for q in ps) / len(ps)
                    label = f"{factor}: {b} - {a}{suffix}"
                    print(f"{label[:59]:<60}{len(ps):>6}{fmean(q['diff'] for q in ps):>+8.2f}"
                          f"{f'{lo:+.2f} to {hi:+.2f}':>18}{higher:>11.0%}"
                          f"{fmean(q['src'] for q in ps):>+10.2f}")


if __name__ == "__main__":
    main()
