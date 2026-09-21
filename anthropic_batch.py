#!/usr/bin/env python3
"""Anthropic, via the Message Batches API. Requests go inline, not as a file.

    python anthropic_batch.py answer prompts.xlsx     # submits, prints batch ids
    python anthropic_batch.py answer prompts.xlsx     # again later: fetches what is done
    python anthropic_batch.py judge responses.jsonl   # same, for judging

Each run fetches any batch that has finished, submits whatever is still
missing, then reports. The same command submits the work, checks on it, and
picks up failures on the next pass. Add --wait to poll in a loop.

Batch ids live in .batches.jsonl next to the output.
"""

import argparse
import json
import os
import re
import sys
import time
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
    "anthropic": dict(model="claude-opus-5", key_env="ANTHROPIC_API_KEY"),
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

# Generous on purpose: thinking is on by default on current models and is
# billed as output tokens, so it eats into this ceiling.
ANSWER_TOKENS = 2000
JUDGE_TOKENS = 400
BATCH_SIZE = 10000  # requests per batch; the API cap is 100,000


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


def append_jsonl(path, rows):
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


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


def pending_batches(state_path, stage):
    """Batches submitted but not yet fetched."""
    fetched, open_ = set(), {}
    for r in read_jsonl(state_path):
        if r.get("fetched"):
            fetched.add(r["batch_id"])
        elif r.get("stage") == stage:
            open_[r["batch_id"]] = r
    return [r for b, r in open_.items() if b not in fetched]


# ---------------------------------------------------------------------------
# The batch dialect: inline requests, poll processing_status, stream results
# ---------------------------------------------------------------------------

def make_client(cfg):
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        sys.exit(f"{cfg['key_env']} is not set.")
    import anthropic
    return anthropic.Anthropic(api_key=key)


def submit(client, cfg, cells, tokens, _tmp_path):
    """Create one batch from a chunk of cells. Returns the batch id.

    custom_id must match ^[a-zA-Z0-9_-]{1,64}$, so it is a positional key
    rather than the cell id. The state file holds the mapping.
    """
    requests = []
    for i, c in enumerate(cells):
        params = {"model": cfg["model"], "max_tokens": tokens,
                  "messages": [{"role": "user", "content": c["user"]}]}
        if c["system"]:
            params["system"] = c["system"]
        requests.append({"custom_id": f"r{i}", "params": params})
    return client.messages.batches.create(requests=requests).id


DONE = {"ended"}


def fetch(client, batch_id):
    """Return (status, {custom_id: (text, in_tokens, out_tokens, error)})."""
    batch = client.messages.batches.retrieve(batch_id)
    status = batch.processing_status
    if status not in DONE:
        return status, None
    out = {}
    for entry in client.messages.batches.results(batch_id):
        outcome = entry.result
        if outcome.type == "succeeded":
            msg = outcome.message
            text = "".join(b.text for b in msg.content if b.type == "text")
            out[entry.custom_id] = (text, msg.usage.input_tokens, msg.usage.output_tokens, None)
        else:
            # errored, canceled or expired -- resubmitted on the next pass
            detail = getattr(outcome, "error", None)
            out[entry.custom_id] = (None, None, None,
                                    f"{outcome.type}: {str(detail)[:400]}")
    return status, out


def call_now(client, cfg, cell, tokens):
    """One immediate call, for --now smoke tests. Batch turnaround is up to 24h."""
    try:
        kwargs = {"system": cell["system"]} if cell["system"] else {}
        m = client.messages.create(model=cfg["model"], max_tokens=tokens,
                                   messages=[{"role": "user", "content": cell["user"]}], **kwargs)
        text = "".join(b.text for b in m.content if b.type == "text")
        return text, m.usage.input_tokens, m.usage.output_tokens, None
    except Exception as e:  # noqa: BLE001
        return None, None, None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["answer", "judge"])
    p.add_argument("input", help="prompts .xlsx for answer, responses.jsonl for judge")
    p.add_argument("--providers", default="anthropic")
    p.add_argument("--out", help="default: responses.jsonl / judgments.jsonl")
    p.add_argument("--state", default=".batches.jsonl")
    p.add_argument("--duplicates", type=int, default=3, help="D, runs per cell")
    p.add_argument("--pass", dest="pass_", type=int, default=0, help="judge pass number")
    p.add_argument("--limit", type=int)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--wait", action="store_true", help="poll until every batch is done")
    p.add_argument("--poll-seconds", type=int, default=120)
    p.add_argument("--now", action="store_true", help="call immediately instead of batching")
    p.add_argument("--no-submit", action="store_true", help="only fetch what is already running")
    p.add_argument("--sheet", default=0)
    p.add_argument("--id-col")
    p.add_argument("--pos-col")
    p.add_argument("--neg-col")
    args = p.parse_args()

    providers = [x.strip() for x in args.providers.split(",") if x.strip()]
    unknown = [x for x in providers if x not in PROVIDERS]
    if unknown:
        sys.exit(f"Unknown provider(s): {unknown}. This script covers {list(PROVIDERS)}.")

    args.out = args.out or ("responses.jsonl" if args.stage == "answer" else "judgments.jsonl")
    args.sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    tokens = ANSWER_TOKENS if args.stage == "answer" else JUDGE_TOKENS

    cells = answer_cells(args, providers) if args.stage == "answer" else judge_cells(args, providers)
    by_id = {c["id"]: c for c in cells}
    clients = {name: make_client(PROVIDERS[name]) for name in providers}
    print(f"{len(cells)} cells across {', '.join(providers)}")

    while True:
        # 1. collect anything that has finished
        still_open = []
        for rec in pending_batches(args.state, args.stage):
            cfg = PROVIDERS[rec["provider"]]
            status, results = fetch(clients[rec["provider"]], rec["batch_id"])
            if results is None:
                still_open.append(rec)
                print(f"  {rec['batch_id']} {status} ({rec['n']} requests)")
                continue
            rows = []
            for key, (text, tin, tout, err) in results.items():
                cell = by_id.get(rec["ids"][int(key[1:])])
                if cell:
                    rows.append(make_row(args.stage, cell, cfg, text, tin, tout, err))
            append_jsonl(args.out, rows)
            append_jsonl(args.state, [{"batch_id": rec["batch_id"], "fetched": True,
                                       "ts": datetime.now(timezone.utc).isoformat()}])
            bad = sum(1 for r in rows if r["error"] is not None)
            print(f"  {rec['batch_id']} {status}: {len(rows) - bad} saved, {bad} failed")

        # 2. work out what is left
        saved = done_ids(args.out, args.stage, providers[0], args.pass_)
        in_flight = {i for rec in still_open for i in rec["ids"]}
        todo = [c for c in cells if c["id"] not in saved and c["id"] not in in_flight]
        print(f"{len(saved)} saved, {len(in_flight)} in flight, {len(todo)} to go")

        # 3. submit what is missing
        if todo and not args.no_submit:
            if args.now:
                rows = []
                for c in todo:
                    cfg = PROVIDERS[c["provider"]]
                    rows.append(make_row(args.stage, c, cfg,
                                         *call_now(clients[c["provider"]], cfg, c, tokens)))
                append_jsonl(args.out, rows)
                print(f"  called {len(rows)} directly")
                return
            for prov in providers:
                mine = [c for c in todo if c["provider"] == prov]
                for i in range(0, len(mine), args.batch_size):
                    chunk = mine[i: i + args.batch_size]
                    bid = submit(clients[prov], PROVIDERS[prov], chunk, tokens,
                                 f".{prov}-batch-{i}.jsonl")
                    append_jsonl(args.state, [{
                        "batch_id": bid, "provider": prov, "stage": args.stage,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "n": len(chunk), "ids": [c["id"] for c in chunk]}])
                    print(f"  submitted {bid} ({len(chunk)} requests to {prov})")
        elif not todo and not still_open:
            print("nothing left to do")
            return

        if not args.wait:
            print("\nCheck back with the same command, or add --wait. "
                  "Most batches finish inside an hour; all expire at 24h.")
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
