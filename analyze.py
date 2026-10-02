#!/usr/bin/env python3
"""Analyze merged grades without calling APIs.

    python analyze.py judgments.jsonl --responses responses.jsonl --out-dir analysis

Means weight each question equally. Intervals resample whole questions.
Hard fails remain in raw score summaries and have a separate failure rate.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import fmean, stdev


CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
METRICS = (*CRITERIA, "total", "hard_fail", "premise_handling")


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{n}: expected a JSON object")
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows


def answer_key(row: dict) -> tuple:
    if not isinstance(row.get("id"), str):
        raise ValueError("answer id must be a string")
    parts = str(row.get("id", "")).split("|")
    if (len(parts) != 5 or not all(parts) or parts[1] not in ("pos", "neg")
            or not parts[4].isascii() or not parts[4].isdigit()
            or str(int(parts[4])) != parts[4]):
        raise ValueError(f"malformed answer id: {row.get('id')!r}")
    for name, value in zip(("qid", "polarity", "identity", "provider"), parts[:4]):
        if row.get(name) != value:
            raise ValueError(f"{row['id']}: inconsistent {name}")
    return (*parts[:4], int(parts[4]))


def invalid_grade(row: dict) -> str | None:
    if row.get("error") is not None:
        return "provider_or_parser_error"
    if any(type(row.get(k)) is not int or not 1 <= row[k] <= 5 for k in CRITERIA):
        return "invalid_scores"
    if row.get("total") != sum(row[k] for k in CRITERIA):
        return "invalid_total"
    if type(row.get("hard_fail")) is not bool:
        return "invalid_hard_fail"
    premise = row.get("premise_handling")
    loaded = str(row.get("question_type", "")).startswith("Loaded")
    if loaded and (type(premise) is not int or not 1 <= premise <= 5):
        return "invalid_premise_handling"
    if not loaded and premise is not None:
        return "unexpected_premise_handling"
    return None


def load_grades(path: Path) -> tuple[list[dict], dict]:
    source = read_rows(path)
    run_ids = {row.get("run_id") for row in source}
    if len(run_ids) > 1:
        raise ValueError("mixed run IDs or tagged and untagged rows; analyze runs separately")
    valid, excluded, seen = [], Counter(), set()
    models, types = defaultdict(set), defaultdict(set)
    for row in source:
        answer_key(row)
        if not isinstance(row.get("judge"), str) or not row["judge"]:
            raise ValueError(f"{row['id']}: missing judge")
        row.setdefault("pass", 0)
        if type(row["pass"]) is not int or row["pass"] < 0:
            raise ValueError(f"{row['id']}: invalid pass")
        key = (row["id"], row["judge"], row["pass"])
        if key in seen:
            raise ValueError(f"duplicate judgment {key}; merge retries before analysis")
        seen.add(key)
        reason = invalid_grade(row)
        if reason:
            excluded[reason] += 1
            continue
        valid.append(row)
        models[row["judge"]].add(row.get("judge_model"))
        types[(row["qid"], row["polarity"])].add(row.get("question_type", "Unspecified"))
    if any(len(v) > 1 for v in models.values()):
        raise ValueError("multiple model versions for one judge; analyze runs separately")
    if any(len(v) > 1 for v in types.values()):
        raise ValueError("inconsistent question types for the same question and polarity")
    if not valid:
        raise ValueError("no usable judgments")
    return valid, {"rows_read": len(source), "valid_grades": len(valid), "run_id": next(iter(run_ids)),
                   "excluded": dict(excluded), "judge_models": {k: next(iter(v)) for k, v in models.items()}}


def estimate(clusters: dict[str, list[float]], draws: int, seed: int) -> dict:
    means = [fmean(clusters[k]) for k in sorted(clusters) if clusters[k]]
    if not means:
        return dict(mean=None, ci_low=None, ci_high=None, n_questions=0, n_observations=0)
    result = dict(mean=fmean(means), ci_low=None, ci_high=None,
                  n_questions=len(means), n_observations=sum(map(len, clusters.values())))
    if len(means) > 1:
        rng = random.Random(seed)
        boot = sorted(fmean(rng.choices(means, k=len(means))) for _ in range(draws))
        def quantile(p: float) -> float:
            index = (len(boot) - 1) * p
            lo = int(index)
            hi = min(lo + 1, len(boot) - 1)
            return boot[lo] + (boot[hi] - boot[lo]) * (index - lo)
        result.update(ci_low=quantile(.025), ci_high=quantile(.975))
    return result


def group_summary(rows: list[dict], fields: tuple[str, ...], draws: int, seed: int) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k) or "Unspecified" for k in fields)].append(row)
    output = []
    for key, group in sorted(groups.items()):
        for metric in METRICS:
            clusters = defaultdict(list)
            for row in group:
                if row.get(metric) is not None:
                    clusters[row["qid"]].append(float(row[metric]))
            output.append(dict(zip(fields, key)) | {"metric": metric} | estimate(clusters, draws, seed))
    return output


def paired_comparisons(rows: list[dict], dimension: str, draws: int, seed: int) -> list[dict]:
    values = sorted({r[dimension] for r in rows})
    pairs = ([("none", x) for x in values if x != "none"] if dimension == "identity" and "none" in values
             else list(combinations(values, 2)) if dimension == "provider" else [])
    matched = defaultdict(dict)
    for row in rows:
        qid, polarity, identity, provider, run = answer_key(row)
        # Preserve judge, pass, polarity, and replicate when matching contrasts.
        key = (qid, polarity, run, row["judge"], row["pass"],
               provider if dimension == "identity" else identity)
        matched[key][row[dimension]] = row
    output = []
    for baseline, comparison in pairs:
        for metric in METRICS:
            clusters = defaultdict(list)
            unmatched = 0
            for key, members in matched.items():
                a, b = members.get(baseline), members.get(comparison)
                if a is None or b is None:
                    unmatched += int(a is not None or b is not None)
                    continue
                if a.get(metric) is not None and b.get(metric) is not None:
                    clusters[key[0]].append(float(b[metric]) - float(a[metric]))
            output.append(dict(baseline=baseline, comparison=comparison, metric=metric,
                               unmatched_cells=unmatched) | estimate(clusters, draws, seed))
    return output


def self_preference(rows: list[dict], draws: int, seed: int) -> list[dict]:
    answers = defaultdict(lambda: defaultdict(list))
    for row in rows:
        answers[row["id"]][row["judge"]].append(row["total"])
    clusters = defaultdict(lambda: defaultdict(list))
    for answer_id, judges in answers.items():
        qid, _, _, provider, _ = answer_id.split("|")
        others = [fmean(scores) for judge, scores in judges.items() if judge != provider]
        if provider in judges and others:
            clusters[provider][qid].append(fmean(judges[provider]) - fmean(others))
    return [dict(provider=provider, metric="self_minus_other_judges_total")
            | estimate(group, draws, seed) for provider, group in sorted(clusters.items())]


def replicate_variability(rows: list[dict]) -> list[dict]:
    groups = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        qid, polarity, identity, provider, run = answer_key(row)
        groups[(qid, polarity, identity, provider)][run][(row["judge"], row["pass"])] = row["total"]
    output = []
    for key, runs in sorted(groups.items()):
        common = set.intersection(*(set(panel) for panel in runs.values()))
        scores = [fmean(panel[j] for j in sorted(common)) for panel in runs.values()] if common else []
        output.append(dict(zip(("qid", "polarity", "identity", "provider"), key)) | dict(
            n_replicates=len(runs), n_common_judge_passes=len(common),
            mean_total=fmean(scores) if scores else None,
            sd_total=stdev(scores) if len(scores) > 1 else None))
    return output


def coverage(rows: list[dict], responses: Path | None) -> dict:
    panels = defaultdict(set)
    observed_panel = {(r["judge"], r["pass"]) for r in rows}
    for row in rows:
        panels[row["id"]].add((row["judge"], row["pass"]))
    result = dict(judged_answers=len(panels),
                  answers_missing_observed_panel=sum(panel != observed_panel for panel in panels.values()),
                  observed_panel=[list(p) for p in sorted(observed_panel)])
    if responses:
        answers = read_rows(responses)
        if {r.get("run_id") for r in answers} != {r.get("run_id") for r in rows}:
            raise ValueError("response and judgment run IDs differ")
        by_id = {r["id"]: r for r in rows}
        seen, usable = set(), set()
        models = defaultdict(set)
        for row in answers:
            answer_key(row)
            if row["id"] in seen:
                raise ValueError("duplicate response ids; merge retries before analysis")
            seen.add(row["id"])
            if row["id"] in by_id and row.get("question_type") != by_id[row["id"]].get("question_type"):
                raise ValueError(f"{row['id']}: response and judgment question types differ")
            if row.get("error") is None and isinstance(row.get("response"), str) and row["response"].strip():
                usable.add(row["id"])
                models[row["provider"]].add(row.get("model"))
        if any(len(v) > 1 for v in models.values()):
            raise ValueError("multiple answering model versions; analyze runs separately")
        if set(panels) - usable:
            raise ValueError("judgments refer to absent or failed responses")
        result.update(response_rows=len(answers), usable_responses=len(usable),
                      unjudged_answers=len(usable - set(panels)), failed_responses=len(seen - usable),
                      answer_models={k: next(iter(v)) for k, v in models.items()})
    return result


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("judgments", type=Path)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("analysis"))
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261002)
    args = parser.parse_args()
    if args.bootstrap < 100:
        parser.error("--bootstrap must be at least 100")
    try:
        rows, summary = load_grades(args.judgments)
        summary["coverage"] = coverage(rows, args.responses)
        summary.update(n_questions=len({r["qid"] for r in rows}), bootstrap_draws=args.bootstrap,
                       seed=args.seed, confidence=.95,
                       method="Equal question means; percentile bootstrap resamples whole questions.",
                       score_policy="Raw rubric totals, including hard fails; hard_fail is a separate rate.",
                       judgments_sha256=hashlib.sha256(args.judgments.read_bytes()).hexdigest())
        if args.responses:
            summary["responses_sha256"] = hashlib.sha256(args.responses.read_bytes()).hexdigest()
        summary["warnings"] = []
        if summary["n_questions"] < 20:
            summary["warnings"].append("Fewer than 20 question clusters; treat intervals as exploratory.")
        if summary["excluded"]:
            summary["warnings"].append("Unusable grades excluded; inspect exclusion counts and coverage.")
        cov = summary["coverage"]
        if cov["answers_missing_observed_panel"] or cov.get("unjudged_answers") or cov.get("failed_responses"):
            summary["warnings"].append("Incomplete observed panel or responses; comparisons may use different subsets.")
        if not args.responses:
            summary["warnings"].append("No responses supplied; completely unjudged answers cannot be counted.")
        if "none" not in {r["identity"] for r in rows}:
            summary["warnings"].append("No control identity; identity contrasts are unavailable.")
        tables = {f"by_{field}.csv": group_summary(rows, (field,), args.bootstrap, args.seed)
                  for field in ("provider", "identity", "question_type", "judge", "polarity")}
        tables["judge_matrix.csv"] = group_summary(rows, ("provider", "judge"), args.bootstrap, args.seed)
        tables["identity_differences.csv"] = paired_comparisons(rows, "identity", args.bootstrap, args.seed)
        tables["model_differences.csv"] = paired_comparisons(rows, "provider", args.bootstrap, args.seed)
        tables["self_preference.csv"] = self_preference(rows, args.bootstrap, args.seed)
        tables["replicate_variability.csv"] = replicate_variability(rows)
        inputs = {p.resolve() for p in (args.judgments, args.responses) if p}
        if any((args.out_dir / name).resolve() in inputs for name in (*tables, "summary.json")):
            raise ValueError("output would overwrite an input")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for name, table in tables.items():
            write_csv(args.out_dir / name, table)
        (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n",
                                                encoding="utf-8")
        print(f"{summary['valid_grades']} usable grades, {summary['n_questions']} questions -> {args.out_dir}")
        for warning in summary["warnings"]:
            print(f"WARNING: {warning}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
