#!/usr/bin/env python3
"""Grade each rubric criterion in its own prompt, to compare with grading all six at once.

    python vllm_per_criterion.py judge responses.jsonl --prompts prompts.xlsx --models <hf-id>,... --out parts.jsonl
    python vllm_per_criterion.py assemble parts.jsonl --out judgments-per-criterion.jsonl
    python vllm_per_criterion.py compare judgments-single.jsonl judgments-per-criterion.jsonl --out-dir analysis

Dr. Aryal asked on 19 November for a subset graded one criterion per prompt:
when a judge writes all six ratings in one reply, the first can pull the
others along. vllm_offline.py grades in one call per answer. Here every answer
gets one call per criterion, one for premise handling (loaded questions only)
and one for the hard-fail check, so 7 or 8 calls per answer and judge.

Each prompt is cut from vllm_offline.py's JUDGE_PROMPT, so the wording is the
same: the same header (question type, question, answer, reference answer),
then that one criterion's description and levels, then a one-field JSON reply.
The answer still comes before the rubric, as validated, and since the header
is shared, vLLM's prefix cache reads each answer once for all its parts.

`judge` writes one row per answer, judge and part. `assemble` joins the parts
into ordinary judgment rows (the same fields as vllm_offline.py, plus
"mode": "per-criterion"), so every analysis script reads them unchanged.
`compare` sets them against one-prompt grades of the same answers. Rerunning
`judge` skips parts already saved.
"""

import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict
from statistics import fmean

import vllm_offline as vo

PARTS = vo.CRITERIA + ("premise_handling", "hard_fail")
LEVELS = ('at one of four levels, written exactly as: "fully meets", "substantially meets", '
          '"partially meets" or "does not meet".')


def split_prompt():
    """(header template, {part: its block}) cut from vllm_offline.JUDGE_PROMPT."""
    head, rest = vo.JUDGE_PROMPT.split("Rate each criterion at one of four levels", 1)
    body = rest.split("\n\n", 1)[1].split("Reply with only a JSON object", 1)[0]
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(rf"^({'|'.join(PARTS)}) - ", body, re.M)]
    blocks = {}
    for (at, part), (end, _) in zip(starts, starts[1:] + [(len(body), None)]):
        blocks[part] = body[at:end].strip("\n") + "\n"
    if set(blocks) != set(PARTS):
        sys.exit(f"JUDGE_PROMPT changed: found parts {sorted(blocks)}")
    return head, blocks


def part_prompt(head, blocks, part):
    if part == "hard_fail":
        ask, reply = "Check the answer for a hard fail.", '"hard_fail": <true|false>'
    elif part == "premise_handling":
        ask, reply = (f"Rate how the answer handles the premise of the question, {LEVELS}",
                      '"premise_handling": "<level>"')
    else:
        ask, reply = f"Rate one criterion of the rubric, {LEVELS}", f'"{part}": "<level>"'
    tail = (f"{ask}\n\n{blocks[part]}\nReply with only a JSON object, no other text:\n"
            f'{{{{{reply}, "justification": "<at most 25 words>"}}}}')
    return head + tail


def part_value(row):
    v = row.get(row["part"])
    return v if (type(v) is bool if row["part"] == "hard_fail"
                 else type(v) is int and 1 <= v <= 4) else None


# ---------------------------------------------------------------------------
# judge
# ---------------------------------------------------------------------------

def judge(args):
    head, blocks = split_prompt()
    refs = {}
    if args.prompts:
        for q in vo.load_prompts(args.prompts, 0, None, None, None, None):
            if q["ideal"] or q["components"]:
                refs[q["qid"]] = (q["ideal"], q["components"])
    answers, seen = [], set()
    for a in vo.read_jsonl(args.input):
        if a.get("error") is None and (a.get("response") or "").strip() and a["id"] not in seen:
            seen.add(a["id"])
            answers.append(a)
    print(f"{len(answers)} answers, {len(refs)} questions with a reference answer")

    # a part row counts as done when its one value was read; vllm_offline's own
    # check wants all six criteria, so swap in this one for make_row
    vo.usable = lambda row, stage: row.get("error") is None and part_value(row) is not None

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    failed = 0
    for model in models:
        prov = vo.short_name(model)
        vo.PROVIDERS[prov] = model
        done = {(r["id"], r["part"]) for r in vo.read_jsonl(args.out)
                if r.get("judge") == prov and r.get("error") is None and part_value(r) is not None}
        cells = []
        for a in answers:
            qtype = a.get("question_type") or "Unspecified"
            ideal, comps = refs.get(a.get("qid"), ("", ""))
            reference = (vo.REFERENCE_BLOCK.format(
                ideal=ideal or "(none supplied)",
                components=vo.COMPONENTS_LINE.format(items=comps) if comps else "")
                if ideal or comps else "")
            fields = dict(claim=a.get("question") or a["user"], answer=a["response"],
                          qtype=qtype, reference=reference)
            for part in PARTS:
                if part == "premise_handling" and not qtype.startswith("Loaded"):
                    continue
                if (a["id"], part) in done:
                    continue
                cells.append({
                    "id": a["id"], "provider": prov, "system": "",
                    "user": part_prompt(head, blocks, part).format(**fields),
                    "row": {"judge": prov, "pass": 0, "part": part, "qid": a.get("qid"),
                            "polarity": a.get("polarity"), "identity": a.get("identity"),
                            "question_type": qtype, "graded_vs_reference": bool(ideal or comps),
                            "provider": a.get("provider"), "mode": "per-criterion"},
                })
        print(f"{prov}: {len(done)} parts saved, {len(cells)} to do -> {args.out}")
        if args.dry_run:
            for c in cells[:2]:
                print(f"\n--- {c['id']} {c['row']['part']}\n{c['user'][-1500:]}")
            continue
        if cells:
            failed += vo.run_model(args, "judge", prov, cells, args.out, args.throughput)
    if failed:
        print(f"\n{failed} part(s) failed. Rerun the same command to retry them.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

def assemble(args):
    parts = defaultdict(dict)
    for r in vo.read_jsonl(args.input):
        if r.get("error") is None and part_value(r) is not None:
            parts[(r["id"], r["judge"])][r["part"]] = r      # the last good one wins
    out, complete = [], 0
    for (aid, j), got in parts.items():
        first = next(iter(got.values()))
        loaded = str(first.get("question_type", "")).startswith("Loaded")
        row = {"id": aid, **{k: first.get(k) for k in (
            "judge", "pass", "qid", "polarity", "identity", "question_type",
            "graded_vs_reference", "provider")},
            "judge_model": first.get("judge_model"), "mode": "per-criterion"}
        for k in PARTS:
            row[k] = got[k][k] if k in got else None
        if all(row[k] is not None for k in vo.CRITERIA):
            row["total"] = sum(row[k] for k in vo.CRITERIA)
            row["rating"] = next(label for lo, label in vo.RATINGS if row["total"] >= lo)
            if row["hard_fail"]:
                row["rating"] = "Fail (Hard-Fail)"
        else:
            row["total"] = row["rating"] = None
        row["justification"] = " | ".join(f"{k}: {got[k].get('justification')}"
                                          for k in PARTS if k in got)
        row["input_tokens"] = sum(g.get("input_tokens") or 0 for g in got.values())
        row["output_tokens"] = sum(g.get("output_tokens") or 0 for g in got.values())
        row["cached_input_tokens"] = sum(g.get("cached_input_tokens") or 0 for g in got.values())
        row["calls"] = len(got)
        ok = vo.usable(row, "judge")
        row["error"] = None if ok else "Empty answer or invalid rubric result; raw output retained."
        complete += ok
        out.append(row)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(out)} grades, {complete} complete -> {args.out}")


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

EDU_LOW, EDU_HIGH = "S09-EDU-low-", "S09-EDU-high-"


def load_grades(path):
    """(answer id, judge) -> the last row with all six criteria and a hard-fail
    flag. A stray premise score is ignored (the lenient rule); `strict` records
    whether the row also passed the runner's own check."""
    out = {}
    for r in vo.read_jsonl(path):
        if all(type(r.get(k)) is int and 1 <= r[k] <= 4 for k in vo.CRITERIA) \
                and type(r.get("hard_fail")) is bool:
            out[(r["id"], r["judge"])] = dict(r, total=sum(r[k] for k in vo.CRITERIA),
                                             strict=r.get("error") is None)
    return out


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = fmean(xs), fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else None


def alpha(units):
    """Krippendorff's alpha, interval metric. units: lists of the judges' values."""
    units = [u for u in units if len(u) >= 2]
    n = sum(len(u) for u in units)
    if n < 2:
        return None
    do = sum(2 * (len(u) * sum(v * v for v in u) - sum(u) ** 2) / (len(u) - 1) for u in units) / n
    allv = [v for u in units for v in u]
    de = 2 * (n * sum(v * v for v in allv) - sum(allv) ** 2) / (n * (n - 1))
    return 1 - do / de if de else None


def gap(rows, a_ids, b_ids, field, draws=500, seed=1):
    """Group a minus group b on `field`, within question and answering model,
    with a bootstrap over questions."""
    cell = defaultdict(lambda: ([], []))
    for r in rows:
        side = 0 if a_ids(r["identity"]) else 1 if b_ids(r["identity"]) else None
        if side is not None:
            cell[(r["qid"], r["provider"])][side].append(r[field])
    by_q = defaultdict(list)
    for (q, _), (a, b) in cell.items():
        if a and b:
            by_q[q].append(fmean(a) - fmean(b))
    qs = sorted(by_q)
    if not qs:
        return None, None, None
    est = fmean(fmean(by_q[q]) for q in qs)
    rng = random.Random(seed)
    boots = sorted(fmean(fmean(by_q[rng.choice(qs)]) for _ in qs) for _ in range(draws))
    return est, boots[int(0.025 * draws)], boots[int(0.975 * draws) - 1]


def compare(args):
    one, per = load_grades(args.single), load_grades(args.per_criterion)
    keys = sorted(set(one) & set(per))
    if not keys:
        sys.exit("No answer is graded both ways.")
    modes = {"one prompt": [one[k] for k in keys], "per criterion": [per[k] for k in keys]}
    fields = vo.CRITERIA + ("total",)
    lines = [f"# One prompt against one prompt per criterion\n",
             f"{len({k[0] for k in keys})} answers, {len(keys)} grades graded both ways "
             f"(5 judges, lenient rule: a stray premise score is ignored).\n"]
    table = []

    lines.append("## Scores\n\n| | one prompt | per criterion | difference | r between modes |\n|---|---|---|---|---|")
    for f in fields + ("premise_handling", "hard_fail"):
        pairs = [(one[k][f], per[k][f]) for k in keys
                 if one[k].get(f) is not None and per[k].get(f) is not None]
        if not pairs:
            continue
        xs, ys = [float(p[0]) for p in pairs], [float(p[1]) for p in pairs]
        scale = 100 if f == "hard_fail" else 1
        r = pearson(xs, ys)
        lines.append(f"| {f}{' (%)' if f == 'hard_fail' else ''} | {fmean(xs) * scale:.2f} | "
                     f"{fmean(ys) * scale:.2f} | {(fmean(ys) - fmean(xs)) * scale:+.2f} | "
                     f"{'' if r is None else f'{r:.2f}'} |")
        table.append({"measure": "mean", "field": f, "one": fmean(xs), "per": fmean(ys), "r": r})
    for name, rows in modes.items():
        lines.append(f"\n{name}: {100 * fmean(r['strict'] for r in rows):.1f}% pass the strict check.")

    lines.append("\n## Do the criteria move together?\n")
    lines.append("The mean correlation between the six criteria across grades (15 pairs), and how "
                 "often a judge gives all six the same level. Lower means the criteria are rated "
                 "more independently.\n")
    lines.append("| judge | one prompt: mean r | per criterion: mean r | one prompt: all six equal | "
                 "per criterion: all six equal |\n|---|---|---|---|---|")
    judges = sorted({k[1] for k in keys})
    for j in judges + ["all"]:
        cells = []
        for name, rows in modes.items():
            rs = [r for r in rows if j == "all" or r["judge"] == j]
            cors = [pearson([r[a] for r in rs], [r[b] for r in rs])
                    for i, a in enumerate(vo.CRITERIA) for b in vo.CRITERIA[i + 1:]]
            cors = [c for c in cors if c is not None]
            same = fmean(len({r[c] for c in vo.CRITERIA}) == 1 for r in rs)
            cells.append((fmean(cors) if cors else None, same))
            table.append({"measure": "halo", "field": j, "mode": name,
                          "mean_r": cells[-1][0], "all_equal": same})
        fmt = lambda v: "" if v is None else f"{v:.2f}"
        lines.append(f"| {j} | {fmt(cells[0][0])} | {fmt(cells[1][0])} | "
                     f"{100 * cells[0][1]:.0f}% | {100 * cells[1][1]:.0f}% |")

    lines.append("\n## Do the judges agree? (Krippendorff's alpha, interval)\n")
    lines.append("| | one prompt | per criterion |\n|---|---|---|")
    for f in fields:
        vals = []
        for rows in modes.values():
            units = defaultdict(list)
            for r in rows:
                units[r["id"]].append(r[f])
            vals.append(alpha(list(units.values())))
            table.append({"measure": "alpha", "field": f, "value": vals[-1]})
        lines.append(f"| {f} | {vals[0]:.2f} | {vals[1]:.2f} |")

    lines.append("\n## The gaps\n")
    lines.append("Within question and answering model, averaged over judges, 95% bootstrap "
                 "interval over questions. Out of 24 for the total.\n")
    lines.append("| contrast | measure | one prompt | per criterion |\n|---|---|---|---|")
    contrasts = [
        ("no high school − doctorate", lambda i: i.startswith(EDU_LOW), lambda i: i.startswith(EDU_HIGH)),
        ("placebo − baseline", lambda i: i.startswith("S01-CTRL-"), lambda i: i == "none"),
    ]
    for label, a, b in contrasts:
        for f in ("total", "evidence"):
            cells = []
            for rows in modes.values():
                est, lo, hi = gap(rows, a, b, f)
                cells.append("" if est is None else f"{est:+.2f} [{lo:+.2f}, {hi:+.2f}]")
                table.append({"measure": "gap", "field": f, "contrast": label, "value": est,
                              "lo": lo, "hi": hi})
            lines.append(f"| {label} | {f} | {cells[0]} | {cells[1]} |")

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.out_dir, "compare.jsonl"), "w", encoding="utf-8") as f:
        for t in table:
            f.write(json.dumps(t) + "\n")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("input", help="responses.jsonl")
    j.add_argument("--models", required=True)
    j.add_argument("--out", default="parts-per-criterion.jsonl")
    j.add_argument("--prompts", help="the prompts .xlsx, for the reference answers")
    j.add_argument("--throughput", default="throughput-per-criterion.jsonl")
    j.add_argument("--dry-run", action="store_true", help="print two prompts, load nothing")
    # the same engine flags as vllm_offline.py, so the shell scripts pass $ARGS unchanged
    j.add_argument("--chunk", type=int, default=5000)
    j.add_argument("--reasoning", choices=["low", "medium"])
    j.add_argument("--judge-tokens", type=int)
    j.add_argument("--tensor-parallel-size", type=int, default=1)
    j.add_argument("--gpu-memory-utilization", type=float, default=0.92)
    j.add_argument("--max-model-len", type=int)
    j.add_argument("--max-num-seqs", type=int)
    j.add_argument("--max-num-batched-tokens", type=int)
    j.add_argument("--engine-config")
    j.add_argument("--engine")
    a = sub.add_parser("assemble")
    a.add_argument("input", help="the parts file from judge")
    a.add_argument("--out", default="judgments-per-criterion.jsonl")
    c = sub.add_parser("compare")
    c.add_argument("single", help="one-prompt judgments of the same answers")
    c.add_argument("per_criterion", help="assembled per-criterion judgments")
    c.add_argument("--out-dir", default="per-criterion-analysis")
    args = p.parse_args()
    if args.cmd == "judge":
        args.shard = "0/1"
        vo.verify_drift()
        judge(args)
    elif args.cmd == "assemble":
        assemble(args)
    else:
        compare(args)


if __name__ == "__main__":
    main()
