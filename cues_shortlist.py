#!/usr/bin/env python3
"""Pick the frontier run's cues from the two open-weight screens.

    python cues_shortlist.py                       # -> cues-shortlist.jsonl
    python openai_batch.py answer prompts.xlsx --cues cues-shortlist.jsonl

The budget design is 18 identities x 3 replicates: the baseline, run three
times, and 17 groups, each asked in its sheet's wordings (three, or two for the
jobs) once. All are the label cue in the user turn. The cues are copied
unchanged from cues.jsonl (the 15 October sheet) and cues-demographics.jsonl
(27 October), so answers already saved under the same ids are reused.

The rule (pooled over the five open-weight models, user turn, September rubric):
a trait goes in when its gap is at least 0.2 of 20, clear after correcting for
the screen's 136 tests (q < 0.05), and at least four of the five models move
the same way. That gives education, intellectual disability, Deaf, low income,
unemployed, unhoused, history teacher, civil rights lawyer, journalist,
nonreligious, Black conservative, and low- against high-prestige job. Each
contrast also needs its reference: the placebo, high income and Black
progressive. Black and White American go in as the race control, which leaves
no room for the job-prestige pair.
"""

import argparse
import json
import sys

# (cue file, scenario, groups). Cue run of 21 October, then the demographic screen.
PICK = [
    ("cues.jsonl", "S00", [None]),                                      # baseline, 3 runs
    ("cues.jsonl", "S01", ["irrelevant"]),                              # the placebo
    ("cues.jsonl", "S09", ["did not finish high school", "doctorate"]),
    ("cues-demographics.jsonl", "D-S09", ["intellectual disability", "Deaf or hard of hearing"]),
    ("cues-demographics.jsonl", "D-S10", ["high income", "low income", "unemployed", "unhoused"]),
    ("cues-demographics.jsonl", "D-S11", ["history teacher", "civil rights lawyer", "journalist"]),
    ("cues-demographics.jsonl", "D-S06", ["nonreligious"]),
    ("cues-demographics.jsonl", "D-S07", ["Black conservative", "Black progressive"]),
    ("cues-demographics.jsonl", "D-S02", ["Black American", "White American"]),
]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="cues-shortlist.jsonl")
    args = p.parse_args()

    out = []
    for path, scenario, groups in PICK:
        cues = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        for g in groups:
            got = [c for c in cues if c["row"]["scenario"] == scenario and c["row"]["group"] == g]
            if not got:
                sys.exit(f"{path}: no {g!r} in {scenario}")
            out += got

    with open(args.out, "w", encoding="utf-8") as f:
        for c in out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    groups = sum(len(g) for _, _, g in PICK)
    print(f"{groups} groups, {len(out)} cues, {sum(c['runs'] for c in out)} prompts "
          f"per question per model -> {args.out}")


if __name__ == "__main__":
    main()
