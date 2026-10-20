#!/usr/bin/env bash
# The full grading run, then the analysis.
#
#     bash vllm_judge.sh
#
# Run inside tmux and the llm conda env, after vllm_check.sh says OK. Safe to
# rerun: grades already saved are skipped, failed ones are retried.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b

# up to three passes: the second and third only retry grades that failed
for pass in 1 2 3; do
    echo "== grading, pass $pass"
    python vllm_offline.py judge responses-vllm_offline.jsonl --prompts "$PROMPTS" \
        --models "$MODELS" --tensor-parallel-size 2 --max-model-len 8192 \
        2>&1 | tee -a judge.log
    [ "${PIPESTATUS[0]}" -eq 0 ] && break
done

echo "== analysis"
python analyze.py judgments-vllm_offline.jsonl --responses responses-vllm_offline.jsonl \
    --out-dir analysis/vllm
echo "done: tables in analysis/vllm"
