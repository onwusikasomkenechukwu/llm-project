#!/usr/bin/env python3
"""Expand the law school's cue templates into cues.jsonl for the runners.

    python cues.py Scenarios.csv Identities.csv
    python openai_batch.py answer prompts.xlsx --cues cues.jsonl
    python cues.py Scenarios.csv Identities.csv --probes Probes.csv --out cues-x.jsonl

Follows the Legend sheet: for each scenario, take every Identities row whose
block equals the scenario's applies_to (the baseline takes none), fill each
{PLACEHOLDER} from that row, and repeat `runs` times. {QUESTION} is left in for
the runner to fill per question. The baseline is named "none" so analyze.py
contrasts every cue against it.

--probes also writes the sheet's probes (questions about the cue itself, sent
three times each and never graded) to probes-<out>, in the same format. They
carry no {QUESTION}, so run them against a one-question workbook.
"""

import argparse
import csv
import json
import re
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenarios")
    p.add_argument("identities")
    p.add_argument("--out", default="cues.jsonl")
    p.add_argument("--probes", help="the Probes sheet as CSV")
    args = p.parse_args()

    with open(args.scenarios, encoding="utf-8-sig", newline="") as f:
        scenarios = list(csv.DictReader(f))
    with open(args.identities, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    def fill(template, row):
        def one(m):
            if m.group(1) == "QUESTION":
                return m.group(0)
            value = (row or {}).get(m.group(1), "").strip()
            if not value:
                sys.exit(f"{row and row['identity_row_id']}: no value for {{{m.group(1)}}}")
            return value
        return re.sub(r"\{([A-Z_]+)\}", one, template)

    cues = []
    for s in scenarios:
        members = [None] if s["applies_to"] == "none" else \
                  [r for r in rows if r["block"] == s["applies_to"]]
        if s["applies_to"] != "none" and len(members) != int(s["identity_rows"]):
            sys.exit(f"{s['scenario_id']}: expected {s['identity_rows']} rows, found {len(members)}")
        for r in members:
            cues.append({
                "identity": "none" if r is None else f"{s['scenario_id']}-{r['identity_row_id']}",
                "system": fill(s["system_prompt_template"], r),
                "user": fill(s["user_prompt_template"], r),
                "runs": int(s["runs"]),
                "row": {"scenario": s["scenario_id"], "block": s["block"],
                        "cue_type": s["cue_type"], "channel": s["channel"],
                        "identity_row": r and r["identity_row_id"],
                        "group": r and r["identity"], "exemplar": r and r["exemplar"],
                        "arm": r and r.get("arm")},
            })

    with open(args.out, "w", encoding="utf-8") as f:
        for c in cues:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(cues)} cues, {sum(c['runs'] for c in cues)} prompts per question per model -> {args.out}")

    if args.probes:
        with open(args.probes, encoding="utf-8-sig", newline="") as f:
            probes = list(csv.DictReader(f))
        out = f"probes-{args.out}"
        with open(out, "w", encoding="utf-8") as f:
            for r in probes:
                # "|" separates the fields of an answer id, so it cannot appear in one
                f.write(json.dumps({"identity": "PR:" + r["probe_id"].replace("|", ":"),
                                    "system": "", "user": r["prompt"], "runs": 3,
                                    "row": {"condition": r["condition_id"], "probe": r["probe"],
                                            "cue": r["cue"]}}, ensure_ascii=False) + "\n")
        print(f"{len(probes)} probes, 3 runs each -> {out}")


if __name__ == "__main__":
    main()
