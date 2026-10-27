#!/usr/bin/env python3
"""Tally the cue sheet's probes: what race, gender and schooling the models read
into each cue.

    python cue_probes.py probes-responses.jsonl --out-dir analysis/probes

Each probe asks a model what most people would assume about the person who
wrote the cue. Answers are normalised (race is everything before the last word,
gender the last word; education is matched against the probe's options) and
counted over the five models and three runs. report.md shows the most common
answer per cue; probes.csv has every model's counts.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# longest first, so "high school" does not swallow "less than high school"
EDUCATION = ("less than high school", "some college", "high school", "bachelor's degree",
             "graduate degree", "unknown")
GENDER = {"male": "male", "man": "male", "female": "female", "woman": "female"}


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse(probe, text):
    t = re.sub(r"[^a-z' \-]", " ", text.lower().replace("’", "'")).split()
    if probe == "education":
        s = " ".join(t)
        return {"education": next((e for e in EDUCATION if e in s), "unparsed")}
    if not t:
        return {"race": "unparsed", "gender": "unparsed"}
    gender = GENDER.get(t[-1], t[-1])
    return {"race": " ".join(t[:-1]) or "unparsed", "gender": gender}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    counts = defaultdict(Counter)              # (condition, field) -> answers
    by_model = defaultdict(Counter)            # (condition, field, model) -> answers
    cue_text = {}
    for r in read(args.responses):
        if r.get("error") is not None or not r.get("probe"):
            continue
        cue_text[r["condition"]] = r["cue"]
        for field, value in parse(r["probe"], r.get("response") or "").items():
            counts[r["condition"], field][value] += 1
            by_model[r["condition"], field, r["provider"]][value] += 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "probes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["condition", "cue", "field", "model", "answer", "count"])
        for (cond, field, model), c in sorted(by_model.items()):
            for answer, n in c.most_common():
                w.writerow([cond, cue_text[cond], field, model, answer, n])

    def top(cond, field):
        c = counts.get((cond, field))
        if not c:
            return ""
        answer, n = c.most_common(1)[0]
        return f"{answer} ({n}/{sum(c.values())})"

    lines = ["# What the models read into each cue\n",
             "Most common answer over five models and three runs.\n",
             "| condition | cue | race | gender | education |", "|---|---|---|---|---|"]
    for cond in sorted(cue_text):
        lines.append(f"| {cond.replace('|', ' / ')} | {cue_text[cond]} | {top(cond, 'race')} | "
                     f"{top(cond, 'gender')} | {top(cond, 'education')} |")
    report = "\n".join(lines) + "\n"
    (args.out_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"{len(cue_text)} cues -> {args.out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
