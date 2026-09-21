# LLM agreement benchmarking

Ask several model providers the same claims, once per identity perspective, and
score how far each answer agrees with the claim. AI4PC Lab, Howard University.

Two scripts, in order:

| | |
|---|---|
| `run.py` | reads the prompts spreadsheet, calls every model, appends raw answers to `responses.jsonl` |
| `judge.py` | reads `responses.jsonl`, scores each answer with a judge model, appends to `judgments.jsonl` |

They share no code and no state beyond `responses.jsonl`. Generation and judging
stay separate on purpose: the rubric, the judge model and the parser can all
change without re-spending the generation budget.

## Setup

```bash
uv sync
```

If `import ssl` fails in the resulting environment — some managed Windows
machines block native DLLs under `AppData`, which breaks HTTPS for any
interpreter installed there — build the environment from a system Python
instead:

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install pandas openpyxl openai anthropic
```

Then copy `.env.example` to `.env` and fill in the keys you need. Both scripts
read keys from the environment only; nothing is ever written to disk.

## Running

```bash
python run.py prompts.xlsx --out responses.jsonl
```

Start with a dry run to check the spreadsheet is being read correctly — it
prints the grid size and the first few prompts, and calls nothing:

```bash
python run.py prompts.xlsx --dry-run
```

Then a small paid smoke test before the full grid:

```bash
python run.py prompts.xlsx --out smoke.jsonl --limit 3 --providers openai,anthropic --duplicates 1
```

Judging works the same way:

```bash
python judge.py responses.jsonl --out judgments.jsonl --judge anthropic
```

Useful flags: `--providers`, `--duplicates` (D), `--limit`, `--concurrency`,
`--attempts`, `--timeout`. `--help` on either script lists them all.

## The spreadsheet

One row per claim. `run.py` finds the columns by name, case-insensitively:

| looking for | accepted headers |
|---|---|
| the claim | `question`, `claim`, `positive`, `statement`, `prompt`, `original` |
| its negation | `negative`, `negation`, `negated`, `opposite`, `reversed` |
| an id | `id`, `qid`, `question_id`, `item`, `index`, `no`, `number` |

Anything else is ignored. If the headers differ, pass `--pos-col`,
`--neg-col`, `--id-col` explicitly; if a column cannot be found, the script
prints the headers it did see and stops. Without an id column, rows are
numbered `q0001` onward — which means **inserting a row later renumbers
everything after it**, so give the sheet a real id column before the first
paid run.

With no negation column, only the positives run, and the script says so.

## Resuming

Every answer is keyed by a stable id built from
`question | polarity | perspective | provider | run`. Rows are appended as they
arrive and never rewritten. Rerunning the same command skips ids already saved
and does only what is missing, so an interrupted run resumes by running it
again. The same holds for `judge.py`, per judge and per `--pass`.

A failed cell leaves a row with `error` set and is retried on the next run. A
cell that has since succeeded is not retried, so a file can hold both an error
row and a good row for one id — `judge.py` reads only the good ones.

Transient failures are retried with exponential backoff. **Billing and quota
errors are not**: no provider lets you resume a run that stopped for lack of
credits, and retrying an `insufficient_quota` error cannot fix it. Both scripts
stop immediately on one, print what was saved, and exit 2. Fix billing, run the
same command, and it picks up where it left off.

## Configuration

Both scripts keep their settings in a labelled block at the top of the file —
perspectives, providers, model ids, the prompt templates, the token cap. Edit
them there. Two things to check before any paid run:

- **Model ids.** Only `claude-opus-5` and `muse-spark-1.3` were verified against
  vendor documentation on 2026-09-21. The rest are defaults; confirm each
  against that provider's own model list.
- **The `cap` field**, which names the parameter carrying the token limit.
  OpenAI's newer models require `max_completion_tokens`; most compatible servers
  still take `max_tokens`. A server that silently ignores the wrong one returns
  long answers and a larger bill, so check one response's `output_tokens` before
  launching the full grid.

`local` points at an OpenAI-compatible server on `localhost:8000` — vLLM,
Ollama or llama.cpp — for open-weight models, or for testing without spending.

## Batch APIs

`run.py` makes ordinary concurrent calls. Four of the five providers also offer
a batch API at roughly half price, but in three mutually incompatible dialects,
and Meta offers none. At the full grid size that is a few hours of wall clock
either way, so batch is a cost lever rather than a necessity.

[`docs/batch-apis.md`](docs/batch-apis.md) has the provider-by-provider
comparison, with sources: whether each supports batch, whether batches and
uploaded files can be deleted afterwards, and what happens when credits run out.

One finding from that research affects the design rather than the code: Meta's
Llama API shut down on 6 July 2026. The `meta` provider entry points at its
replacement, the Meta Model API, which serves Muse — a Meta model, but not
Llama. Benchmarking Llama itself now means a third-party host or a local server.

## Output

`responses.jsonl`, one object per answer:

```json
{"id": "c001|pos|physician|openai|0", "qid": "c001", "polarity": "pos",
 "perspective": "physician", "provider": "openai", "run": 0,
 "question": "...", "system": "...", "user": "...", "model": "...",
 "ts": "2026-09-21T14:29:07Z", "response": "...", "input_tokens": 17,
 "output_tokens": 11, "latency_s": 2.12, "error": null}
```

`judgments.jsonl`, one object per judgment:

```json
{"id": "c001|pos|physician|openai|0", "judge": "anthropic",
 "judge_model": "claude-sonnet-5", "pass": 0, "agreement": 4,
 "refused": false, "reason": "...", "raw": "...", "error": null}
```

`raw` holds the judge's reply verbatim, always. If the parser turns out to be
wrong, fix `parse()` and re-read the existing file rather than paying to judge
again. The script reports how many judgments have no parsed score.

## Open questions

Still to settle before the full run: the spreadsheet's real column layout and
where the perspectives come from; the values of N and D; which judge model, and
whether a second judge from another family is needed on a subset to check for
self-preference bias; whose keys and budget; and whether the Meta row means
Muse or Llama.
