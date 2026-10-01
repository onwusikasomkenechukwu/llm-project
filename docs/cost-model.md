# Cost analysis

Budget: **$30,000**. This costs the full benchmark against it, using prices
measured from a real pilot run rather than estimated.

Everything below is arithmetic on two things: the per-call token counts recorded
in `responses.jsonl` and `judgments.jsonl`, and the invoices from the pilot runs.
Nothing here is a vendor's list-price estimate, and the method has been checked
against the bills — see the next section.

## Summary

| | Q = 400 questions | Q = 800 (each question plus its negation) |
|---|---|---|
| One judge | $1,818 | $3,635 |
| Three judges, each model graded by the others | $3,654 | $7,307 |
| **Four judges, every model grades every answer** | **$4,509** | **$9,018** |

At the decided design — 400 questions, 18 identities, 4 models, 3 replicates,
cross-evaluated by all four — the benchmark costs about **$4,500**, or **$9,000**
if each question is also asked in negated form.

If answers run twice as long as these, double those: $9,000 and $18,000. The
upper figure is still under two thirds of the budget, so the design does not need
trimming to fit it.

**Every figure here is measured.** Meta was dropped from the benchmark, and with
it the one provider that had no key at pilot time. The pilot ran all four
remaining providers, so nothing below is an assumed rate.

## Checked against the invoices

The pilot's cost was predicted from recorded tokens before the bills arrived, and
then compared against them:

| account | predicted | billed | error |
|---|---|---|---|
| xAI | $1.515 | **$1.51** | −0.3% |
| Google | $0.571 | **$0.58** | +1.6% |
| Anthropic | $0.910 | pending | |
| OpenAI | $0.762 | pending | |
| **checked so far** | **$2.086** | **$2.09** | **+0.2%** |

xAI is the useful one. It is the only account whose prediction depends on three
separate corrections holding at once: cached input billed at $0.50 per million
rather than $2.00, reasoning tokens billed although they are reported outside
`completion_tokens`, and no batch discount because its current models refuse
batch. Landing within a cent means all three are right, and it is the provider
where getting this wrong would have cost the most, since xAI is 45% of the
grading bill.

Scaled onto the full grid, the observed +0.2% moves the $4,509 projection to
about $4,518. Anthropic and OpenAI are still outstanding, so this is not a
complete reconciliation — but the two accounts that were hardest to model are the
two that have been confirmed.

## What one answer costs

A second pilot measured this directly: 72 answers cross-evaluated by all four
providers, 288 grades. Per provider, per answer:

| provider | per answer | how it ran |
|---|---|---|
| Anthropic | $0.01002 | batch, 50% discount |
| Google | $0.00996 | batch, 50% discount |
| OpenAI | $0.00686 | batch, 50% discount |
| xAI | $0.00560 | live — xAI cannot batch its current models |
| **mean** | **$0.00811** | |

All four were measured on the same pilot, so the mean carries no estimate.

## What cross-evaluation costs

Every answer is graded by every model, so judging is four times the work of
answering. The judges are not equally priced:

| judge | per grade | note |
|---|---|---|
| `gemini-3.1-pro-preview` | $0.00543 | cheapest; batch |
| `gpt-5.5` | $0.00887 | batch; terse, 358 output tokens per grade |
| `claude-opus-5-5` | $0.01014 | batch |
| `grok-4.7` | $0.01964 | live, and it emits ~2,700 output tokens per grade |
| **all four, per answer** | **$0.04408** | |

So judging is **84% of the total bill**, and **xAI alone is 45% of the judging**
despite being one grader of four: `grok-4.7` reasons at length and reasoning is
billed as output. Judging is the number to watch; the answers are nearly
incidental.

Measured per grade: 1,886 input tokens (rubric, question, answer, and the
reference answer where one exists) and 1,076 output tokens including reasoning,
averaged over the four graders. An earlier version of this document assumed 480
output tokens and so ran 23% low overall — the correction is why the figures
above changed.

## The arithmetic

    cost = Q × I × P × D × T

    Q  questions                  400
    I  identities                  18   (17 from the Identity Matrix, plus a control)
    P  models answering             4
    D  replicates per question      3
    T  cost per answer        $0.05219   ($0.00811 to answer + $0.04408 to grade)

    400 × 18 × 4 × 3  =  86,400 answers  →  345,600 grades  →  $4,509

Turned around, $30,000 would fund **119 identities** at 400 questions, or 60 if
every question is also negated. The design calls for 18. Money is not the
constraint on this study; the question set is.

## Why four judges rather than three

Grading an answer with the model that wrote it looks like a conflict, and the
obvious fix is to have each model graded only by the other three. That is cheaper
— $3,654 against $4,509 — but it throws away the measurement.

Running the full four-by-four matrix means every model also grades itself, and
the difference between a model's self-grade and the other three's grade of the
same answer **is** self-preference bias, measured directly rather than argued
about. The project's own grading report named that as the first objection anyone
would raise. For $855 it stops being an objection and becomes a reported result,
and the second pilot produced it: Google grades its own answers 1.07 points above
what the other three give them, while Anthropic and xAI grade themselves lower
than the panel does.

## What this does not cover

- **Reruns.** A prompt template corrected after a full run means paying for that
  run twice. The most likely single overrun, and the formula has no term for it.
- **Human raters** on a subsample, the third of the four priorities set for the
  project. Not an API cost.
- **Six questions is a small sample for a token average.** They are the right
  shape — the project's own worked examples, with real loaded premises — but a
  longer or more contested question could lengthen both answers and grades, and
  reasoning is billed as output. This is why the doubled figures are quoted
  alongside.
- **Price changes.** Every rate here was read in late September 2026.

A sensible reserve is the doubled figure: budget **$9,000** for Q=400 or
**$18,000** with negations, and expect to spend about half.

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
