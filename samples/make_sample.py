#!/usr/bin/env python3
"""Rebuild the placeholder question set used to exercise the pipeline.

    python samples/make_sample.py

Writes samples/flask10.xlsx: ten instructions sampled from the FLASK evaluation
set, in the column layout the run scripts expect. They stand in for the real
questions while those are being written, and they test the plumbing only -- they
carry no loaded premises, so nothing they produce says anything about the
research question.

The rows are fetched rather than committed. FLASK carries no licence, so this
repository does not redistribute any of it; the sample is generated locally and
is excluded from version control. Cite the paper, not this file:

    Ye, Kim, Kim, Hwang, Kim, Jo, Thorne, Kim and Seo.
    "FLASK: Fine-grained Language Model Evaluation based on Alignment Skill
    Sets." arXiv:2307.10928, 2023.  https://arxiv.org/abs/2307.10928
    Data: https://github.com/kaistAI/FLASK
"""

import json
import pathlib
import random
import sys
import urllib.request

SOURCE = ("https://raw.githubusercontent.com/kaistAI/FLASK/main/"
          "evaluation_set/flask_evaluation.jsonl")
OUT = pathlib.Path(__file__).with_name("flask10.xlsx")

SEED = 20260923          # fixed, so the pilot's sample can be reproduced exactly
EXPECTED_ROWS = 1740     # observed 2026-09-23; a mismatch means upstream changed
DOMAINS = ("Humanities", "Social Science", "Language")
MAX_CHARS = 400


def flat(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v or "")


def main():
    import openpyxl

    print(f"fetching {SOURCE}")
    with urllib.request.urlopen(SOURCE, timeout=120) as r:
        rows = [json.loads(line) for line in r.read().decode("utf-8").splitlines() if line.strip()]
    print(f"{len(rows)} rows upstream", end="")
    if len(rows) != EXPECTED_ROWS:
        print(f" -- note: expected {EXPECTED_ROWS}, so the sample will differ "
              f"from the one used in the pilot")
    else:
        print(" (matches the pilot)")

    pool = [r for r in rows
            if any(d in flat(r.get("domain")) for d in DOMAINS)
            and len(str(r["instruction"])) < MAX_CHARS]
    if len(pool) < 10:
        sys.exit(f"only {len(pool)} rows matched the filter; upstream format may have changed")

    random.seed(SEED)
    picked = random.sample(pool, 10)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "prompts"
    ws.append(["Prompt ID", "Domain", "Skill", "Question"])
    for r in picked:
        ws.append([f"FLASK-{int(r['idx']):04d}", flat(r.get("domain")),
                   flat(r.get("skill"))[:70], str(r["instruction"]).strip()])
    wb.save(OUT)
    print(f"wrote {OUT} ({len(picked)} questions) from a pool of {len(pool)}")
    print("placeholder only: no loaded premises, so no hard fails and no "
          "premise-handling scores")


if __name__ == "__main__":
    main()
