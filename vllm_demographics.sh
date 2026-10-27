#!/usr/bin/env bash
# The demographic cue screen (cue_templates_demographics.xlsx, 27 October) on the
# open-weight models, in waves, each analysed as soon as it is graded.
#
#     bash vllm_demographics.sh               # probes, then every wave in order
#     bash vllm_demographics.sh 3-disability  # one wave
#     bash vllm_demographics.sh evaluate      # just re-analyse what is finished
#
# 312 prompts per question per model on a balanced half of the questions (81,
# samples/prompts-half.xlsx): 126,360 answers and 631,800 grades. At the 21
# October run's rates (0.46 s to answer, 4.4 s to grade five times, per answer;
# Qwen is half the grading) that is about 7 days. Settings are frozen from that
# run (vllm_cues.sh), as the sheet's Legend asks.
#
# A wave answers its cues, grades them with all five judges, then reruns the
# screen (cue_screen.py), the probe tally and the score tables by topic and
# question type (analyze.py) on everything finished so far, into
# runs/demographics/analysis, in the background while the next wave starts.
# User-turn cues come first, as the Legend asks. Saved-memory waves come last,
# so a dimension that shows nothing in the user turn can be cut from them by
# editing WAVES before they start.
#
# If gh is signed in, each wave's analysis (never the raw rows) is pushed to the
# results/demographics branch, so the laptop can read it as it lands. If not,
# it stays on this machine.
#
# Run inside tmux and the llm conda env. Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-half.xlsx
CUES=cues-demographics.jsonl
D=runs/demographics
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"

# name:scenario ids, from the Scenarios sheet. Hours at 21 October rates.
WAVES=(
    "1-politics:D-S00|D-S01|D-M01|D-S07"                     # anchors and politics, ~14 h
    "2-identity:D-S02|D-S03|D-S04|D-S05|D-S06|D-S08"           # race, color, gender, orientation, religion, citizenship, ~30 h
    "3-disability:D-S09|D-S10|D-S11"                           # disability, income, occupation, ~28 h
    "4-place:D-S12|D-S13|D-S14|D-S15|D-S16"                    # geography, family, veteran, record, writing, ~20 h
    "5-memory:D-M02|D-M03|D-M04|D-M05|D-M06|D-M07|D-M08"       # saved memory, first half, ~38 h
    "6-memory:D-M09|D-M10|D-M11|D-M12|D-M13|D-M14|D-M15"       # saved memory, second half, ~43 h
)
mkdir -p "$D/analysis"

probes() {
    echo "== probes: what the models read into each cue, ungraded"
    python vllm_offline.py answer samples/prompts-probe.xlsx --cues probes-$CUES \
        --out "$D/probes-responses.jsonl" $ARGS 2>&1 | tee -a "$D/answer.log"
}

wave() {
    local name=${1%%:*} ids=${1#*:}
    local cues="$D/cues-$name.jsonl"
    grep -E "\"scenario\": \"($ids)\"" "$CUES" > "$cues"
    echo "== wave $name: $(wc -l < "$cues") cues"
    python vllm_offline.py answer "$PROMPTS" --cues "$cues" \
        --out "$D/responses-$name.jsonl" $ARGS 2>&1 | tee -a "$D/answer.log"
    # one grading pass, as on 21 October
    python vllm_offline.py judge "$D/responses-$name.jsonl" --prompts "$PROMPTS" \
        --out "$D/judgments-$name.jsonl" $ARGS 2>&1 | tee -a "$D/judge.log"
}

evaluate() {
    echo "== evaluating everything finished so far ($1)"
    # merge before the next wave starts writing, analyse in the background
    python merge.py responses --in-dir "$D" --out "$D/all-responses.jsonl"
    python merge.py judgments --in-dir "$D" --out "$D/all-judgments.jsonl"
    (
        A="$D/analysis"
        python cue_screen.py "$D/all-responses.jsonl" "$D/all-judgments.jsonl" \
            --out-dir "$A/screen-strict" > /dev/null
        python cue_screen.py "$D/all-responses.jsonl" "$D/all-judgments.jsonl" \
            --out-dir "$A/screen-lenient" --lenient > /dev/null
        [ -s "$D/probes-responses.jsonl" ] && python cue_probes.py "$D/probes-responses.jsonl" \
            --out-dir "$A/probes"
        python analyze.py "$D/all-judgments.jsonl" --responses "$D/all-responses.jsonl" \
            --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores"
        python vllm_failures.py "$D/all-judgments.jsonl" > "$A/failures.txt"
        echo "after wave $1, $(date)" > "$A/AS_OF.txt"
        publish "$1"
    ) >> "$D/evaluate.log" 2>&1 &
}

publish() {
    if ! gh auth status > /dev/null 2>&1; then
        echo "gh not signed in: analysis stays in $D/analysis"
        return
    fi
    local W=../llm-project-results
    [ -d "$W" ] || git worktree add -B results/demographics "$W" HEAD
    rm -rf "$W/demographics" && cp -r "$D/analysis" "$W/demographics"
    git -C "$W" add -f demographics
    git -C "$W" commit -qm "Demographic cue screen, after wave $1" &&
        git -C "$W" push -q -u origin results/demographics
}

case "${1:-all}" in
    all)
        [ -s "$D/probes-responses.jsonl" ] || probes
        for w in "${WAVES[@]}"; do
            wave "$w"
            evaluate "${w%%:*}"
        done
        wait
        echo "done: $D/analysis/screen-strict/report.md" ;;
    evaluate)
        evaluate manual
        wait ;;
    probes)
        probes ;;
    *)
        w=$(printf '%s\n' "${WAVES[@]}" | grep "^$1:") || { echo "no wave $1"; exit 1; }
        wave "$w"
        evaluate "$1"
        wait ;;
esac
