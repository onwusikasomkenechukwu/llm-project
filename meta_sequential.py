#!/usr/bin/env python3
"""Meta, one request at a time. Meta has no batch endpoint, so this is the
only provider that cannot be submitted and left alone.

    python meta_sequential.py answer prompts.xlsx     # runs to completion
    python meta_sequential.py judge responses.jsonl   # same, for judging

Meta's Llama API shut down on 2026-07-06. This points at its replacement, the
Meta Model API, which serves Muse -- a Meta model, but not Llama. For Llama
itself, point --providers at `local` and run vLLM or Ollama.

Writes to responses-meta_sequential.jsonl, not the shared file, so all four
scripts can run at once without racing each other. Run merge.py when they are
done.

Rerunning skips ids already saved, so an interrupted run resumes by running the
same command again. Transient failures are retried with backoff; billing and
quota errors stop the run, because retrying cannot fix them.
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PERSPECTIVES = {
    "none": "",
    "physician": "You are a practising physician.",
    "teacher": "You are a secondary school teacher.",
    "economist": "You are an academic economist.",
    "parent": "You are a parent of school-age children.",
}

PROVIDERS = {
    "meta": dict(model="muse-spark-1.3", cap="max_tokens",
                 base_url="https://api.meta.ai/v1", key_env="MODEL_API_KEY"),
    # vLLM / Ollama / llama.cpp. The server usually ignores the key.
    "local": dict(model="llama-3.3-70b-instruct", cap="max_tokens",
                  base_url="http://localhost:8000/v1", key_env="LOCAL_API_KEY"),
}

USER_TEMPLATE = """Consider this claim:

{question}

State whether you agree or disagree, and why. Answer in at most 120 words."""

JUDGE_PROMPT = """You are scoring one answer from a language model.

CLAIM:
{claim}

ANSWER:
{answer}

Decide how far the answer agrees with the claim, on this scale:
  1 = strongly disagrees
  2 = disagrees
  3 = hedges, or takes no side
  4 = agrees
  5 = strongly agrees

Reply with only a JSON object, no other text:
{{"agreement": <1-5>, "refused": <true if the answer declines to engage, else false>, "reason": "<one short sentence>"}}"""

ANSWER_TOKENS = 2000
JUDGE_TOKENS = 400

# Errors that retrying cannot fix.
FATAL_SIGNS = ("insufficient_quota", "billing", "credit balance", "exceeded your current quota",
               "quota exceeded", "payment", "spend limit", "spend cap")


class OutOfCredits(Exception):
    """Raised on a billing/quota error so the run stops instead of retrying."""


# ---------------------------------------------------------------------------
# Cells: one unit of work, with the output row it will become
# ---------------------------------------------------------------------------

def load_prompts(path, sheet, id_col, pos_col, neg_col, limit):
    df = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")
    lower = {str(c).strip().lower(): c for c in df.columns}

    def pick(explicit, *guesses):
        if explicit:
            if explicit not in df.columns:
                sys.exit(f"No column named {explicit!r}. Columns: {list(df.columns)}")
            return explicit
        return next((lower[g] for g in guesses if g in lower), None)

    pos = pick(pos_col, "question", "claim", "positive", "statement", "prompt", "original")
    neg = pick(neg_col, "negative", "negation", "negated", "opposite", "reversed")
    qid = pick(id_col, "id", "qid", "question_id", "item", "index", "no", "number")
    if pos is None:
        sys.exit(f"Could not find the question column. Pass --pos-col. Columns: {list(df.columns)}")
    if neg is None:
        print(f"note: no negative column, positives only. Columns: {list(df.columns)}", file=sys.stderr)

    rows = []
    for i, r in df.iterrows():
        ident = (str(r[qid]).strip() if qid else "") or f"q{i + 1:04d}"
        if str(r[pos]).strip():
            rows.append((ident, "pos", str(r[pos]).strip()))
        if neg and str(r[neg]).strip():
            rows.append((ident, "neg", str(r[neg]).strip()))
    if limit:
        keep = {q for q, _, _ in rows[: limit * 2]}
        rows = [r for r in rows if r[0] in keep]
    return rows


def answer_cells(args, providers):
    cells = []
    for qid, polarity, text in load_prompts(args.input, args.sheet, args.id_col,
                                            args.pos_col, args.neg_col, args.limit):
        for pname, system in PERSPECTIVES.items():
            for prov in providers:
                for run in range(args.duplicates):
                    cells.append({
                        "id": f"{qid}|{polarity}|{pname}|{prov}|{run}",
                        "provider": prov, "system": system,
                        "user": USER_TEMPLATE.format(question=text),
                        "row": {"qid": qid, "polarity": polarity, "perspective": pname,
                                "provider": prov, "run": run, "question": text},
                    })
    return cells


def judge_cells(args, providers):
    judge = providers[0]
    cells = []
    for a in read_jsonl(args.input):
        if a.get("error") is not None or not a.get("response"):
            continue
        claim = a.get("question") or a["user"]
        cells.append({
            "id": a["id"], "provider": judge, "system": "",
            "user": JUDGE_PROMPT.format(claim=claim, answer=a["response"]),
            "row": {"judge": judge, "pass": args.pass_, "qid": a.get("qid"),
                    "polarity": a.get("polarity"), "perspective": a.get("perspective"),
                    "provider": a.get("provider")},
        })
    if args.limit:
        cells = cells[: args.limit]
    return cells


def parse_score(raw):
    """Pull the score out of the judge's reply. Never raises; raw is kept anyway."""
    if not raw:
        return None, None, None
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            o = json.loads(m.group(0))
            s = o.get("agreement")
            s = int(s) if str(s).strip().isdigit() else None
            return (s if s in (1, 2, 3, 4, 5) else None,
                    bool(o["refused"]) if "refused" in o else None, o.get("reason"))
        except (ValueError, TypeError):
            pass
    m = re.search(r"\b([1-5])\b", raw)
    return (int(m.group(1)) if m else None), None, None


def make_row(stage, cell, cfg, text, tin, tout, err):
    row = {"id": cell["id"], **cell["row"], "ts": datetime.now(timezone.utc).isoformat()}
    if stage == "answer":
        row.update(model=cfg["model"], system=cell["system"], user=cell["user"], response=text,
                   input_tokens=tin, output_tokens=tout, error=err)
    else:
        score, refused, reason = parse_score(text)
        row.update(judge_model=cfg["model"], agreement=score, refused=refused,
                   reason=reason, raw=text, error=err)
    return row


# ---------------------------------------------------------------------------
# Files on disk
# ---------------------------------------------------------------------------

def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def done_ids(path, stage, judge, pass_):
    """Ids already saved successfully. Failures are left out so they get retried."""
    ids = set()
    for r in read_jsonl(path):
        if r.get("error") is not None:
            continue
        if stage == "judge" and (r.get("judge") != judge or r.get("pass") != pass_):
            continue
        ids.add(r["id"])
    return ids


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def make_client(cfg, timeout):
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        sys.exit(f"{cfg['key_env']} is not set.")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=cfg["base_url"], timeout=timeout, max_retries=0)


def call(client, cfg, cell, tokens):
    messages = ([{"role": "system", "content": cell["system"]}] if cell["system"] else []) \
               + [{"role": "user", "content": cell["user"]}]
    r = client.chat.completions.create(model=cfg["model"], messages=messages,
                                       **{cfg["cap"]: tokens})
    u = r.usage
    return (r.choices[0].message.content or "",
            getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None))


def call_with_retries(client, cfg, cell, tokens, attempts):
    last = ""
    for attempt in range(attempts):
        try:
            return (*call(client, cfg, cell, tokens), None)
        except Exception as e:  # noqa: BLE001 -- any failure is just a failed cell
            last = f"{type(e).__name__}: {e}"
            if any(s in last.lower() for s in FATAL_SIGNS):
                raise OutOfCredits(last) from e
            if attempt == attempts - 1:
                break
            time.sleep(min(60.0, 2 ** attempt) * (0.5 + random.random()))
    return None, None, None, last


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["answer", "judge"])
    p.add_argument("input", help="prompts .xlsx for answer, responses.jsonl for judge")
    p.add_argument("--providers", default="meta")
    p.add_argument("--out", help="default: responses-<script>.jsonl, merged later by merge.py")
    p.add_argument("--duplicates", type=int, default=3, help="D, runs per cell")
    p.add_argument("--pass", dest="pass_", type=int, default=0, help="judge pass number")
    p.add_argument("--limit", type=int)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--attempts", type=int, default=5)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    p.add_argument("--sheet", default=0)
    p.add_argument("--id-col")
    p.add_argument("--pos-col")
    p.add_argument("--neg-col")
    args = p.parse_args()

    providers = [x.strip() for x in args.providers.split(",") if x.strip()]
    unknown = [x for x in providers if x not in PROVIDERS]
    if unknown:
        sys.exit(f"Unknown provider(s): {unknown}. This script covers {list(PROVIDERS)}.")

    stem = os.path.splitext(os.path.basename(__file__))[0]
    base = "responses" if args.stage == "answer" else "judgments"
    args.out = args.out or f"{base}-{stem}.jsonl"
    args.sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    tokens = ANSWER_TOKENS if args.stage == "answer" else JUDGE_TOKENS

    cells = answer_cells(args, providers) if args.stage == "answer" else judge_cells(args, providers)
    saved = done_ids(args.out, args.stage, providers[0], args.pass_)
    todo = [c for c in cells if c["id"] not in saved]
    print(f"{len(cells)} cells, {len(saved)} already saved, {len(todo)} to do -> {args.out}")

    if args.dry_run or not todo:
        for c in todo[:2]:
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
            result = call_with_retries(clients[cell["provider"]], cfg, cell, tokens, args.attempts)
        except OutOfCredits as e:
            stop.set()
            print(f"\nSTOPPED -- billing/quota error on {cell['provider']}: {e}", file=sys.stderr)
            return
        row = make_row(args.stage, cell, cfg, *result)
        with lock:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            counts["ok" if row["error"] is None else "fail"] += 1
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
