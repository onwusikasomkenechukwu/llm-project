#!/usr/bin/env bash
# The 15 October identity-cue design, on the open-weight models and the full
# question set: answer, grade once, explain failures.
#
#     bash vllm_cues.sh
#
# Cues: the templated baseline plus the race x gender block -- Black/White x
# woman/man, as an explicit label or an implicit name, in the user turn or in
# the system prompt as saved memory, three exemplars each, as on the frontier
# models. 17 conditions x 162 questions x 3 = 41,310 answers and 206,550
# grades: about four days on 2x A6000.
#
# Run inside tmux and the llm conda env. Writes to its own files, so it never
# mixes with the 20 October run, whose bare-question baseline shares the id
# "none" with this run's templated one. Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192"

python - <<'EOF'
import json
keep = {"S00", "S03", "S04", "S05", "S06"}   # baseline; label/name x user/memory
with open("cues.jsonl", encoding="utf-8") as src, \
        open("cues-race-gender.jsonl", "w", encoding="utf-8") as out:
    n = 0
    for line in src:
        if json.loads(line)["row"]["scenario"] in keep:
            out.write(line)
            n += 1
print(f"{n} cues -> cues-race-gender.jsonl")
EOF

echo "== answering"
python vllm_offline.py answer "$PROMPTS" --cues cues-race-gender.jsonl \
    --out cues-responses.jsonl $ARGS 2>&1 | tee -a cues-answer.log

# one grading pass: on 20 October the retries recovered little
echo "== grading"
python vllm_offline.py judge cues-responses.jsonl --prompts "$PROMPTS" \
    --out cues-judgments.jsonl $ARGS 2>&1 | tee -a cues-judge.log

echo "== why grades failed"
python vllm_failures.py cues-judgments.jsonl | tee cues-failures.txt
echo "done: cues-responses.jsonl, cues-judgments.jsonl"
