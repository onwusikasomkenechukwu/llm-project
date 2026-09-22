#!/usr/bin/env python3
"""OpenAI and xAI, via their batch API. Both speak the same dialect: upload a
JSONL of requests, create a batch, come back later for the results.

    python openai_xai.py answer prompts.xlsx          # submits, prints batch ids
    python openai_xai.py answer prompts.xlsx          # again later: fetches what is done
    python openai_xai.py judge responses.jsonl        # same, for judging

Each run does three things in order: fetch any batch that has finished, submit
whatever is still missing, then report. So the same command submits the work,
checks on it, and picks up failures on the next pass. Add --wait to poll in a
loop instead of coming back by hand.

Writes to responses-openai_xai.jsonl, not the shared file, so all four scripts
can run at once without racing each other. Run merge.py when they are done.

Batch ids live in .batches-openai_xai.jsonl. Delete it only if you also want the
batches themselves abandoned.
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

# cap: OpenAI's newer models need max_completion_tokens, xAI takes max_tokens.
PROVIDERS = {
    "openai": dict(model="gpt-5.2", cap="max_completion_tokens",
                   base_url="https://api.openai.com/v1", key_env="OPENAI_API_KEY"),
    "xai": dict(model="grok-4", cap="max_tokens",
                base_url="https://api.x.ai/v1", key_env="XAI_API_KEY"),
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
BATCH_SIZE = 10000  # requests per batch; the API cap is 50,000


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
    """Batches submitted but not yet fetched, in submission order."""
    fetched, open_ = set(), {}
    for r in read_jsonl(state_path):
        if r.get("fetched"):
            fetched.add(r["batch_id"])
        elif r.get("stage") == stage:
            open_[r["batch_id"]] = r
    return [r for b, r in open_.items() if b not in fetched]


# ---------------------------------------------------------------------------
# The batch dialect: upload a file, create a batch, download results
# ---------------------------------------------------------------------------

def make_client(cfg):
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        sys.exit(f"{cfg['key_env']} is not set.")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=cfg["base_url"])


def submit(client, cfg, cells, tokens, tmp_path):
    """Upload one chunk of cells and create a batch. Returns the batch id.

    custom_id is a positional key, not the cell id: providers restrict the
    character set, and our ids contain pipes. The state file holds the mapping.
    """
    with open(tmp_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cells):
            messages = ([{"role": "system", "content": c["system"]}] if c["system"] else []) \
                       + [{"role": "user", "content": c["user"]}]
            f.write(json.dumps({
                "custom_id": f"r{i}", "method": "POST", "url": "/v1/chat/completions",
                "body": {"model": cfg["model"], "messages": messages, cfg["cap"]: tokens},
            }) + "\n")
    with open(tmp_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    os.remove(tmp_path)
    batch = client.batches.create(input_file_id=uploaded.id,
                                  endpoint="/v1/chat/completions", completion_window="24h")
    return batch.id


DONE = {"completed", "failed", "expired", "cancelled"}


def fetch(client, batch_id):
    """Return (status, {custom_id: (text, in_tokens, out_tokens, error)})."""
    batch = client.batches.retrieve(batch_id)
    if batch.status not in DONE:
        return batch.status, None
    out = {}
    for fid in (batch.output_file_id, batch.error_file_id):
        if not fid:
            continue
        for line in client.files.content(fid).text.splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key, resp, err = r.get("custom_id"), r.get("response"), r.get("error")
            if resp and resp.get("status_code") == 200:
                body = resp["body"]
                u = body.get("usage") or {}
                out[key] = (body["choices"][0]["message"].get("content") or "",
                            u.get("prompt_tokens"), u.get("completion_tokens"), None)
            else:
                detail = err or (resp or {}).get("body")
                out[key] = (None, None, None, json.dumps(detail)[:500])
    return batch.status, out


def call_now(client, cfg, cell, tokens):
    """One immediate call, for --now smoke tests. Batch turnaround is up to 24h."""
    messages = ([{"role": "system", "content": cell["system"]}] if cell["system"] else []) \
               + [{"role": "user", "content": cell["user"]}]
    try:
        r = client.chat.completions.create(model=cfg["model"], messages=messages,
                                           **{cfg["cap"]: tokens})
        u = r.usage
        return (r.choices[0].message.content or "",
                getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), None)
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
    p.add_argument("--providers", help="default: both for answer, openai for judge")
    p.add_argument("--out", help="default: responses-<script>.jsonl, merged later by merge.py")
    p.add_argument("--state", help="default: .batches-<script>.jsonl")
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

    default_provs = "openai,xai" if args.stage == "answer" else "openai"
    providers = [x.strip() for x in (args.providers or default_provs).split(",") if x.strip()]
    unknown = [x for x in providers if x not in PROVIDERS]
    if unknown:
        sys.exit(f"Unknown provider(s): {unknown}. This script covers {list(PROVIDERS)}.")
    if args.stage == "judge" and len(providers) > 1:
        sys.exit("One judge at a time. Use --pass or rerun for a second judge.")

    stem = os.path.splitext(os.path.basename(__file__))[0]
    base = "responses" if args.stage == "answer" else "judgments"
    args.out = args.out or f"{base}-{stem}.jsonl"
    args.state = args.state or f".batches-{stem}.jsonl"
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
            print(f"\nCheck back with the same command, or add --wait. "
                  f"Batches usually finish well inside 24h.")
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
