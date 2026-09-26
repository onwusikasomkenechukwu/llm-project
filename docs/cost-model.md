# Cost model

Solving `B = Q × I × P × D × T` for `I`, with `T` derived from the first pilot's
actual invoices rather than from estimates. Fixed: `Q` = 400 questions, `P` = 5
providers, `D` = 3 runs per cell.

## T is per cell, not per prompt

This is the one place it is easy to be wrong by an order of magnitude. `T` has
to be the cost of a single **(question × identity × provider × run)** unit —
one answer plus its share of judging. The pilot billed **$2.13 for 120 cells**,
so:

    T = 2.13 / 120 = $0.01775

Not `2.13 / 10 prompts = $0.213`. The pilot's 10 prompts already had 3
identities and 4 providers folded into them, so dividing by prompts and then
multiplying by `I × P × D` again counts those twice and overstates the budget
about twelvefold.

## Where T comes from

| line | per cell | note |
|---|---|---|
| Anthropic answer | $0.01053 | batch, 50% off |
| Google answer | $0.01067 | batch, 50% off |
| OpenAI answer | $0.01033 | batch, 50% off |
| xAI answer | $0.00567 | live, no batch discount available |
| **mean answer** | **$0.00930** | across the four providers with keys |
| judging | $0.00845 | `claude-opus-5-5`, batch; $1.014 over 120 cells |
| **T** | **$0.01775** | |

Judging is **48% of T**. That is the largest single lever in the model, and it
is a knob rather than a constant — see below.

## Identities affordable at each budget

`I = B / (Q × P × D × T) = B / (6000 × T)`

| budget | I at T | I at 1.5×T | I at 2×T |
|---|---|---|---|
| $5,000 | **47** | 31 | 23 |
| $10,000 | **94** | 63 | 47 |
| $15,000 | **141** | 94 | 70 |

The 1.5× and 2× columns are not padding. The pilot ran FLASK prompts — short,
generic tasks. The real questions are longer, ask for roughly 250-word answers,
and are the kind of contested historical material that makes a reasoning model
think harder. Reasoning is billed as output, so token growth there is the most
likely source of drift.

## The answer that matters more

Run the formula the other way and the budget question mostly dissolves:

| grid | at T | at 2×T |
|---|---|---|
| I=18 (17 identities + control), Q=400 | **$1,917** | $3,834 |
| I=18, Q=800 (each question plus its negation) | $3,834 | $7,668 |
| I=6, Q=400 | $639 | $1,278 |
| I=3, Q=400 | $320 | $639 |

**The full intended design costs about $1,900, and about $3,800 with polarity.**
Even doubling T for longer answers, the whole thing fits inside $5,000. The
binding constraint on this study is not money; it is the 400 questions, which we
still do not have.

So the useful framing for the $5k–$15k question is not "how many identities can
we afford" — 47 at the low end, against 17 in the design — but "what else is
worth buying with the headroom." Candidates, in order of what they add:

1. **A second judge from a different family** over the full grid, not just a
   subset. Doubles the judging line (+48% of T, so ~$920 at Q=400, I=18) and
   directly answers the self-preference objection the law school's own grading
   report raises first.
2. **Polarity**, if the design wants each question and its negation. Doubles
   everything: +$1,900.
3. **Higher D** for variance estimates. D=5 instead of 3 is +67%.
4. **More questions.** The cheapest way to strengthen a benchmark, and
   recommendation 5 in their own report.

## The judge is the knob

Judging is 48% of T, so the judge model moves everything:

| judge | judge/cell | T | I at $5k | I at $10k | full I=18 grid |
|---|---|---|---|---|---|
| `claude-opus-5-5` | $0.00845 | $0.01775 | 47 | 94 | $1,917 |
| `claude-sonnet-5` | $0.00423 | $0.01352 | 62 | 123 | $1,461 |
| `claude-haiku-4-5` | $0.00211 | $0.01141 | 73 | 146 | $1,233 |

Worth testing rather than assuming: grade a few hundred rows with both Opus and
Sonnet and check whether the scores move. If they agree, Sonnet saves ~$450 on
the full grid and the difference funds the second judge outright.

## What this model assumes

- **Meta is not in it.** There was no Meta key at pilot time, so Meta's answer
  cost is the mean of the other four. It runs live (no batch endpoint), which
  pushes up, and Muse Spark is positioned as cheap, which pushes down. Replace
  this with a measured number before committing a five-figure budget.
- **Batch pricing** for OpenAI, Anthropic and Google (50% off). xAI and Meta
  run live at full rates.
- **Re-grading overhead is included.** The pilot billed 149 judge calls for 120
  cells — a 1.24× factor from rows that had to be graded twice. Leaving that in
  is deliberate; some of it will always happen.
- **Reasoning tokens are counted.** They were not, at first: Google and xAI both
  report them outside their output counts and bill for them anyway, which
  under-reported those two columns threefold. See `docs/batch-apis.md`.
- **No failed-run headroom.** A prompt template fixed after a full run means
  paying for that run twice. Budget a contingency the formula does not contain.

## Reproducing this

Every number above comes from `responses.jsonl` and `judgments.jsonl` plus the
four invoice figures. Both files record `input_tokens`, `output_tokens` and
`reasoning_tokens` per row, so recomputing `T` after any change is arithmetic on
files already on disk — no new API calls.
