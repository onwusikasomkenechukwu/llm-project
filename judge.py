#!/usr/bin/env python3
"""Stage 2: score the saved answers with a judge model.

    python judge.py responses.jsonl --out judgments.jsonl
    python judge.py responses.jsonl --out judgments.jsonl --judge anthropic --limit 20

Reads responses.jsonl, sends each answer to the judge, appends one JSON object
per judgment. The judge's raw reply is always saved next to the parsed score, so
fixing the parser later never means paying to judge again.

Rerunning skips ids already judged by the same judge and pass. To judge the same
answers a second time -- a different judge family, a check on self-preference
bias -- change --judge or bump --pass, and nothing already saved is touched.
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

# ---------------------------------------------------------------------------
# Configuration. Edit these three blocks; the rest is plumbing.
# ---------------------------------------------------------------------------

# Judge candidates. Pick one with --judge. Using a judge from a family that is
# also being evaluated is a known self-preference confound; the cheap check is a
# second judge from a different family over a subset (--limit).
JUDGES = {
    "anthropic": dict(sdk="anthropic", model="claude-sonnet-5",
                      base_url=None, key_env="ANTHROPIC_API_KEY"),
    "openai": dict(sdk="openai", model="gpt-5.2",
                   base_url="https://api.openai.com/v1", key_env="OPENAI_API_KEY"),
    "google": dict(sdk="openai", model="gemini-3-pro",
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   key_env="GEMINI_API_KEY"),
}

# What the judge scores. Agreement with the claim is the primary measure; the
# refusal flag separates "did not agree" from "did not answer".
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

MAX_TOKENS = 400

FATAL_SIGNS = ("insufficient_quota", "billing", "credit balance", "exceeded your current quota",
               "quota exceeded", "payment", "spend limit", "spend cap")


class OutOfCredits(Exception):
    """Raised on a billing/quota error so judging stops instead of retrying."""


# ---------------------------------------------------------------------------
# Judge calls
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


def call(client, cfg, prompt):
    if cfg["sdk"] == "anthropic":
        m = client.messages.create(model=cfg["model"], max_tokens=MAX_TOKENS,
                                   messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in m.content if b.type == "text")
    r = client.chat.completions.create(model=cfg["model"],
                                       messages=[{"role": "user", "content": prompt}],
                                       max_completion_tokens=MAX_TOKENS)
    return r.choices[0].message.content or ""


def call_with_retries(client, cfg, prompt, attempts):
    last = ""
    for attempt in range(attempts):
        try:
            return call(client, cfg, prompt), None
        except Exception as e:  # noqa: BLE001 -- any failure is just a failed judgment
            last = f"{type(e).__name__}: {e}"
            if any(s in last.lower() for s in FATAL_SIGNS):
                raise OutOfCredits(last) from e
            if attempt == attempts - 1:
                break
            time.sleep(min(60.0, 2 ** attempt) * (0.5 + random.random()))
    return None, last


def parse(raw):
    """Pull the score out of the judge's reply. Never raises; raw is kept anyway."""
    if not raw:
        return None, None, None
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = obj.get("agreement")
            score = int(score) if isinstance(score, (int, float, str)) and str(score).strip().isdigit() else None
            return (score if score in (1, 2, 3, 4, 5) else None,
                    bool(obj.get("refused")) if "refused" in obj else None,
                    obj.get("reason"))
        except (ValueError, TypeError):
            pass
    m = re.search(r"\b([1-5])\b", raw)  # last resort: a bare digit
    return (int(m.group(1)) if m else None), None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def claim_of(row):
    """The bare claim. Older response files without it fall back to the full prompt."""
    return row.get("question") or row["user"]


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("responses", help="responses.jsonl written by run.py")
    p.add_argument("--out", default="judgments.jsonl")
    p.add_argument("--judge", default="anthropic", choices=list(JUDGES))
    p.add_argument("--pass", dest="pass_", type=int, default=0,
                   help="bump for a second pass with the same judge")
    p.add_argument("--limit", type=int, help="judge only the first N answers")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--attempts", type=int, default=5)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    args = p.parse_args()

    cfg = JUDGES[args.judge]
    answers = [r for r in read_jsonl(args.responses) if r.get("error") is None and r.get("response")]

    already = set()
    if os.path.exists(args.out):
        for r in read_jsonl(args.out):
            if r.get("judge") == args.judge and r.get("pass") == args.pass_ and r.get("error") is None:
                already.add(r["id"])

    todo = [r for r in answers if r["id"] not in already]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(answers)} answers, {len(already)} already judged by "
          f"{args.judge} pass {args.pass_}, {len(todo)} to do -> {args.out}")
    if args.dry_run or not todo:
        if todo:
            print("\n--- example prompt\n" + JUDGE_PROMPT.format(
                claim=claim_of(todo[0]), answer=todo[0]["response"]))
        return

    client = make_client(cfg, args.timeout)
    lock = threading.Lock()
    out = open(args.out, "a", encoding="utf-8")
    counts = {"ok": 0, "fail": 0}
    stop = threading.Event()

    def work(answer):
        if stop.is_set():
            return
        prompt = JUDGE_PROMPT.format(claim=claim_of(answer), answer=answer["response"])
        try:
            raw, err = call_with_retries(client, cfg, prompt, args.attempts)
        except OutOfCredits as e:
            stop.set()
            print(f"\nSTOPPED -- billing/quota error: {e}", file=sys.stderr)
            return
        score, refused, reason = parse(raw)
        row = {"id": answer["id"], "judge": args.judge, "judge_model": cfg["model"],
               "pass": args.pass_, "ts": datetime.now(timezone.utc).isoformat(),
               "provider": answer.get("provider"), "perspective": answer.get("perspective"),
               "polarity": answer.get("polarity"), "qid": answer.get("qid"),
               "agreement": score, "refused": refused, "reason": reason,
               "raw": raw, "error": err}
        with lock:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            counts["ok" if err is None else "fail"] += 1
            n = counts["ok"] + counts["fail"]
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  ok={counts['ok']} failed={counts['fail']}", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            list(pool.map(work, todo))
    finally:
        out.close()

    unparsed = sum(1 for r in read_jsonl(args.out)
                   if r.get("error") is None and r.get("agreement") is None)
    print(f"\njudged {counts['ok']}, failed {counts['fail']}, in {args.out}")
    if unparsed:
        print(f"{unparsed} judgments have no parsed score. The raw replies are saved -- "
              f"fix parse() and rerun with --pass {args.pass_ + 1}, or reparse offline.")
    if stop.is_set():
        print("Judging stopped early. Fix billing, then run the same command to resume.")
        sys.exit(2)
    if counts["fail"]:
        print("Rerun the same command to retry the failed judgments.")


if __name__ == "__main__":
    main()
