# LLM agreement benchmarking

Ask several model providers the same claims, once per identity perspective, and
score how far each answer agrees with the claim. AI4PC Lab, Howard University.

One script per batch dialect. Four of the five providers offer a batch API, in
three mutually incompatible formats; Meta offers none. Rather than one script
with four branches, each format gets its own file:

| script | providers | how |
|---|---|---|
| `openai_xai.py` | OpenAI, xAI | upload JSONL, create batch, fetch results |
| `anthropic_batch.py` | Anthropic | inline requests, poll, stream results |
| `google_batch.py` | Google | upload JSONL, create job, download results |
| `meta_sequential.py` | Meta, local | one request at a time — Meta has no batch endpoint |
| `merge.py` | — | folds the per-script files into one |

Every script takes a stage, `answer` or `judge`, and writes rows in the same
shape — but to **its own file**, so all four can run at the same time without
racing each other for one handle. `merge.py` puts them back together.

Generation and judging stay separate: the rubric, the judge model and the parser
can all change without re-spending the generation budget.

## Setup

```bash
uv sync
```

If `import ssl` fails in the resulting environment — some managed Windows
machines block native DLLs under `AppData`, which breaks HTTPS for any
interpreter installed there — build the environment from a system Python
instead:

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install pandas openpyxl openai anthropic google-genai
```

Then copy `.env.example` to `.env` and fill in the keys you need. Keys are read
from the environment only.

## Running

Submit, then come back later. The same command does both:

```bash
python openai_xai.py answer prompts.xlsx
```

The first call submits batches and prints their ids. Every later call fetches
whatever has finished, appends it, and resubmits anything that came back
failed. Repeat until it says `nothing left to do`. Add `--wait` to poll in a
loop instead of checking by hand.

Run the other three the same way. They can all run at once, in separate
terminals, because each writes to its own file:

```bash
python anthropic_batch.py answer prompts.xlsx
python google_batch.py answer prompts.xlsx
python meta_sequential.py answer prompts.xlsx
```

When every script says `nothing left to do`, fold the four files into one:

```bash
python merge.py responses
```

Then judge the merged file. Pick whichever script hosts the judge model, and
merge again afterwards:

```bash
python anthropic_batch.py judge responses.jsonl
python merge.py judgments
```

A second judge from a different family is just a second script over the same
input — it writes its own file, so it can run alongside the first, and the merge
keys judgments by `(id, judge, pass)` rather than overwriting.

Before any of that, check the spreadsheet is being read correctly and that a
prompt actually works. `--now` skips batching and calls the API directly, which
is the only way to get an answer in seconds rather than hours:

```bash
python meta_sequential.py answer prompts.xlsx --dry-run
python openai_xai.py answer prompts.xlsx --limit 3 --duplicates 1 --now
```

Useful flags: `--providers`, `--duplicates` (D), `--limit`, `--batch-size`,
`--pass`, `--no-submit`. `--help` on any script lists them all.

## The spreadsheet

One row per claim. Columns are found by name, case-insensitively:

| looking for | accepted headers |
|---|---|
| the claim | `question`, `claim`, `positive`, `statement`, `prompt`, `original` |
| its negation | `negative`, `negation`, `negated`, `opposite`, `reversed` |
| an id | `id`, `qid`, `question_id`, `item`, `index`, `no`, `number` |

Anything else is ignored. If the headers differ, pass `--pos-col`, `--neg-col`,
`--id-col`; if a column cannot be found, the script prints the headers it did
see and stops. Without an id column, rows are numbered `q0001` onward — which
means **inserting a row later renumbers everything after it**, so give the sheet
a real id column before the first paid run.

With no negation column, only the positives run, and the script says so.

## Resuming

Every answer is keyed by a stable id built from
`question | polarity | perspective | provider | run`. Rows are appended as they
arrive and never rewritten, so rerunning any command does only what is missing.

Submitted batch ids are recorded in `.batches-<script>.jsonl`. That is what lets
a later run reattach to a batch already in flight instead of paying to submit it
twice — don't delete it while batches are open.

`merge.py` resolves duplicates rather than concatenating. A cell that failed and
was retried has both rows on disk; the successful one wins, and among several
successes the latest timestamp wins. It never folds a previous merge back into
itself, so it is safe to rerun at any point, including while jobs are still in
flight — it just reports less coverage.

Failures need no special handling. A request that fails comes back in the batch
results with an error, gets written as a row with `error` set, and is picked up
by the next submission. Nothing is retried in a loop. `meta_sequential.py` is
the exception: having no batch to fall back on, it retries transient failures
with backoff, and stops outright on a billing or quota error, since no provider
lets you resume a run that stopped for lack of credits and retrying an
`insufficient_quota` error cannot fix it.

## Configuration

Each script keeps its settings in a labelled block at the top — perspectives,
model ids, prompt templates, token caps, batch size. The perspectives and
prompts are deliberately duplicated across the four files; edit them together.

Two things to check before any paid run:

- **Model ids.** Only `claude-opus-5` and `muse-spark-1.3` were verified against
  vendor documentation on 2026-09-21. The rest are defaults; confirm each
  against that provider's own model list.
- **The `cap` field**, which names the parameter carrying the token limit.
  OpenAI's newer models require `max_completion_tokens`; most compatible servers
  still take `max_tokens`. A server that silently ignores the wrong one returns
  long answers and a larger bill, so check one response's `output_tokens` first.

`meta_sequential.py` also accepts `--providers local`, pointing at an
OpenAI-compatible server on `localhost:8000` — vLLM, Ollama or llama.cpp — for
open-weight models, or for testing without spending.

## Output

Each script writes `responses-<script>.jsonl` or `judgments-<script>.jsonl`;
`merge.py` produces `responses.jsonl` and `judgments.jsonl`. Every row has the
same shape whichever script wrote it.

One object per answer:

```json
{"id": "c001|pos|physician|openai|0", "qid": "c001", "polarity": "pos",
 "perspective": "physician", "provider": "openai", "run": 0,
 "question": "...", "ts": "2026-09-21T14:29:07Z", "model": "...",
 "system": "...", "user": "...", "response": "...",
 "input_tokens": 17, "output_tokens": 11, "error": null}
```

One object per judgment:

```json
{"id": "c001|pos|physician|openai|0", "judge": "anthropic", "pass": 0,
 "qid": "c001", "polarity": "pos", "perspective": "physician",
 "provider": "openai", "ts": "...", "judge_model": "claude-sonnet-5",
 "agreement": 4, "refused": false, "reason": "...", "raw": "...", "error": null}
```

`raw` holds the judge's reply verbatim, always. If the parser turns out to be
wrong, fix `parse_score()` and re-read the existing file rather than paying to
judge again.

## Provider notes

[`docs/batch-apis.md`](docs/batch-apis.md) has the full comparison with sources:
which providers support batch, whether batches and uploaded files can be deleted
afterwards, and what each does when credits run out.

The finding that shaped the layout above: Meta's Llama API shut down on 6 July
2026. `meta_sequential.py` points at its replacement, the Meta Model API, which
serves Muse — a Meta model, but not Llama, and with no batch endpoint.
Benchmarking Llama itself now means a third-party host or a local server.

One caveat on `google_batch.py`: Google documents the request JSONL exactly but
not the result line shape, so `read_results()` accepts both a `{"key",
"response"}` wrapper and a bare `GenerateContentResponse`. It has been tested
against the documented shape, not a live batch — check the first small job
before trusting a large one.

## Open questions

Still to settle: the spreadsheet's real column layout and where the perspectives
come from; the values of N and D; which judge model, and whether a second judge
from another family is needed on a subset to check for self-preference bias;
and whose keys and budget.
