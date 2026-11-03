#!/usr/bin/env python3
"""Tune vLLM's engine settings for each model, as judge and as answerer.

    python vllm_tune.py                       # every model, both stages, about 5 hours
    python vllm_tune.py --stages judge        # grading only (90% of a cue run's time)
    python vllm_tune.py --models Qwen/Qwen3.8-27B
    python vllm_tune.py --summary             # rewrite the report and vllm-engine.json from what ran

Each trial is a real vllm_offline.py run on a fixed sample, changing one engine
setting at a time from the settings the runs use now, timed by vllm_offline's
own throughput record (load time excluded). Judging is timed on October
answers graded on the current rubric; answering on the subset questions under
ten cues. Trials go to tune/; nothing in a run's files is touched.

The fastest setting that changes only speed, and beats the current one by 3% or
more without losing usable grades, goes to vllm-engine.json, which the run
scripts read. FP8 KV cache is timed but never chosen: it changes the
arithmetic, so it is for Dr. Aryal to accept, by hand. Speculative decoding
keeps the sampling distribution, so it counts as speed only. A setting this
vLLM or model does not support fails its trial and is skipped.

Why it matters, from the 21 October run (114 hours): grading took 103. Qwen
alone took 54 of those, decoding about 1,250 tokens per grade (1,170 of them
thinking), so decode settings matter for it. The other judges write 70-200
tokens and spend their time reading the 1,650-token prompt, near the GPUs'
limit, so expect less from them.
"""

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from statistics import fmean

MODELS = ("Qwen/Qwen3.8-27B", "RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16",
          "allenai/Olmo-3.1-32B-Instruct", "google/gemma-4-31B-it", "openai/gpt-oss-120b")
# the settings every run script uses now
BASE = ["--tensor-parallel-size", "2", "--max-model-len", "8192", "--reasoning", "low",
        "--gpu-memory-utilization", "0.95", "--max-num-seqs", "512",
        "--max-num-batched-tokens", "32768", "--chunk", "10000"]
NGRAM = {"speculative_config": {"method": "ngram", "num_speculative_tokens": 4, "prompt_lookup_max": 4}}
MTP = {"speculative_config": {"method": "mtp", "num_speculative_tokens": 2}}
# variant: (engine settings, speed only?)
VARIANTS = {
    "base": ({}, True),
    "seqs-256": ({"max_num_seqs": 256}, True),
    "seqs-1024": ({"max_num_seqs": 1024}, True),
    "batched-16k": ({"max_num_batched_tokens": 16384}, True),
    "batched-64k": ({"max_num_batched_tokens": 65536}, True),
    "spec-ngram": (NGRAM, True),
    "spec-mtp": (MTP, True),
    "kv-fp8": ({"kv_cache_dtype": "fp8"}, False),
}
# decode-heavy work tries decode settings; prefill-heavy grading tries prefill ones
DECODE = ("base", "seqs-1024", "batched-64k", "spec-ngram", "spec-mtp", "kv-fp8")
PREFILL = ("base", "batched-16k", "batched-64k", "seqs-1024")
PLAN = {("judge", "Qwen/Qwen3.8-27B"): DECODE}
ANSWER_PLAN = ("base", "seqs-1024", "spec-ngram")
# trial size: about six minutes each at 21 October rates; Qwen grades slowly, but
# needs enough prompts in flight for its batch to fill
JUDGE_N = {"Qwen/Qwen3.8-27B": 400, "openai/gpt-oss-120b": 1500}
JUDGE_DEFAULT_N = 600
ANSWER_CUES = 10   # x 32 subset questions = 320 answers per trial
SAVED = ("cues-responses.jsonl", "runs/cues-vllm-2026-10-21/cues-responses.jsonl")
T = Path("tune")


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def samples():
    """A fixed sample of October answers to grade, and the answering inputs."""
    T.mkdir(exist_ok=True)
    answers = T / "answers.jsonl"
    if not answers.exists():
        src = next((p for p in SAVED if os.path.exists(p)), None)
        if not src:
            sys.exit("no October answers (cues-responses.jsonl) to grade")
        rows = [r for r in read(src) if r.get("error") is None and (r.get("response") or "").strip()]
        pick = random.Random(20261103).sample(rows, max(JUDGE_N.values()))
        answers.write_text("".join(json.dumps(r) + "\n" for r in pick), encoding="utf-8")
    cues = T / "cues.jsonl"
    if not cues.exists():
        rows = read("cues.jsonl")
        pick = random.Random(20261103).sample(rows, ANSWER_CUES)
        cues.write_text("".join(json.dumps(dict(c, runs=1)) + "\n" for c in pick), encoding="utf-8")
    return answers, cues


def trial(stage, model, variant, answers, cues):
    out = T / f"{stage}-{model.split('/')[-1]}-{variant}.jsonl"
    out.unlink(missing_ok=True)
    engine = VARIANTS[variant][0]
    cmd = [sys.executable, "vllm_offline.py", stage]
    if stage == "judge":
        n = JUDGE_N.get(model, JUDGE_DEFAULT_N)
        cmd += [str(answers), "--prompts", "samples/prompts-2026-10-20.xlsx", "--limit", str(n)]
    else:
        cmd += ["samples/prompts-subset.xlsx", "--cues", str(cues)]
    cmd += ["--models", model, "--out", str(out), "--throughput", str(T / "throughput.jsonl"), *BASE]
    if engine:
        cmd += ["--engine", json.dumps(engine)]
    print(f"\n== {stage} {model} {variant}", flush=True)
    before = len(read(T / "throughput.jsonl")) if (T / "throughput.jsonl").exists() else 0
    with open(T / "trials.log", "a", encoding="utf-8") as log:
        code = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    records = read(T / "throughput.jsonl") if (T / "throughput.jsonl").exists() else []
    record = records[-1] if len(records) > before else None
    rows = read(out) if out.exists() else []
    ok = [r for r in rows if r.get("error") is None]
    result = {"stage": stage, "model": model, "variant": variant, "engine": engine,
              "speed_only": VARIANTS[variant][1], "exit": code,
              "prompts_per_second": record and record["prompts_per_second"],
              "output_tokens_per_second": record and record["output_tokens_per_second"],
              "rows": len(rows), "usable_share": round(len(ok) / len(rows), 3) if rows else None,
              "mean_total": round(fmean(r["total"] for r in ok), 3) if stage == "judge" and ok else None,
              "mean_output_tokens": round(fmean(r.get("output_tokens") or 0 for r in rows), 1) if rows else None}
    with open(T / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
    speed = result["prompts_per_second"]
    print(f"   {'failed' if speed is None else f'{speed} prompts/s'}, usable {result['usable_share']}", flush=True)


def summarise():
    results = {}
    for r in read(T / "results.jsonl") if (T / "results.jsonl").exists() else []:
        results[r["stage"], r["model"], r["variant"]] = r   # the latest trial of each counts
    config, lines = {}, ["# Engine tuning", "",
                         "Prompts per second on each trial, load time excluded. **Chosen** goes to "
                         "vllm-engine.json. FP8 KV cache is never chosen automatically.", "",
                         "| stage | model | setting | prompts/s | vs base | usable | mean total | output tok | |",
                         "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for stage, model in sorted({(s, m) for s, m, _ in results}):
        trials = {v: r for (s, m, v), r in results.items() if (s, m) == (stage, model)}
        base = trials.get("base")
        best = None
        if base and base["prompts_per_second"]:
            for v, r in trials.items():
                good = (r["speed_only"] and r["prompts_per_second"] and v != "base"
                        and r["prompts_per_second"] >= 1.03 * base["prompts_per_second"]
                        and (r["usable_share"] or 0) >= (base["usable_share"] or 0) - 0.02)
                if good and (best is None or r["prompts_per_second"] > trials[best]["prompts_per_second"]):
                    best = v
        if best:
            config.setdefault(model, {})[stage] = trials[best]["engine"]
        for v, r in sorted(trials.items(), key=lambda kv: -(kv[1]["prompts_per_second"] or 0)):
            ratio = (f"{r['prompts_per_second'] / base['prompts_per_second']:.2f}x"
                     if base and base["prompts_per_second"] and r["prompts_per_second"] else "")
            mark = "**chosen**" if v == best else ("" if r["speed_only"] else "not speed-only")
            lines.append(f"| {stage} | {model.split('/')[-1]} | {v} | {r['prompts_per_second'] or 'failed'} | "
                         f"{ratio} | {r['usable_share']} | {r['mean_total'] or ''} | {r['mean_output_tokens']} | {mark} |")
    Path("vllm-engine.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (T / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote vllm-engine.json ({sum(len(v) for v in config.values())} tuned model x stage) "
          f"and {T / 'report.md'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=",".join(MODELS))
    p.add_argument("--stages", default="judge,answer")
    p.add_argument("--summary", action="store_true", help="only rewrite the report and vllm-engine.json")
    args = p.parse_args()
    if not args.summary:
        answers, cues = samples()
        done = {(r["stage"], r["model"], r["variant"]) for r in read(T / "results.jsonl")} \
            if (T / "results.jsonl").exists() else set()
        for stage in args.stages.split(","):
            for model in args.models.split(","):
                plan = PLAN.get((stage, model), PREFILL) if stage == "judge" else ANSWER_PLAN
                for variant in plan:
                    if (stage, model, variant) not in done:   # rerun to resume
                        trial(stage, model, variant, answers, cues)
    summarise()


if __name__ == "__main__":
    main()
