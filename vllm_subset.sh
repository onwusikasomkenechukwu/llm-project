#!/usr/bin/env bash
# The first run on the law school's rubric of 3 November, on the 32 questions
# the law school also grades by hand (samples/prompts-subset.xlsx: one per topic
# x question type), so the AI and human grades line up.
#
#     bash vllm_subset.sh             # copy saved answers, answer, grade, analyse
#     bash vllm_subset.sh evaluate    # just re-analyse what is graded
#
# Cues: the October sheet as the 21 October run had it (cues.jsonl: race x
# gender, education and the controls), but three runs of every cue rather than
# of the baseline only: 32 x 103 x 3 x 5 = 49,440 answers and 247,200 grades.
# The October run's answers for these questions (16,800, run 1 of every cue
# and all three baseline runs) are copied in first, so 32,640 are answered.
# At the 21 October rates (0.46 s to answer, 4.4 s to grade five times, per
# answer) that is about 4 hours answering and 60 grading, near 3 days.
#
# Every answer is graded afresh on the new rubric. The hand-grading sample
# (label_sample.py) is drawn at the end: each question once per model, under
# a different cue group each time, in eight batches of 20. Its sheet and key
# stay on this machine.
#
# Run inside tmux and the llm conda env. Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-subset.xlsx
RUNS=3
D=runs/subset-rubric3
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
# per model and stage, from vllm_tune.py
[ -s vllm-engine.json ] && ARGS="$ARGS --engine-config vllm-engine.json"
# where earlier runs left their answers; missing files are skipped
SAVED="cues-responses.jsonl runs/cues-vllm-2026-10-21/cues-responses.jsonl"
mkdir -p "$D/analysis"

prepare() {
    [ -s "$PROMPTS" ] || python samples/subset_prompts.py samples/prompts-2026-10-20.xlsx
    # the cues, every one at three runs
    python - "$D/cues.jsonl" "$RUNS" <<'EOF'
import json, sys
out, runs = sys.argv[1], int(sys.argv[2])
cues = [json.loads(l) for l in open("cues.jsonl", encoding="utf-8") if l.strip()]
with open(out, "w", encoding="utf-8") as f:
    for c in cues:
        f.write(json.dumps(dict(c, runs=runs)) + "\n")
print(f"{len(cues)} cues, {runs} runs each -> {out}")
EOF
    # saved answers for these questions and cues, once, before anything new is answered
    [ -s "$D/responses.jsonl" ] || python - "$D/responses.jsonl" "$D/cues.jsonl" "$PROMPTS" $SAVED <<'EOF'
import glob, json, sys
import openpyxl
out, cue_path, prompts, *saved = sys.argv[1:]
ws = openpyxl.load_workbook(prompts, read_only=True).worksheets[0]
qids = {str(r[0]) for r in list(ws.iter_rows(values_only=True))[1:] if r[0]}
runs = {c["identity"]: c["runs"] for c in map(json.loads, open(cue_path, encoding="utf-8"))}
rows = {}
for path in sorted({p for s in saved for p in glob.glob(s)}):
    for line in open(path, encoding="utf-8"):
        r = json.loads(line) if line.strip() else {}
        if (r.get("qid") in qids and r.get("polarity") == "pos" and r.get("run", 0) < runs.get(r.get("identity"), 0)
                and r.get("error") is None and (r.get("response") or "").strip()):
            rows[r["id"]] = r
with open(out, "w", encoding="utf-8") as f:
    for r in rows.values():
        f.write(json.dumps(r) + "\n")
print(f"copied {len(rows)} saved answers -> {out}")
EOF
}

run() {
    echo "== answering what is not saved"
    python vllm_offline.py answer "$PROMPTS" --cues "$D/cues.jsonl" \
        --out "$D/responses.jsonl" $ARGS 2>&1 | tee -a "$D/answer.log"
    echo "== grading on the 3 November rubric"
    python vllm_offline.py judge "$D/responses.jsonl" --prompts "$PROMPTS" \
        --out "$D/judgments.jsonl" $ARGS 2>&1 | tee -a "$D/judge.log"
}

evaluate() {
    local R="$D/responses.jsonl" J="$D/judgments.jsonl" A="$D/analysis"
    echo "== analysing"
    python analyze.py $J --responses $R --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores"
    python cue_stats.py $R $J --out-dir "$A/cue-stats-strict" > /dev/null
    python cue_stats.py $R $J --out-dir "$A/cue-stats-lenient" --lenient > /dev/null
    python vllm_failures.py $J > "$A/failures.txt"
    echo "== the hand-grading sample"
    python label_sample.py $R $J --prompts "$PROMPTS" --out-dir "$D/labelling"
}

case "${1:-all}" in
    all)
        prepare && run && evaluate
        echo "done: $D/analysis, hand sample in $D/labelling" ;;
    evaluate)
        evaluate ;;
    *)
        echo "usage: bash vllm_subset.sh [evaluate]"; exit 1 ;;
esac
