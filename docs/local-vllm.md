# Open-weight run on the IRB-411 GPU machine

Dr. Aryal, 19 October 2026: the same design as the API run, with the five
open-weight models he downloaded in place of the five providers. Every model
answers every question three times, then every model grades every answer, against
the current rubric, with the four subscores saved on every grade. No identities
for this first pass. vLLM offline batched inference, tuned for prompts per second.

`vllm_offline.py` does it. It shares the rubric, prompt building, output rows and
resume logic with the API runners, and `check_drift.py` holds it to them.

## Size

| | |
|---|---|
| questions | 162 (`samples/prompts-2026-10-20.xlsx`, built from the team sheet on 20 Oct by `samples/make_prompts.py`) |
| answers | 162 × 3 replicates × 5 models = **2,430** |
| grades | 2,430 × 5 judges = **12,150** |

120 of the 162 carry gold-standard elements and are graded against them; 42 do
not yet and are graded on their own merits. Since 19 Oct the team rewrote the
first ten Jim Crow questions and added ten more (so no Normative questions are
left), and started an Environmental Justice tab (two draft questions). Voting
Rights, the 14th Amendment and the Civil Rights Movement tabs have IDs but no
questions yet. The 19 Oct set (150) stays in `samples/` for any run already made
on it.

"Quality" in the team sheet's rubric tab is v1. The current rubric (v2, the PDF)
renamed it **Completeness**, so the subscores on every row are `accuracy`,
`completeness`, `objectivity`, `sourcing`, plus `total`, `premise_handling` and
`hard_fail`.

## Defaults, as Dr. Aryal asked

- **Sampling** is each model's own, from its `generation_config.json`
  (`llm.get_default_sampling_params()`). Only `max_tokens` is set, as a ceiling:
  4,000 to answer, 3,000 to grade (`--judge-tokens` to raise it for a model that
  reasons at length, as Muse needed).
- **System prompt**: none is sent for these prompts, so each chat template applies
  its model's default. Where a cue puts text in the system prompt, it is sent as
  the default followed by ours, never in its place.
- **Reasoning** models' thinking (`<think>` blocks, gpt-oss channels) is split off
  the answer before it is saved or graded, and counted in `reasoning_tokens`.

## On the machine

```bash
git clone https://github.com/onwusikasomkenechukwu/llm-project.git && cd llm-project
python -m venv .venv && source .venv/bin/activate
pip install vllm openpyxl
nvidia-smi
python vllm_offline.py --list-models
```

`--list-models` prints the cached models and the short name each gets in the
output. Use the five Dr. Aryal downloaded, in the order they should run.

### 1. Check one model end to end

```bash
python vllm_offline.py answer samples/prompts-2026-10-20.xlsx --identities none \
    --models <model-1> --limit 5 --out test-answers.jsonl
```

Read a few answers in `test-answers.jsonl`: thinking must not be left in
`response`, and nothing should stop at the ceiling.

### 2. Tune for throughput

Every run appends prompts/s and tokens/s to `throughput-vllm_offline.jsonl`.
Tune on about 300 prompts (`--limit 100` with 3 replicates), changing one
setting at a time:

| setting | try | effect |
|---|---|---|
| `--tensor-parallel-size` | 1 vs the GPU count | a model that fits on one GPU is usually faster as one copy per GPU (below) than split across all of them |
| `--max-num-seqs` | 128, 256, 512 | sequences decoded together; higher until memory or speed stops improving |
| `--max-num-batched-tokens` | 8192, 16384, 32768 | prefill per step |
| `--max-model-len` | 8192 or 16384 | a smaller ceiling leaves more memory for KV cache |
| `--gpu-memory-utilization` | 0.90–0.95 | |

[vllm-tuner](https://github.com/kryvokhyzha/vllm-tuner) (`--preset high_throughput`)
searches the same settings automatically against a server. Its best values pass
straight to these flags.

**One copy per GPU**, for any model that fits on one:

```bash
CUDA_VISIBLE_DEVICES=0 python vllm_offline.py answer ... --shard 0/2 &
CUDA_VISIBLE_DEVICES=1 python vllm_offline.py answer ... --shard 1/2 &
wait && cat responses-vllm_offline-shard*.jsonl > responses-vllm_offline.jsonl
```

### 3. The run

```bash
python vllm_offline.py answer samples/prompts-2026-10-20.xlsx --identities none \
    --models <m1>,<m2>,<m3>,<m4>,<m5> <tuned settings>
python vllm_offline.py judge responses-vllm_offline.jsonl --prompts samples/prompts-2026-10-20.xlsx \
    --models <m1>,<m2>,<m3>,<m4>,<m5> <tuned settings>
python analyze.py judgments-vllm_offline.jsonl --responses responses-vllm_offline.jsonl --out-dir analysis/vllm
```

Models run one after another, each loaded once for its whole share. An
interrupted run resumes by running the same command again.

## The demographic cue screen (from 28 October)

Dr. Aryal's `cue_templates_demographics.xlsx`: 16 dimensions beyond race,
gender and education (politics, religion, disability, income, occupation,
place, citizenship, criminal record, writing style and more), each in the user
turn and as saved memory, on a balanced half of the questions. That is 312
prompts per question per model, 126,360 answers and 631,800 grades, about seven
days on the Dell.

```bash
git pull
python samples/half_prompts.py samples/prompts-2026-10-20.xlsx   # only if the half is missing
tmux new -s demo
conda activate llm
bash vllm_demographics.sh
```

It runs in six waves, user-turn cues first and politics in the first wave
(about 14 hours). Each wave is graded and analysed before the next begins:
`runs/demographics/analysis/screen-strict/report.md` gives each focal contrast's
gap per model and whether it passes the gate to the frontier pilot (0.2 points
in at least two of five models). `scores/by_topic*.csv` and
`scores/by_provider_question_type.csv` show which kinds of question score
lowest, and `probes/report.md` what race, gender and schooling the models read
into each cue.

The cue files are built on the laptop, where the law school's sheet is kept:

```bash
python cues.py "cue_templates_demographics(Scenarios).csv" "cue_templates_demographics(Identities).csv" \
    --probes "cue_templates_demographics(Probes).csv" --out cues-demographics.jsonl
```
