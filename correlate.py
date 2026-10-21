#!/usr/bin/env python3
"""Correlate open-weight and frontier models, pair by pair, without calling APIs.

    python correlate.py judgments.jsonl [more-judgments.jsonl ...] --out-dir analysis/correlation

Pass every judgment file that should be pooled: the frontier run, the vLLM run,
and any cross-grading of one family's answers by the other.

Answering phase: for each open-weight model and each frontier model, the panel
score of their answers to the same prompt -- question, polarity, identity and
replicate -- correlated across prompts. Replicates are not averaged; replicate k
of one model pairs with replicate k of the other, so each is its own sample. The
panel is the judges that graded both models' answers, so neither side is scored
by judges the other never faced.

Judging phase: for each open-weight judge and each frontier judge, the totals
they gave the same answer, correlated across every answer both graded, every
replicate counted separately.

Grades failing the analyze.py validity rules are dropped. Intervals resample
whole questions, since prompts and answers cluster by question.
"""

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import fmean

FRONTIER = {"anthropic", "google", "muse", "openai", "xai"}
CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
SHORT = {"gemma-4-31b-it": "Gemma", "gpt-oss-120b": "gpt-oss",
         "llama-4-scout-17b-16e-instruct-quantized.w4a16": "Llama-Scout",
         "olmo-3.1-32b-instruct": "OLMo", "qwen3.8-27b": "Qwen",
         "anthropic": "Anthropic", "google": "Google", "muse": "Muse",
         "openai": "OpenAI", "xai": "xAI"}
MIN_PAIRS = 10


def valid(row):
    if row.get("error") is not None:
        return False
    if any(type(row.get(k)) is not int or not 1 <= row[k] <= 5 for k in CRITERIA):
        return False
    if row.get("total") != sum(row[k] for k in CRITERIA) or type(row.get("hard_fail")) is not bool:
        return False
    premise = row.get("premise_handling")
    if str(row.get("question_type", "")).startswith("Loaded"):
        return type(premise) is int and 1 <= premise <= 5
    return premise is None


def pearson(pairs):
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = fmean(xs), fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else None


def estimate(by_question, draws, seed):
    """r over all pairs, with a 95% interval from resampling questions."""
    pairs = [p for qs in by_question.values() for p in qs]
    out = dict(r=pearson(pairs), ci_low=None, ci_high=None,
               n_pairs=len(pairs), n_questions=len(by_question))
    if out["r"] is None or len(by_question) < 2:
        return out
    rng, keys, boot = random.Random(seed), sorted(by_question), []
    for _ in range(draws):
        r = pearson([p for k in rng.choices(keys, k=len(keys)) for p in by_question[k]])
        if r is not None:
            boot.append(r)
    boot.sort()
    if boot:
        out["ci_low"], out["ci_high"] = boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot)) - 1]
    return out


def load(paths):
    grades, seen = {}, set()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = (row["id"], row["judge"], row.get("pass", 0))
                if key in seen:
                    raise SystemExit(f"duplicate judgment {key}; merge retries first")
                seen.add(key)
                if valid(row):
                    grades[key] = row
    return list(grades.values())


def answering(grades, draws, seed):
    # (prompt without provider) -> provider -> judge -> totals
    cells = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for g in grades:
        qid, polarity, identity, provider, run = g["id"].split("|")
        cells[(qid, polarity, identity, run)][provider][g["judge"]].append(g["total"])
    providers = {p for c in cells.values() for p in c}
    rows = []
    for o in sorted(providers - FRONTIER):
        for f in sorted(providers & FRONTIER):
            by_question, panel = defaultdict(list), set()
            for prompt, c in cells.items():
                if o not in c or f not in c:
                    continue
                judges = set(c[o]) & set(c[f])
                if not judges:
                    continue
                panel |= judges
                score = lambda p: fmean(fmean(c[p][j]) for j in judges)
                by_question[prompt[0]].append((score(o), score(f)))
            rows.append(dict(open_weight=o, frontier=f, **estimate(by_question, draws, seed),
                             panel=",".join(sorted(panel))))
    return rows


def judging(grades, draws, seed):
    by_answer = defaultdict(lambda: defaultdict(list))
    for g in grades:
        by_answer[g["id"]][g["judge"]].append(g["total"])
    judges = {j for a in by_answer.values() for j in a}
    rows = []
    for o in sorted(judges - FRONTIER):
        for f in sorted(judges & FRONTIER):
            by_question = defaultdict(list)
            for answer, a in by_answer.items():
                if o in a and f in a:
                    by_question[answer.split("|")[0]].append((fmean(a[o]), fmean(a[f])))
            rows.append(dict(open_weight=o, frontier=f, **estimate(by_question, draws, seed)))
    return rows


def table(title, rows):
    frontier = sorted({r["frontier"] for r in rows})
    print(f"\n{title}\n")
    print("| open-weight | " + " | ".join(SHORT.get(f, f) for f in frontier) + " |")
    print("|---" * (len(frontier) + 1) + "|")
    for o in sorted({r["open_weight"] for r in rows}):
        cells = []
        for f in frontier:
            r = next(x for x in rows if x["open_weight"] == o and x["frontier"] == f)
            cells.append("n/a" if r["r"] is None or r["n_pairs"] < MIN_PAIRS else
                         f"{r['r']:+.2f} ({r['ci_low']:+.2f} to {r['ci_high']:+.2f}), n={r['n_pairs']}")
        print(f"| {SHORT.get(o, o)} | " + " | ".join(cells) + " |")


def save(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("judgments", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    grades = load(args.judgments)
    answer_rows = answering(grades, args.bootstrap, args.seed)
    judge_rows = judging(grades, args.bootstrap, args.seed)
    if not any(r["n_pairs"] for r in answer_rows + judge_rows):
        raise SystemExit("no prompt or answer is shared by an open-weight and a frontier model")
    if answer_rows:
        table("Answering: panel scores on the same prompt and replicate", answer_rows)
    if judge_rows:
        table("Judging: totals given to the same answer", judge_rows)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        save(args.out_dir / "answer_correlation.csv", answer_rows)
        save(args.out_dir / "judge_correlation.csv", judge_rows)


if __name__ == "__main__":
    main()
