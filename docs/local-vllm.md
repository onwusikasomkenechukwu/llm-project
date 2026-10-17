# Running the cue experiment on open-weight models

Dr. Aryal's proposal (16 October 2026): run the cue scenarios at scale on
open-weight models served locally with vLLM, and check whether the effects seen
on the frontier APIs carry over. Not an exact map, a cheaper approximation.

Hardware assumed: 2 × RTX A6000 (48 GB each, 96 GB total, Ampere) and 256 GB RAM,
on the cluster or a machine in 411.

## Size

The team workbook has **76 questions** written so far. At 105 cue prompts each:

| | per model |
|---|---|
| answers | 7,980 |
| grades, per judge | 7,980 |

Measured on the cue run, a non-reasoning model writes about 250 output tokens
per answer, and a grade is about 1,300 input and 400 output tokens. So one model
answering everything is about 2.0M output tokens, and one judge grading one
model's answers about 3.2M output tokens and 10.4M input. Every judge prompt
shares the same rubric prefix, so `--enable-prefix-caching` should make most of
that input nearly free.

**Time is output tokens divided by measured throughput.** At 500 output tokens a
second, a model's answers take about 70 minutes and one judge pass about 1.8
hours. That figure is a placeholder until the throughput test below replaces it.

## Models that fit in 96 GB

Ampere has no FP8 compute, so the options are 16-bit weights or 4-bit (AWQ or
GPTQ, through vLLM's Marlin kernels). Both cards together, `--tensor-parallel-size 2`:

| model | open-weight relative of | weights | fits |
|---|---|---|---|
| Llama 3.3 70B Instruct, AWQ 4-bit | Meta | ~40 GB | yes, with KV cache to spare |
| Gemma 3 27B, 16-bit | Google | ~55 GB | yes |
| Qwen3 32B, 16-bit | — | ~65 GB | yes, smaller KV cache |
| gpt-oss-20b | OpenAI | ~13 GB | yes; the 120b needs checking on Ampere |

One model per vendor where one exists is what makes "does it translate to the
frontier model" answerable.

## Throughput test

1. Install vLLM and [vllm-tuner](https://github.com/kryvokhyzha/vllm-tuner) on the
   machine (Python 3.11–3.13, `uv pip install vllm "vllm-tuner[all]"`).
2. Tune for throughput, one model at a time:
   `python -m vllm_tuner.cli.main run --model <hf-id> --preset high_throughput`.
   It searches `gpu_memory_utilization`, `max_num_seqs` and
   `max_num_batched_tokens`, restarting the server for each trial.
3. Serve the best configuration and push a sample of real cue prompts through
   `sequential.py --providers local` at high concurrency. Record prompts per
   second and output tokens per second. The tuner benchmarks synthetic traffic;
   this is the figure that counts.

`sequential.py` already has a `local` provider pointed at
`http://localhost:8000/v1`. Before a multi-model run, its model name needs to be
settable per run rather than fixed in the file.

## What to compare

Run `cue_pairs.py` on the local results and set it beside the frontier run: does
the education gap appear, is it on Sourcing, and does race stay at zero? A local
model reproducing the frontier pattern on the same question is the check that
makes the 76-question local results worth reading.
