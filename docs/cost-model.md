# Cost analysis

Budget: **$30,000**. This costs the full benchmark against it, using prices
measured from a real pilot run rather than estimated.

Everything below is arithmetic on two things: the per-call token counts recorded
in `responses.jsonl` and `judgments.jsonl`, and the four invoices from the pilot.
Nothing here is a vendor's list-price estimate.

## Summary

| | Q = 400 questions | Q = 800 (each question plus its negation) |
|---|---|---|
| One judge | $1,519 | $3,037 |
| Three judges, each model graded by the others | $2,949 | $5,898 |
| **Four judges, every model grades every answer** | **$3,664** | **$7,328** |

At the decided design — 400 questions, 18 identities, 4 models, 3 replicates,
cross-evaluated by all four — the benchmark costs about **$3,700**, or **$7,300**
if each question is also asked in negated form.

If answers run twice as long as the pilot's, double those: $7,300 and $14,700.
The upper figure is less than half the budget, so the design does not need
trimming to fit it.

**Every figure here is measured.** Meta was dropped from the benchmark, and with
it the one provider that had no key at pilot time. The pilot ran all four
remaining providers, so nothing below is an assumed rate.

## What one answer costs

The pilot billed **$2.13** for 120 answers and their judgments, across four
providers. Per provider, per answer:

| provider | per answer | how it ran |
|---|---|---|
| Anthropic | $0.01053 | batch, 50% discount |
| Google | $0.01067 | batch, 50% discount |
| OpenAI | $0.01033 | batch, 50% discount |
| xAI | $0.00567 | live — xAI cannot batch its current models |
| **mean** | **$0.00930** | |

All four were measured on the same pilot, so the mean carries no estimate.

## What cross-evaluation costs

Every answer is graded by every model, so judging is four times the work of
answering. The judges are not equally priced:

| judge | per grade | note |
|---|---|---|
| `gemini-3.1-pro-preview` | $0.00453 | cheapest; batch |
| `claude-opus-5-5` | $0.00810 | batch |
| `grok-4.7` | $0.00916 | live, and it prepends ~1,200 tokens of its own system prompt to every call |
| `gpt-5.5` | $0.01132 | dearest; batch |
| **all four, per answer** | **$0.03311** | |

So judging is **78% of the total bill**. That is the number to watch: the
answers are nearly incidental.

A grade is costed at roughly 1,650 input tokens (rubric, question, answer, and
the reference answer where one exists) and 480 output tokens including the
model's reasoning. That shape reproduces the pilot's actual Anthropic judging
bill, which is the only part of this that has been checked against an invoice.

## The arithmetic

    cost = Q × I × P × D × T

    Q  questions                  400
    I  identities                  18   (17 from the Identity Matrix, plus a control)
    P  models answering             4
    D  replicates per question      3
    T  cost per answer        $0.04241   ($0.00930 to answer + $0.03311 to grade)

    400 × 18 × 4 × 3  =  86,400 answers  →  345,600 grades  →  $3,664

Turned around, $30,000 would fund **147 identities** at 400 questions, or 74 if
every question is also negated. The design calls for 18. Money is not the
constraint on this study; the question set is.

## Why four judges rather than three

Grading an answer with the model that wrote it looks like a conflict, and the
obvious fix is to have each model graded only by the other three. That is cheaper
— $2,949 against $3,664 — but it throws away the measurement.

Running the full four-by-four matrix means every model also grades itself, and
the difference between a model's self-grade and the other three's grade of the
same answer **is** self-preference bias, measured directly rather than argued
about. The project's own grading report named that as the first objection anyone
would raise. For $715 it stops being an objection and becomes a reported result.

## What this does not cover

- **Reruns.** A prompt template corrected after a full run means paying for that
  run twice. The most likely single overrun, and the formula has no term for it.
- **Human raters** on a subsample, the third of the four priorities set for the
  project. Not an API cost.
- **The pilot's prompts were short.** They came from a generic benchmark, not
  from this question set. Real questions ask for about 250 words on contested
  historical material, which reasoning models think harder about, and reasoning
  is billed as output. This is why the doubled figures are quoted alongside.
- **Price changes.** Every rate here was read in late September 2026.

A sensible reserve is the doubled figure: budget **$7,300** for Q=400 or
**$14,700** with negations, and expect to spend about half.

## Reproducing any of this

```bash
python merge.py                     # fold the per-script files together
```

Every row of `responses.jsonl` and `judgments.jsonl` records `input_tokens`,
`output_tokens` and `reasoning_tokens`. Recomputing the cost after any change is
arithmetic on files already on disk, with no new API calls.

One correction worth recording, because it would have thrown the numbers out by
a factor of three: **Google and xAI both bill for reasoning tokens that they
report outside their output counts** — Gemini in `thoughtsTokenCount`, xAI in
`completion_tokens_details.reasoning_tokens`. Counting only the obvious field
under-reported Google 3.3× and xAI 3.1× against the real invoices. Both are now
folded into `output_tokens`. OpenAI and Anthropic include reasoning already, and
their predicted cost matched the bill to the cent and to 5% respectively.
