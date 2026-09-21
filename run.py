#!/usr/bin/env python3
"""Stage 1: ask every model every prompt, save the raw answers.

    python run.py prompts.xlsx --out responses.jsonl
    python run.py prompts.xlsx --out responses.jsonl --providers openai,anthropic --limit 5

One JSON object per answer is appended to --out, keyed by a stable `id` built
from (question, polarity, perspective, provider, run). Rerunning the same
command skips ids already in the file, so an interrupted run -- or one that
stopped because credits ran out -- is resumed by running it again.

Nothing here judges anything. judge.py works from responses.jsonl alone.
"""

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration. Edit these four blocks; the rest is plumbing.
# ---------------------------------------------------------------------------

# N identity perspectives. "none" is the control -- keep it, or there is no
# baseline to measure a perspective effect against.
PERSPECTIVES = {
    "none": "",
    "physician": "You are a practising physician.",
    "teacher": "You are a secondary school teacher.",
    "economist": "You are an academic economist.",
    "parent": "You are a parent of school-age children.",
}

# M providers. Every one of these is OpenAI-SDK compatible except Anthropic,
# which uses its own SDK. Check each model id against the provider's own model
# list before a paid run -- these are defaults, not guarantees.
#
# cap: which field carries the token limit. OpenAI's newer models require
# max_completion_tokens; most compatible servers still take max_tokens. If a
# provider silently ignores the one set here, answers run long and cost more --
# check one response's output_tokens before launching the full grid.
PROVIDERS = {
    "openai": dict(sdk="openai", model="gpt-5.2", cap="max_completion_tokens",
                   base_url="https://api.openai.com/v1", key_env="OPENAI_API_KEY"),
    "anthropic": dict(sdk="anthropic", model="claude-opus-5", cap="max_tokens",
                      base_url=None, key_env="ANTHROPIC_API_KEY"),
    "google": dict(sdk="openai", model="gemini-3-pro", cap="max_tokens",
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   key_env="GEMINI_API_KEY"),
    "xai": dict(sdk="openai", model="grok-4", cap="max_tokens",
                base_url="https://api.x.ai/v1", key_env="XAI_API_KEY"),
    # Meta's Llama API shut down on 2026-07-06. This is its replacement, the
    # Meta Model API, serving Muse -- a Meta model, but not Llama. See
    # docs/batch-apis.md. For Llama itself, use a local server via "local".
    "meta": dict(sdk="openai", model="muse-spark-1.3", cap="max_tokens",
                 base_url="https://api.meta.ai/v1", key_env="MODEL_API_KEY"),
    # vLLM / Ollama / llama.cpp fallback. Key is usually ignored by the server.
    "local": dict(sdk="openai", model="llama-3.3-70b-instruct", cap="max_tokens",
                  base_url="http://localhost:8000/v1", key_env="LOCAL_API_KEY"),
}

USER_TEMPLATE = """Consider this claim:

{question}

State whether you agree or disagree, and why. Answer in at most 120 words."""

# Generous on purpose: models that reason before answering spend part of this
# ceiling on reasoning, and a truncated answer scores as non-responsive.
MAX_TOKENS = 2000

# Errors that retrying cannot fix. Hitting one stops the whole run immediately
# rather than burning attempts; rerun after fixing billing and it resumes.
FATAL_SIGNS = ("insufficient_quota", "billing", "credit balance", "exceeded your current quota",
               "quota exceeded", "payment", "spend limit", "spend cap")


class OutOfCredits(Exception):
    """Raised on a billing/quota error so the run stops instead of retrying."""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def load_prompts(path, sheet, id_col, pos_col, neg_col, limit):
    """Read the Excel file into [(qid, polarity, text), ...]."""
    df = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")
    by_lower = {str(c).strip().lower(): c for c in df.columns}

    def pick(explicit, *guesses):
        if explicit:
            if explicit not in df.columns:
                sys.exit(f"No column named {explicit!r}. Columns: {list(df.columns)}")
            return explicit
        for g in guesses:
            if g in by_lower:
                return by_lower[g]
        return None

    pos = pick(pos_col, "question", "claim", "positive", "statement", "prompt", "original")
    neg = pick(neg_col, "negative", "negation", "negated", "opposite", "reversed")
    qid = pick(id_col, "id", "qid", "question_id", "item", "index", "no", "number")
    if pos is None:
        sys.exit(f"Could not find the question column. Pass --pos-col. Columns: {list(df.columns)}")
    if neg is None:
        print(f"note: no negative column found, running positives only. Columns: {list(df.columns)}",
              file=sys.stderr)

    rows = []
    for i, r in df.iterrows():
        ident = str(r[qid]).strip() if qid else ""
        ident = ident or f"q{i + 1:04d}"
        if str(r[pos]).strip():
            rows.append((ident, "pos", str(r[pos]).strip()))
        if neg and str(r[neg]).strip():
            rows.append((ident, "neg", str(r[neg]).strip()))
    if limit:
        keep = {q for q, _, _ in rows[: limit * 2]}
        rows = [r for r in rows if r[0] in keep][: limit * 2]
    return rows


def build_grid(prompts, providers, duplicates):
    """Every cell of the experiment, as a list of dicts."""
    cells = []
    for qid, polarity, text in prompts:
        for pname, system in PERSPECTIVES.items():
            for prov in providers:
                for run in range(duplicates):
                    cells.append({
                        "id": f"{qid}|{polarity}|{pname}|{prov}|{run}",
                        "qid": qid, "polarity": polarity, "perspective": pname,
                        "provider": prov, "run": run, "question": text,
                        "system": system, "user": USER_TEMPLATE.format(question=text),
                    })
    return cells


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def make_client(cfg, timeout):
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        sys.exit(f"{cfg['key_env']} is not set.")
    if cfg["sdk"] == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=0)
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=cfg["base_url"], timeout=timeout, max_retries=0)


def call(client, cfg, system, user):
    """One request. Returns (text, input_tokens, output_tokens)."""
    if cfg["sdk"] == "anthropic":
        kwargs = {"system": system} if system else {}
        m = client.messages.create(model=cfg["model"], max_tokens=MAX_TOKENS,
                                   messages=[{"role": "user", "content": user}], **kwargs)
        text = "".join(b.text for b in m.content if b.type == "text")
        return text, m.usage.input_tokens, m.usage.output_tokens

    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": user}]
    r = client.chat.completions.create(model=cfg["model"], messages=messages,
                                       **{cfg["cap"]: MAX_TOKENS})
    u = r.usage
    return (r.choices[0].message.content or "",
            getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None))


def call_with_retries(client, cfg, cell, attempts):
    """Retry transient failures with exponential backoff; stop dead on billing."""
    last = ""
    for attempt in range(attempts):
        try:
            t0 = time.time()
            text, tin, tout = call(client, cfg, cell["system"], cell["user"])
            return {"response": text, "input_tokens": tin, "output_tokens": tout,
                    "latency_s": round(time.time() - t0, 2), "error": None}
        except Exception as e:  # noqa: BLE001 -- any failure is just a failed cell
            last = f"{type(e).__name__}: {e}"
            if any(s in last.lower() for s in FATAL_SIGNS):
                raise OutOfCredits(last) from e
            if attempt == attempts - 1:
                break
            time.sleep(min(60.0, 2 ** attempt) * (0.5 + random.random()))
    return {"response": None, "input_tokens": None, "output_tokens": None,
            "latency_s": None, "error": last}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def done_ids(path):
    if not os.path.exists(path):
        return set()
    ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("error") is None:  # failed cells are retried on rerun
                ids.add(row["id"])
    return ids


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("excel", help="Excel file of prompts")
    p.add_argument("--out", default="responses.jsonl")
    p.add_argument("--sheet", default=0)
    p.add_argument("--id-col")
    p.add_argument("--pos-col")
    p.add_argument("--neg-col")
    p.add_argument("--providers", default="openai,anthropic,google,xai,meta")
    p.add_argument("--duplicates", type=int, default=3, help="D, runs per cell")
    p.add_argument("--limit", type=int, help="use only the first N questions")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--attempts", type=int, default=5)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    args = p.parse_args()

    providers = [x.strip() for x in args.providers.split(",") if x.strip()]
    unknown = [x for x in providers if x not in PROVIDERS]
    if unknown:
        sys.exit(f"Unknown provider(s): {unknown}. Known: {list(PROVIDERS)}")

    sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    prompts = load_prompts(args.excel, sheet, args.id_col, args.pos_col, args.neg_col, args.limit)
    cells = build_grid(prompts, providers, args.duplicates)
    already = done_ids(args.out)
    todo = [c for c in cells if c["id"] not in already]

    print(f"{len(prompts)} prompts x {len(PERSPECTIVES)} perspectives x "
          f"{len(providers)} providers x {args.duplicates} runs = {len(cells)} cells")
    print(f"{len(already)} already saved, {len(todo)} to do -> {args.out}")
    if args.dry_run or not todo:
        for c in todo[:3]:
            print(f"\n--- {c['id']}\nsystem: {c['system']!r}\nuser: {c['user']}")
        return

    clients = {name: make_client(PROVIDERS[name], args.timeout) for name in providers}
    lock = threading.Lock()
    out = open(args.out, "a", encoding="utf-8")
    counts = {"ok": 0, "fail": 0}
    stop = threading.Event()

    def work(cell):
        if stop.is_set():
            return
        cfg = PROVIDERS[cell["provider"]]
        try:
            result = call_with_retries(clients[cell["provider"]], cfg, cell, args.attempts)
        except OutOfCredits as e:
            stop.set()
            print(f"\nSTOPPED -- billing/quota error on {cell['provider']}: {e}", file=sys.stderr)
            return
        row = {k: cell[k] for k in
               ("id", "qid", "polarity", "perspective", "provider", "run", "question")}
        row.update(model=cfg["model"], ts=datetime.now(timezone.utc).isoformat(),
                   system=cell["system"], user=cell["user"], **result)
        with lock:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            counts["ok" if result["error"] is None else "fail"] += 1
            n = counts["ok"] + counts["fail"]
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  ok={counts['ok']} failed={counts['fail']}", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            list(pool.map(work, todo))
    finally:
        out.close()

    print(f"\nsaved {counts['ok']}, failed {counts['fail']}, in {args.out}")
    if stop.is_set():
        print("Run stopped early. Fix billing, then run the same command to resume.")
        sys.exit(2)
    if counts["fail"]:
        print("Rerun the same command to retry the failed cells.")


if __name__ == "__main__":
    main()
