#!/usr/bin/env bash
# One prompt per rubric criterion against one prompt for the whole rubric, on a
# subset of the 32-question run, as Dr. Aryal asked on 19 November.
#
#     bash vllm_per_criterion.sh             # select, grade both ways, compare
#     bash vllm_per_criterion.sh evaluate    # just re-compare what is graded
#     bash vllm_per_criterion.sh publish     # push the comparison (never the raw rows), once gh is signed in
#
# The answers: the 32 questions x 5 answering models, under the baseline (its
# three runs), the placebo and the education cues (run 1 of each of their
# three wordings): 12 per question and model, 1,920 answers. The hand-grading
# sample's answers are added when its key is on this machine, so the human
# grades can be set against both modes later. No answer is asked again.
#
# Both modes grade the same answers with the same five judges, with level
# names. The one-prompt grades are made afresh, because the subset's own grades
# asked for numbers (it ran before 0877eb5). One prompt is 1 call per answer
# and judge; per criterion is 7, or 8 on loaded questions, about 75,000 calls.
# One prompt takes about 2.5 hours at the 21 October rate; per criterion has
# never been timed here, so expect several times that (throughput-per-criterion.jsonl).
#
# The comparison (analysis/report.md): scores per criterion, how much the six
# criteria move together within a grade, judge agreement, and the education
# and placebo gaps, each both ways.
#
# Run inside tmux and the llm conda env, after any other GPU job has finished.
# Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-subset.xlsx
SRC=runs/subset-rubric3
D=runs/per-criterion
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
# per model and stage, from vllm_tune.py
[ -s vllm-engine.json ] && ARGS="$ARGS --engine-config vllm-engine.json"
mkdir -p "$D/analysis"

prepare() {
    [ -s "$D/responses.jsonl" ] && return 0
    [ -s "$SRC/responses.jsonl" ] || { echo "no $SRC/responses.jsonl: run vllm_subset.sh first"; return 1; }
    python - "$SRC/responses.jsonl" "$SRC/labelling/key.csv" "$D/responses.jsonl" <<'EOF'
import csv, json, os, sys
src, key, out = sys.argv[1:]
labelled = set()
if os.path.exists(key):
    labelled = {r["answer_id"] for r in csv.DictReader(open(key, encoding="utf-8"))}
def wanted(r):
    i = r["identity"]
    return (r["id"] in labelled or i == "none"
            or (r.get("run") == 0 and i.startswith(("S01-CTRL-", "S09-EDU-"))))
rows = {}
for line in open(src, encoding="utf-8"):
    r = json.loads(line) if line.strip() else {}
    if r and r.get("error") is None and (r.get("response") or "").strip() and wanted(r):
        rows.setdefault(r["id"], r)
with open(out, "w", encoding="utf-8") as f:
    for r in rows.values():
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"{len(rows)} answers ({len(labelled & set(rows))} of them hand-graded) -> {out}")
EOF
}

run() {
    if pgrep -f "vllm_offline.py (answer|judge)" > /dev/null; then
        echo "another vLLM job is running; start this once it has finished"; return 1
    fi
    echo "== one prompt for the whole rubric"
    python vllm_offline.py judge "$D/responses.jsonl" --prompts "$PROMPTS" \
        --out "$D/judgments-single.jsonl" $ARGS 2>&1 | tee -a "$D/judge-single.log"
    echo "== one prompt per criterion"
    python vllm_per_criterion.py judge "$D/responses.jsonl" --prompts "$PROMPTS" \
        --out "$D/parts.jsonl" --throughput throughput-per-criterion.jsonl $ARGS 2>&1 \
        | tee -a "$D/judge-per-criterion.log"
}

evaluate() {
    echo "== comparing"
    python vllm_per_criterion.py assemble "$D/parts.jsonl" --out "$D/judgments-per-criterion.jsonl"
    python vllm_per_criterion.py compare "$D/judgments-single.jsonl" \
        "$D/judgments-per-criterion.jsonl" --out-dir "$D/analysis" > /dev/null
    cp throughput-per-criterion.jsonl "$D/analysis/throughput.jsonl" 2>/dev/null
    grep -h '"stage": "judge"' throughput-vllm_offline.jsonl 2>/dev/null | tail -5 \
        > "$D/analysis/throughput-single.jsonl"
    date > "$D/analysis/AS_OF.txt"
    echo "done: $D/analysis/report.md"
}

publish() {
    gh auth status > /dev/null 2>&1 || { echo "sign in first: gh auth login"; return 1; }
    local W=../llm-project-results-per-criterion
    [ -d "$W" ] || git worktree add -B results/per-criterion "$W" HEAD
    rm -rf "$W/per-criterion" && cp -r "$D/analysis" "$W/per-criterion"
    git -C "$W" add -f per-criterion
    git -C "$W" commit -qm "One prompt per criterion against one prompt, 32-question subset" &&
        git -C "$W" push -q -u origin results/per-criterion
    echo "pushed results/per-criterion; sign out with: gh auth logout"
}

case "${1:-all}" in
    all)
        prepare && run && evaluate ;;
    evaluate)
        evaluate ;;
    publish)
        publish ;;
    *)
        echo "usage: bash vllm_per_criterion.sh [evaluate|publish]"; exit 1 ;;
esac
