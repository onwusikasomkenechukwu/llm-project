# Rubric-first judge prompt: cache test, 16 October 2026

40 answers from the 15 October cue run (8 per answering model) were regraded with
the judge prompt reordered rubric-first, so the rubric, question and reference
form a prefix shared by every grade of a question, and with an Anthropic
`cache_control` breakpoint before the answer. A control regraded the same 40
the same day with the unchanged prompt. All calls were live.

## Caching

| grader | calls with a cache hit | input served from cache |
|---|---|---|
| Anthropic | 39 of 40 | 79% |
| OpenAI | 0 of 40 | 0% — shared prefix just under its 1,024-token minimum |
| xAI | every call | ~46% — its own ~1,200-token system prompt, cached before the change too |
| Muse | 2 of 33 | 5% |

Google was not tested: its implicit-cache minimum is reported as 4,096 tokens,
far above this prompt.

## Grades

| grader | old prompt today − original | new prompt − old prompt, same day |
|---|---|---|
| Anthropic | −0.15 | **−0.68** (sourcing −0.53) |
| OpenAI | −0.03 | **−1.40** (sourcing −0.75, completeness −0.40) |

The old prompt reproduces the original grades closely, so the shift comes from
the reordering, not run-to-run noise. Graders reading the rubric before the
answer score it more strictly, mostly on sourcing.

## Decision

Reverted. The saving would have been on Anthropic alone, about 30% of its
grading cost or roughly $340 of the $7,577 full design, and it would have made
every new grade incomparable with the pilot and the cue run. The runners keep
recording cached input tokens, so cost accounting now sees cache hits such as
xAI's.
