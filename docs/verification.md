# Verification

Offline checks cover collection, grading, analysis, run records and configuration
consistency. The provider clients use fixture responses during testing.

## Checks completed

| Area | Evidence |
|---|---|
| Existing pipeline | Workbook limits and validation, identity framing, blind grading, score parsing, completion detection, merge selection, and retry behavior tested across the runners |
| Provider adapters | Mocked OpenAI, Anthropic, Google and compatible chat clients; installed Google SDK request types exercised |
| Batch lifecycle | Submit, fetch, resume, pass isolation, incompatible inputs, dry runs and bounded retries tested |
| Sequential lifecycle | Two-provider collection and resume tested with a mocked transport |
| Samples | Both generators tested in temporary directories; FLASK download replaced by a deterministic fixture |
| Analysis | Question weighting, seeded bootstrap, matching, hard-fail policy, replicate variability, invalid rows and exports tested |
| Manifest | Creation, execution, merge, complete preflight, analysis, provenance, interrupted-run recovery, locks and integrity checks tested |
| Drift guard | Deliberate rubric, model, token-limit and identity changes rejected; comments accepted; inconsistent copies cannot become the baseline |
| Existing pilot | Strict preflight passed 90 answers and 450 judgments across six questions |
| Pilot analysis | All 450 grades usable; ten tables and summary generated; five model means reproduced |
| CLI smoke checks | All four provider scripts passed dry runs |
| Manifest CLI | Created runs/offline-verification, recorded a dry run and verified integrity; correctly reported collection incomplete |
| Final suite | 40 unittest tests passed |
| Syntax | All project Python scripts and tests compiled |

The fixture manifest test exercises collection output through merge, strict
preflight, analysis and artifact verification. All fixture files live in temporary
directories. Existing pilot response and judgment files were not rewritten.

## Reproduce

Use the project's installed environment:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe check_drift.py
.venv\Scripts\python.exe check_run.py samples\rubric_pilot.xlsx --polarity pos --expected-questions 6 --identities none,black-american,white-american --duplicates 1 --responses responses.jsonl --judgments judgments.jsonl
.venv\Scripts\python.exe analyze.py judgments.jsonl --responses responses.jsonl --out-dir analysis\pilot
```

The retained example manifest is under `runs/offline-verification/manifest.json`.
It records an offline smoke check, not a completed benchmark. Analysis exports and
run directories are excluded from Git.

## Limits

No paid API requests were submitted. The checks establish local behavior,
contract consistency and handling of representative provider results; they do
not establish current service availability, account quota, model-alias stability,
live token billing, or completion of a new remote batch. The sample downloader's
current upstream availability was not checked.

Tests ran on the existing Python 3.14 environment with openpyxl 3.1.5, openai
3.19.1, anthropic 1.8.0 and google-genai 2.25.0. The Google SDK emitted an internal
deprecation warning about a Python type scheduled for removal in 3.17; it did not
fail these checks. Other Python and SDK versions were not separately tested.

An abrupt termination can leave a partial final JSONL line or a stale lock.
Malformed JSON stops processing rather than being silently discarded. Inspect
and repair the partial line before recording recovery. Never remove a lock
belonging to a live process.

Local hashes are integrity evidence, not cryptographic signatures. The drift
guard detects code/configuration drift, not changes inside a provider behind an
unchanged model identifier. Statistical results from six questions remain
exploratory.
