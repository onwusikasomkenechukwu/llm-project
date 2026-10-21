#!/usr/bin/env python3
"""Why grades failed: a breakdown per judge, with one example of each kind.

    python vllm_failures.py                      # judgments-vllm_offline.jsonl
    python vllm_failures.py judgments.jsonl

Only the latest row per (answer, judge, pass) counts, so a failure that a later
retry fixed is not reported.
"""

import json
import sys
from collections import Counter, defaultdict

CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
JUDGE_TOKENS = 3000


def reason(r):
    """The first thing wrong with a grade, or None if it is usable."""
    loaded = str(r.get("question_type", "")).startswith("Loaded")
    ph = r.get("premise_handling")
    if not (r.get("raw") or "").strip():
        return "empty reply"
    if any(r.get(k) is None for k in CRITERIA):
        if (r.get("output_tokens") or 0) >= JUDGE_TOKENS:
            return "hit the token ceiling before the rubric JSON"
        return "no rubric JSON found"
    if any(type(r.get(k)) is not int or not 1 <= r[k] <= 5 for k in CRITERIA):
        return "criterion outside 1-5"
    if r.get("total") != sum(r[k] for k in CRITERIA):
        return "total does not add up"
    if type(r.get("hard_fail")) is not bool:
        return "hard_fail missing"
    if loaded and not (type(ph) is int and 1 <= ph <= 5):
        return "premise_handling missing on a Loaded question"
    if not loaded and ph is not None:
        return "premise_handling given on a non-Loaded question"
    return None if r.get("error") is None else "other: " + str(r["error"])[:60]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "judgments-vllm_offline.jsonl"
    latest = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                key = (r["id"], r.get("judge"), r.get("pass", 0))
                if key not in latest or reason(latest[key]) is not None:
                    latest[key] = r

    total, why, example = Counter(), defaultdict(Counter), {}
    for r in latest.values():
        j = r.get("judge")
        total[j] += 1
        w = reason(r)
        if w:
            why[j][w] += 1
            example.setdefault((j, w), r)

    print(f"{path}: {len(latest)} grades, {sum(sum(c.values()) for c in why.values())} failing\n")
    for j in sorted(total, key=str):
        bad = sum(why[j].values())
        print(f"{j}: {bad} of {total[j]} failing")
        for w, n in why[j].most_common():
            ex = example[(j, w)]
            tail = (ex.get("raw") or "")[-160:].replace("\n", " ")
            print(f"   {n:5}  {w}\n          e.g. {ex['id']} ({ex.get('question_type')}): ...{tail}")
        print()


if __name__ == "__main__":
    main()
