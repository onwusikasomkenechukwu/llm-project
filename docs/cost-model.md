# Cost analysis

The law school's budget is **$30,000**; the request on the table is **$15,000**.
This document keeps the method behind the figures. The figures themselves, with
every table, are in the README's [Costs](../README.md#costs) section, and this
file deliberately does not repeat them so the two cannot drift apart.

**Headline, five providers, 18 identities, 400 questions, D=3, all five
grading:** **$5,618**, or **$11,236** if every question is also asked negated. A
question-clustered bootstrap puts the 99% interval at $4,679–$6,215 and
$9,359–$12,430, so both designs fit a $15,000 request.

## Where each number comes from

Every row of `responses.jsonl` and `judgments.jsonl` records `input_tokens`,
`output_tokens` and `reasoning_tokens`. The cost of a row is those tokens at the
provider's own rate:

| provider | role | effective rate, $ per million tokens (input / output) | batch |
|---|---|---|---|
| OpenAI `gpt-5.5` | answers, grades | 2.50 / 15.00 | yes, discount included |
| Anthropic `claude-opus-5-5` | answers, grades | 2.00 / 10.00 | yes, discount included |
| Google `gemini-3.1-pro-preview` | answers, grades | 1.00 / 6.00 | yes, discount included |
| xAI `grok-4.7` | answers | 2.00 / 6.00, cached input 0.50 | no, runs live |
| Muse `muse-spark-1.3` | answers, grades | 2.00 / 6.00 | no, runs live |
| xAI `grok-4.3` | grades | billed per request, read from the batch results | yes |

xAI's batch results report what each request was billed, as
`cost_in_usd_ticks` (1e-10 USD), so its grading cost is the billed figure rather
than tokens times a rate: $0.2209 for the 90 pilot grades, $0.00245 each.

From those per-row costs:

    C_answer[m]   mean cost of one answer from model m
    C_judge[j]    mean cost of one grade from grader j
    C             mean cost of one graded pair = C_answer/M + C_judge, over all 450

    T     = M² · N · P · R · D  =  5² × 18 × 400 × 1 × 3  =  540,000 graded pairs
    total = T × C

`M²` is the two roles each model plays, so the 108,000 answers sit inside `T`
rather than beside it. The cost of one answer plus its five grades ($0.05202) is
a per-answer figure, not `C`; multiplying it by `T` counts the grading five
times.

The intervals come from resampling the six pilot **questions**, 20,000 times,
because every pair from one question shares its answer lengths. Resampling the
450 pairs individually would treat correlated observations as independent and
give intervals far too narrow. Six clusters still under-cover, which is why the
README quotes the 99% upper bound as the planning ceiling.

## Checked against the invoices

The method was tested on an earlier pilot, when four accounts were billing, by
predicting the cost from recorded tokens before the bills arrived:

| account | predicted | billed | error |
|---|---|---|---|
| xAI | $1.515 | **$1.51** | −0.3% |
| Anthropic | $0.910 | **$0.91** | 0.0% |
| OpenAI | $0.762 | **$0.76** | −0.3% |
| Google | $0.571 | **$0.58** | +1.6% |
| **total** | **$3.758** | **$3.76** | **+0.05%** |

That run graded xAI with `grok-4.7` live. Its prediction depended on three
corrections holding at once — cached input billed at $0.50 per million rather
than $2.00, reasoning tokens billed although reported outside
`completion_tokens`, and no batch discount — and any one being wrong would have
shown as a visible error. Muse joined after that reconciliation, and its rate is
the list price. `grok-4.3` grading needs no prediction, since its cost is read
from the bill.

## Two providers hide tokens they bill for

Google reports reasoning in `thoughtsTokenCount`, outside
`candidatesTokenCount`; xAI reports it in
`completion_tokens_details.reasoning_tokens`, outside `completion_tokens`. Both
bill for it. Counting only the obvious field under-reported Google 3.3× and xAI
3.1× against the real invoices. Both are folded into `output_tokens` in every
script. OpenAI and Anthropic include reasoning already.

## What this does not cover

- **Reruns.** A prompt template corrected after a full run means paying for that
  run twice. The most likely single overrun, and the formula has no term for it.
- **Human raters** on a subsample. Not an API cost.
- **The question mix.** A factual question runs 36% cheaper through the grid than
  an open-ended one, so the real 400's mix of types moves the total.
- **Price changes.** Every rate here was read in late September and early October
  2026.

## Reproducing any of this

```bash
python merge.py
```

Then recompute from the rows on disk. No step needs a new API call.
