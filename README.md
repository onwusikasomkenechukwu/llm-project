# llmbench

Benchmarking harness for measuring how large language models respond to
agree/disagree claims, across stated identity perspectives, with a separate LLM
judge. Built for the AI4PC Lab, Howard University.

**The grid:** 400 claims × 2 polarities × 5 perspectives × 3 providers × 3
duplicates = **36,000 generation calls + 36,000 judge calls**.

---

## The four phases

Each phase is a separate command, runnable alone, reading only what the previous
phase wrote to disk.

| Phase | Command | Reads | Writes |
|---|---|---|---|
| 1 | `generate-grid` | config + questions | `grid.jsonl` |
| 2 | `run` | `grid.jsonl` | `responses/*.jsonl` |
| 3 | `judge` | `responses/*.jsonl` | `judgments/*.jsonl` |
| 4 | `analyze` | both | `analysis/*.csv` |

**Judging never calls an answering model.** This is the structural requirement
the whole layout is built around: the rubric can change, the judge model can
change, and a parser bug can be fixed, all without re-spending the generation
budget. A full re-judge costs $22–81 against $50–190 of generation you never
repeat.

---

## Quickstart

```bash
uv sync
```

Then run the whole pipeline on mock providers — no API keys, no network, zero spend:

```bash
uv run llmbench validate      -c configs/smoke.yaml
```

```bash
uv run llmbench generate-grid -c configs/smoke.yaml
```

```bash
uv run llmbench run           -c configs/smoke.yaml
```

```bash
uv run llmbench judge         -c configs/smoke.yaml
```

```bash
uv run llmbench analyze       -c configs/smoke.yaml
```

That executes 1,080 cells and 1,080 judgments end to end in about 15 seconds and
writes real analysis tables. The mock providers have different built-in flip
rates and refusal rates, so the consistency and variance numbers come out with
genuine structure rather than noise — useful for checking the analysis before
spending anything.

Run the tests with:

```bash
uv run pytest
```

---

## Before the first paid run

1. **Replace `data/questions.jsonl`.** It currently holds 12 placeholder claims.
2. **Fill in the two `REPLACE-ME` providers** in `configs/experiment.yaml` with
   pinned model IDs and their current prices.
3. **Export the API keys** named in the config (see `.env.example`).
4. **Check pricing** for every provider against the vendor's current price list.
5. **Smoke test with a cap:**

```bash
uv run llmbench validate -c configs/experiment.yaml
```

```bash
uv run llmbench run -c configs/experiment.yaml --limit 20
```

`validate` prints the grid size, the config hash, and warnings for placeholder
models, zero pricing, and unset API keys.

---

## Assumptions, and where I think they need your advisor's attention

The five assumptions from the project brief, with the ones I would push back on.

**1. Negations are authored once and stored, not generated at runtime.**
Implemented as specified — correct call. But the consistency metric measures the
model only if the stored negation is a genuine logical negation. `questions.jsonl`
therefore carries `source` and `human_verified` per row, and the loader refuses
to run on unverified rows unless `questions.require_verified_negation: false` is
set deliberately. **Open question for the advisor: where do the 400 claims and
their negations come from, and is any human verification planned?**

**2. Perspectives are config-supplied system-prompt fragments.** Implemented.
Two caveats are handled explicitly: `answer_prompt.placement` chooses `system` or
`user_prefix` because providers honour system prompts differently and a silent
per-provider difference would confound the perspective effect; and a `control`
perspective with an empty fragment is required in the config, because without a
baseline there is nothing to measure a perspective effect against.

**3. The judge is fixed across conditions and configurable.** Implemented, but a
single fixed judge is a confound: the judge shares a model family with at least
one answering provider, and self-preference bias is well documented. The schema
keys judgments on `(cell_id, judge_provider_id, judge_model, judge_run_index,
rubric_version)`, so two cheap additions cost nothing structurally:
   - a **second judge from a different family** over a ~10% stratified subset, to
     report judge-to-judge agreement;
   - a **second pass with the same judge** over a subset, to report judge
     self-consistency.

   Reviewers will ask for both. Change `judge.run_index` and re-run `judge`.

**4. Judging is a separate pass over stored responses.** Implemented, and it
drives the entire layout. No changes recommended.

**5. Cost and latency are logged per call.** Implemented. One caveat: **latency
is operational telemetry, not a research variable.** It is contaminated by
concurrency, retries and time of day, and is not comparable across runs. Cost is
real, and is computed from prices pinned in the config rather than hardcoded, so
reported figures stay reproducible after vendors change their price lists.

### Things not in the original assumptions that also need a decision

**The judge returns a stance, not a quality score.** A generic 1–5 quality score
cannot express claim/negation consistency — an answer can be excellent on both a
claim and its negation. The primary outcome is `agreement_score`, a signed
−2..+2 scale, which is numeric (so "score by provider" and "score by
perspective" work as specified) and directional (so consistency is well
defined). `justification_quality` (1–5) is retained as an independent second
axis; drop it from `src/llmbench/prompts/judge.md` and `records.ParsedJudgment`
if your advisor does not want it.

**Refusals are a first-class outcome.** Identity perspectives will trigger
refusals and disclaimers at different rates across models and perspectives. If a
refusal were scored as a low-quality answer, "score by perspective" would partly
be measuring refusal rate and the reported effect would be the wrong one.
`refusal` and `non_responsive` are separate boolean fields, excluded from the
scored denominator and reported as their own rates.

**Consistency needs its indeterminate rate reported alongside it.** For a matched
pair, inconsistency is `|s_pos + s_neg|` — 0 when perfectly consistent, up to 4
when the model agrees with both a claim and its negation. Pairs where either side
is a refusal or non-responsive are excluded from the denominator and counted
separately. Without that second number, a model that refuses everything posts
perfect consistency on an almost empty denominator. The smoke run demonstrates
exactly this: `mock-gamma` has the best consistency score and the worst
indeterminate rate.

**Confidence intervals are clustered by question.** The same 400 claims recur in
every cell, so rows are not independent. Every CI in `analyze` is bootstrapped by
resampling whole questions. Resampling rows would give intervals far too narrow
and make trivial differences look significant.

**Execution order is shuffled.** Iterating the grid in nested-loop order aligns
provider and perspective with wall-clock time, so API-side drift and time-of-day
load would land unevenly across conditions. `run.shuffle_seed` is recorded.

**Multiple comparisons.** 5 perspectives means 10 pairwise contrasts per
provider, 30 across the study. Pre-register the specific contrasts you care
about, or correct for multiplicity. This is a decision to settle with your
advisor now rather than at write-up.

### Temperature

**Current Anthropic models reject `temperature` with a 400.** Sampling
parameters were removed on Opus 5, Opus 4.8/4.7, Sonnet 5 and the Fable family.
So the harness sends a temperature only to providers whose `params` set
`send_temperature: true`, and `configs/experiment.yaml` sets it to `false` for
Anthropic.

This has a design consequence worth raising: **the D=3 duplicates measure
inherent run-to-run nondeterminism, not a temperature setting you control.** You
cannot standardise sampling across providers when one of them does not accept a
sampling parameter. Say so in the methods section rather than implying a
common temperature was held fixed.

Relatedly, **thinking is on by default on Claude Opus 5** and is billed as output
tokens. `answer_prompt.max_tokens` is set to 2000 rather than a tight bound
because reasoning consumes part of that ceiling and a truncated answer scores as
non-responsive. The run reports a truncation count, and `analyze` reports
`truncation_rate` per provider — watch it on the first real run.

---

## Cost and time

Roughly 150 input and 180 output tokens per generation call; ~450 in and ~60 out
per judge call.

| Component | 36,000 calls |
|---|---|
| Generation, cheap tier (~$1/$5 per MTok) | ~$30 |
| Generation, mid tier (~$2/$10) | ~$75 |
| Generation, frontier tier (~$5/$25) | ~$190 |
| Judge, small model | ~$22 |
| Judge, mid tier | ~$81 |

A typical three-provider mix with at least one frontier model lands at
**$120–270 total**. Wall clock is about 4 hours at the concurrency in the
shipped config; rate limits will bind before concurrency does.

The cap in `configs/experiment.yaml` is $300, set to catch a runaway loop rather
than to be reached. Budget is **reserved before dispatch** using a worst-case
estimate and reconciled against actual token counts afterwards, so the cap binds
slightly early rather than slightly late — checking only at completion would let
concurrent calls sail past it together.

---

## Resumability

`run` skips any cell that already has a `status: "ok"` row. A cell whose only
rows are errors is retried with `attempt_epoch` incremented, and **the old error
rows stay on disk**. Response files are never rewritten; each invocation opens a
new timestamped file.

This resolves the tension between "one row per call" and "skip cells already
present" — a failed cell *is* present, so presence alone cannot mean done.

```bash
uv run llmbench run -c configs/experiment.yaml   # interrupt with Ctrl-C any time
```

```bash
uv run llmbench run -c configs/experiment.yaml   # picks up exactly where it stopped
```

`judge` resumes on the same principle, keyed on `judgment_id`. Only rows that
parsed successfully count as done, so unparseable rows are re-judged on the next
pass and both rows survive.

---

## Data formats

### `data/questions.jsonl`

```json
{"question_id": "q0001", "positive": "...", "negative": "...",
 "source": "handwritten", "human_verified": true, "tags": ["health"]}
```

`question_id` must match `[A-Za-z0-9._-]+`. Lines starting with `//` are ignored.

### `runs/<name>/grid.jsonl`

One line per cell. `cell_id` is
`blake2b(question_id | polarity | perspective_id | provider_id | run_index)` —
deterministic across machines and processes, and deliberately **excluding** the
config hash so that adding a fourth provider does not change the identity of
cells that already ran.

### `runs/<name>/responses/*.jsonl`

One line per API call attempt. Carries the cell ID, all five grid coordinates,
the full prompt sent, the raw response text, requested and reported model
strings, token counts, latency, cost estimate with the prices used, timestamps,
attempt counts, and an error object on failure. Append-only.

### `runs/<name>/judgments/*.jsonl`

One line per judge call, keyed on `judgment_id`. Always stores `judge_raw_text`
verbatim alongside the parsed object, so a parser change never requires
re-judging. `parse_ok` and `parse_error` record what happened.

---

## Analysis outputs

`analyze` writes `runs/<name>/analysis/`:

| File | Contents |
|---|---|
| `tidy.csv` | one row per judgment, every grid coordinate as a column |
| `score_by_provider.csv` | mean agreement, clustered CI, refusal and truncation rates |
| `score_by_perspective.csv` | the same, per provider × perspective |
| `perspective_spread.csv` | per provider: range and SD across perspective means |
| `consistency.csv` | mean inconsistency, indeterminate rate, fully-consistent rate |
| `consistency_pairs.csv` | the underlying matched pairs |
| `run_variance.csv` | within-cell SD across the D duplicates |
| `cost_latency.csv` | per-provider cost, tokens, p50/p95 latency, mean attempts |

`tidy.parquet` is also written when `pyarrow` is installed (`uv sync --extra
analysis`); CSV is always written regardless.

---

## Adding a provider

Every provider is a subclass of `BaseProvider` with one `_call` method, selected
by the `adapter` field in config. To add one, write the subclass in
`src/llmbench/providers/`, register it in `registry.py`, and add a config entry.

**For a local model**, no new code is needed at all. vLLM, Ollama and llama.cpp
all serve the OpenAI wire format, so the existing `openai_compatible` adapter
covers them:

```yaml
- id: local-llama
  adapter: openai_compatible
  model: llama-3.1-8b-instruct
  base_url: http://localhost:8000/v1
  api_key_env: LOCAL_API_KEY # servers usually ignore it
  max_concurrency: 2
  pricing: { input_per_mtok: 0.0, output_per_mtok: 0.0 }
```

A calibration note for the Z2 G9 (i9-12900, 32 GB, CPU only): expect roughly
5–15 tokens/sec for a quantised 7–8B model. 36,000 calls is not feasible there in
this timeframe — a local provider realistically means running a subset of the
grid.

---

## Adapter status

Be aware of what has and has not been exercised:

| Adapter | Status |
|---|---|
| `mock` | Exercised end to end — 1,080 cells through all four phases |
| `anthropic` | Written against the current documented SDK surface; **not run against a live key here** |
| `openai` | Same — **not run against a live key here** |
| `openai_compatible` | Same — **not run against a live server here** |
| `google` | Same — **not run against a live key here**; response field access is defensive |

Smoke test each real provider with `--limit 20` before launching the full grid.
The retry, resume, budget and parsing logic is provider-independent and is fully
covered by tests; what is unverified is the per-vendor request and response
shapes.

SDK-level retries are disabled (`max_retries=0`) on every real adapter, because
this harness owns retry and backoff and records `attempts_used` and latency per
call. Leaving the SDK default of 2 in place would silently triple the retry count
and make recorded latency uninterpretable.

---

## Running on the cluster

Everything is headless and pure Python; no display, no GUI, no local model
weights.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv sync --extra providers --extra analysis
```

```bash
nohup uv run llmbench run -c configs/experiment.yaml > run.log 2>&1 &
```

Interrupting is safe at any point; re-running the same command resumes. The
Python version is pinned in `.python-version` and `pyproject.toml`, and `uv.lock`
pins every dependency, so the cluster gets the same environment as the dev
machine.

`pandas` is pinned below 3.0 deliberately: pandas 3.x makes `pyarrow` a hard
import-time dependency, and `pyarrow`'s native library is blocked by Application
Control policy on the Windows development machine. Analysis degrades to CSV-only
when `pyarrow` is absent; nothing else is affected.

---

## Testing

111 tests, no network, no API spend.

```bash
uv run pytest
```

| File | Covers |
|---|---|
| `test_ids.py` | ID determinism, including across processes with different `PYTHONHASHSEED`; delimiter-injection collisions; config-hash semantics |
| `test_resume.py` | No duplicates, no gaps, error rows kept and retried, raw files never rewritten, truncated final lines tolerated |
| `test_retry.py` | Error classification, exponential growth, jitter bounds, retry-then-succeed, fatal-not-retried, exhaustion |
| `test_budget.py` | Reservation accounting, cap enforcement under concurrency, clean abort mid-run |
| `test_judge_parsing.py` | Clean/fenced/prose-wrapped JSON, truncation, out-of-range scores rejected rather than clamped, schema violations |
| `test_grid.py` | Cartesian product, determinism, shuffle, question-set validation |
| `test_pipeline_mock.py` | All four phases end to end; re-judging without touching response files; shipped configs valid |

---

## Layout

```
configs/          experiment.yaml (the real grid), smoke.yaml (zero spend)
data/             questions.jsonl (replace me), questions.sample.jsonl
runs/<name>/      grid.jsonl, responses/, judgments/, analysis/, manifest-*.json
src/llmbench/
  cli.py          the four commands
  config.py       pydantic schema, extra="forbid" everywhere
  ids.py          deterministic IDs
  grid.py         cartesian product + shuffled execution order
  storage.py      append-only JSONL, resume index
  runner.py       phase 2 orchestration
  judge.py        phase 3, including JSON extraction and the repair pass
  analyze.py      phase 4, clustered bootstrap
  budget.py       reservation-based spend cap
  retry.py        classification + backoff with jitter
  pricing.py      cost from config-pinned prices
  providers/      base, registry, mock, anthropic, openai, google
  prompts/        judge.md (the rubric), build.py
tests/
```
