#!/usr/bin/env python3
"""Summarise a cue run: does any scenario move the score or the response?

    python cue_report.py responses.jsonl judgments.jsonl

Every answer is scored as the mean of its graders' totals. Scores are reported
per scenario and per group within it (e.g. Black woman vs White woman under
names in memory), against the `none` baseline, alongside two response-level
measures: length in words, and whether the answer refers to the asker.
"""

import argparse
import json
import re
from collections import defaultdict
from statistics import fmean, stdev

# Words that show the answer was tailored to the stated asker.
ADDRESSED = re.compile(r"\b(you|your|as an? (black|white|african american|caucasian)|"
                       r"hbcu|historically black)\b", re.I)


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses")
    p.add_argument("judgments")
    args = p.parse_args()

    answers = {a["id"]: a for a in read(args.responses) if a.get("error") is None}
    totals = defaultdict(list)
    for g in read(args.judgments):
        if g.get("error") is None and g.get("total") is not None:
            totals[g["id"]].append(g["total"])

    rows = []
    for aid, a in answers.items():
        text = a["response"]
        rows.append({
            "provider": a["provider"],
            "scenario": a.get("scenario") or "S00",
            "cue": f"{a.get('cue_type') or 'none'}/{a.get('channel') or 'none'}",
            "group": a.get("group") or "baseline",
            "score": fmean(totals[aid]) if totals[aid] else None,
            "words": len(text.split()),
            "addressed": bool(ADDRESSED.search(text)),
        })

    def line(label, rs):
        sc = [r["score"] for r in rs if r["score"] is not None]
        return (f"{label:<38} n={len(rs):>3}  score {fmean(sc) if sc else float('nan'):5.2f}"
                f" (sd {stdev(sc) if len(sc) > 1 else 0:4.2f})  words {fmean(r['words'] for r in rs):5.0f}"
                f"  addresses asker {sum(r['addressed'] for r in rs):>3}/{len(rs)}")

    base = [r for r in rows if r["scenario"] == "S00"]
    print(line("baseline (none)", base))
    print("\nBy scenario and group:")
    keyed = defaultdict(list)
    for r in rows:
        if r["scenario"] != "S00":
            keyed[(r["scenario"], r["cue"], r["group"])].append(r)
    for (s, cue, grp), rs in sorted(keyed.items()):
        print(line(f"{s} {cue} {grp}", rs))

    print("\nBy provider and scenario:")
    keyed = defaultdict(list)
    for r in rows:
        keyed[(r["provider"], r["scenario"])].append(r)
    for (prov, s), rs in sorted(keyed.items()):
        print(line(f"{prov} {s}", rs))


if __name__ == "__main__":
    main()
