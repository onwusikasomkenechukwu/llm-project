# Analysis methods

`analyze.py` consumes merged judgments and optionally merged responses. It uses
Python's standard library. It makes no network requests and does not require
pandas, NumPy or plotting libraries.

## Estimand and intervals

For each table group and metric, first average usable observations within each
question ID, then average those question means. Each question gets equal weight.
Polarities, identities, providers, judges, passes and replicates belonging to one
question stay in that question's cluster.

The interval is the 2.5th and 97.5th percentile of 2,000 bootstrap means, with
linear interpolation between percentiles. Each draw samples question means with
replacement. `--bootstrap` changes the draw count and `--seed` controls the
pseudorandom generator. A group with one question gets a mean but no interval.
Fewer than 20 questions produces an exploratory-use warning.

These are descriptive, unadjusted intervals, not a multiple-comparison testing
procedure or evidence of a model ranking. Missing observations can change the
composition within questions. Inspect coverage and the matched counts before
comparing results.

## Tables

| File | Contents |
|---|---|
| `by_provider.csv` | Answering-provider summaries |
| `by_identity.csv` | Stated-identity summaries |
| `by_question_type.csv` | Question-type summaries |
| `by_judge.csv` | Judge summaries on observed answers |
| `by_polarity.csv` | Positive and negated summaries |
| `judge_matrix.csv` | Answering provider by judge |
| `identity_differences.csv` | Each identity minus the no-identity control |
| `model_differences.csv` | Pairwise provider differences, comparison minus baseline |
| `self_preference.csv` | A provider judging itself minus other judges on the same answers |
| `replicate_variability.csv` | Replicate means and sample standard deviations within each question/polarity/identity/provider |

Summary metrics are accuracy, completeness, objectivity, sourcing, total,
hard-fail rate and premise handling. Premise handling includes only loaded
questions. Raw totals are not set to zero on a hard fail; the failure rate remains
separate. Hard-fail rates range from zero to one.

`n_questions` counts contributing clusters. `n_observations` counts observations
before the question averages, not independent samples. CSV blanks represent
unavailable values; an empty table can occur when no control or matched pair exists.

## Matching

Identity contrasts match question, polarity, provider, replicate, judge and pass.
Model contrasts match question, polarity, identity, replicate, judge and pass.
Only matched pairs contribute. The reported sign is comparison minus baseline.
`unmatched_cells` counts cells with only one member of the pair.

Self-preference first averages each judge's passes on an answer. It subtracts
the equally weighted mean of the other judges from the answering provider's own
grade, then averages those differences by question. An answer needs both a self
grade and at least one other judge. This contrast describes observed grading,
not a causal effect of authorship disclosure.

Replicate variability first restricts each replicate to the same available
judge/pass panel. Its standard deviation is across those replicate means, not
across individual grades. A single replicate or no common panel has no standard
deviation.

## Validation

Duplicate judgment keys must be resolved with `merge.py` before analysis.
Malformed identifiers or inconsistent metadata stop the command. Invalid scores,
missing hard-fail values, provider errors and invalid premise-handling values
are excluded and counted by reason. No usable judgments is an error.

Mixed run IDs, mixing tagged and legacy untagged rows, and multiple model
versions for the same judge or answerer are rejected. Answerer-version validation
requires `--responses`. Output `summary.json` records input SHA-256 hashes,
versions, run ID, seed, draw count, exclusions and coverage.

Coverage uses the observed judge/pass panel; it cannot infer a wholly absent
judge or an uncollected question. With responses supplied, it also reports
unjudged and failed answers and rejects orphan grades. Use `check_run.py` with
the intended grid, or a manifest's `finish`, for complete-run verification.
