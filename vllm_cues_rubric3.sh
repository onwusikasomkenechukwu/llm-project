#!/usr/bin/env bash
# The 21 October cue run again, graded on the law school's rubric of 3 November:
# the same 162 questions, the same 105 cue prompts per question (cues.jsonl), the
# same five models, the same answers. Only the rubric changes, so any difference
# from the October results is the rubric's, not new answers'.
#
#     bash vllm_cues_rubric3.sh             # copy the answers, grade, analyse
#     bash vllm_cues_rubric3.sh evaluate    # just re-analyse what is graded
#
# 85,050 answers, 425,250 grades. Answers the subset run (vllm_subset.sh)
# already graded on the new rubric are copied in rather than graded again: run
# 1 of the 32 subset questions, 16,800 answers. The other 68,250 take about 83
# hours at the 21 October rate of 4.4 s per answer for five grades.
#
# Run inside tmux and the llm conda env, after vllm_subset.sh. Safe to rerun:
# saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
D=runs/cues-rubric3
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
mkdir -p "$D/analysis"

prepare() {
    # the October answers, wherever the 21 October run left them
    if [ ! -s "$D/responses.jsonl" ]; then
        local src
        for src in cues-responses.jsonl runs/cues-vllm-2026-10-21/cues-responses.jsonl; do
            [ -s "$src" ] && { cp "$src" "$D/responses.jsonl"; break; }
        done
        [ -s "$D/responses.jsonl" ] || { echo "no October answers (cues-responses.jsonl) found"; return 1; }
        echo "copied $(wc -l < "$D/responses.jsonl") October answers from $src"
    fi
    # the subset run's new-rubric grades for the same answers, once
    if [ ! -s "$D/judgments.jsonl" ] && [ -s runs/subset-rubric3/judgments.jsonl ]; then
        python - "$D/responses.jsonl" runs/subset-rubric3/judgments.jsonl "$D/judgments.jsonl" <<'EOF'
import json, sys
answers, source, out = sys.argv[1:]
ids = {json.loads(l)["id"] for l in open(answers, encoding="utf-8") if l.strip()}
n = 0
with open(out, "w", encoding="utf-8") as f:
    for line in open(source, encoding="utf-8"):
        if line.strip() and json.loads(line)["id"] in ids:
            f.write(line if line.endswith("\n") else line + "\n")
            n += 1
print(f"copied {n} subset grades -> {out}")
EOF
    fi
}

run() {
    echo "== grading on the 3 November rubric"
    python vllm_offline.py judge "$D/responses.jsonl" --prompts "$PROMPTS" \
        --out "$D/judgments.jsonl" $ARGS 2>&1 | tee -a "$D/judge.log"
}

evaluate() {
    local R="$D/responses.jsonl" J="$D/judgments.jsonl" A="$D/analysis"
    echo "== analysing"
    python analyze.py $J --responses $R --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores-strict"
    python analyze.py $J --responses $R --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores-lenient" \
        --ignore-stray-premise
    python cue_stats.py $R $J --out-dir "$A/cue-stats-strict" > /dev/null
    python cue_stats.py $R $J --out-dir "$A/cue-stats-lenient" --lenient > /dev/null
    python vllm_failures.py $J > "$A/failures.txt"
}

case "${1:-all}" in
    all)
        prepare && run && evaluate
        echo "done: $D/analysis" ;;
    evaluate)
        evaluate ;;
    *)
        echo "usage: bash vllm_cues_rubric3.sh [evaluate]"; exit 1 ;;
esac
