#!/usr/bin/env bash
# The 15 October identity-cue design, on the open-weight models and the full
# question set: answer, grade once, explain failures.
#
#     bash vllm_cues.sh
#
# Cues: the whole law-school cue sheet (cues.jsonl, from cues.py) -- the
# templated baseline, irrelevant-detail controls, race x gender as a label, a
# name or a matched HBCU profile, and education (did not finish high school vs
# doctorate) as a label or a profile, each in the user turn or in the system
# prompt as saved memory, three exemplars each, as on the frontier models.
# 105 answers per question per model: 85,050 answers and 425,250 grades.
#
# Reasoning is turned down (Dr. Aryal, 21 October): gpt-oss at low effort,
# Qwen's thinking off, for answering and grading alike. The other three do not
# reason. Scores therefore compare within this run, against its own baseline,
# not with the 20 October run, which used each model's default reasoning.
#
# Run inside tmux and the llm conda env. Writes to its own files, so it never
# mixes with the 20 October run, whose bare-question baseline shares the id
# "none" with this run's templated one. Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low"

echo "== answering"
python vllm_offline.py answer "$PROMPTS" --cues cues.jsonl \
    --out cues-responses.jsonl $ARGS 2>&1 | tee -a cues-answer.log

# one grading pass: on 20 October the retries recovered little
echo "== grading"
python vllm_offline.py judge cues-responses.jsonl --prompts "$PROMPTS" \
    --out cues-judgments.jsonl $ARGS 2>&1 | tee -a cues-judge.log

echo "== why grades failed"
python vllm_failures.py cues-judgments.jsonl | tee cues-failures.txt
echo "done: cues-responses.jsonl, cues-judgments.jsonl"
