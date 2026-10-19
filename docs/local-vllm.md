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
| questions | 150 (`samples/prompts-2026-10-19.xlsx`, built from the team sheet on 19 Oct) |
| answers | 150 × 3 replicates × 5 models = **2,250** |
| grades | 2,250 × 5 judges = **11,250** |

115 of the 150 carry gold-standard elements and are graded against them; 35 do
not yet and are graded on their own merits. Two are typed Normative, a type the
rubric dropped; they are kept and graded without premise handling.

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
python vllm_offline.py answer samples/prompts-2026-10-19.xlsx --identities none \
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
python vllm_offline.py answer samples/prompts-2026-10-19.xlsx --identities none \
    --models <m1>,<m2>,<m3>,<m4>,<m5> <tuned settings>
python vllm_offline.py judge responses-vllm_offline.jsonl --prompts samples/prompts-2026-10-19.xlsx \
    --models <m1>,<m2>,<m3>,<m4>,<m5> <tuned settings>
python analyze.py judgments-vllm_offline.jsonl --responses responses-vllm_offline.jsonl --out-dir analysis/vllm
```

Models run one after another, each loaded once for its whole share. An
interrupted run resumes by running the same command again.
