#!/usr/bin/env bash
# One prompt per rubric criterion against one prompt for the whole rubric, as
# Dr. Aryal asked on 19 November: on the full 162-question sweep of the rubric
# v3 regrade (vllm_cues_rubric3.sh), the baseline, the placebo and the race x
# gender cues, only where the one-prompt grade is valid.
#
#     bash vllm_per_criterion.sh             # select, grade in three waves, compare after each
#     bash vllm_per_criterion.sh evaluate    # just re-compare what is graded
#     bash vllm_per_criterion.sh publish     # push the comparison (never the raw rows), once gh is signed in
#
# The answers: the 162 questions x 5 answering models, under the baseline (its
# three runs), the placebo in both channels and Black/White x man/woman (label,
# name and profile, user turn and saved memory, run 1 of each wording): 81 of the
# 105 prompts per question, 65,610 answers. No answer is asked again.
#
# The one-prompt side is the regrade's own grades (runs/cues-rubric3), so only
# the per-criterion side is graded here, and only for the answer and judge
# pairs whose regrade is valid under the lenient rule (96.6% of them). That is
# 7 calls per answer and judge, or 8 on loaded questions: about 2.3 million.
# Per criterion has never been timed here; a call is shorter than a full grade,
# so somewhere between one and two weeks (throughput-per-criterion.jsonl).
#
# Three waves, each compared as soon as it is graded: the baseline and placebo
# (about a day), then race x gender in the user turn, then in saved memory.
#
# The 32 subset questions' regrades were made with the numeric v3 prompt (before
# 0877eb5), the rest with level names, as here. The comparison is reported on
# all 162 questions (analysis/report.md) and on the 130 graded with level names
# both ways (analysis/level-names/report.md).
#
# Run inside tmux and the llm conda env, after any other GPU job has finished.
# Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
SRC=runs/cues-rubric3
D=runs/per-criterion-sweep
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
# per model and stage, from vllm_tune.py
[ -s vllm-engine.json ] && ARGS="$ARGS --engine-config vllm-engine.json"
WAVES="1-baseline-placebo 2-race-gender-user 3-race-gender-memory"
# the Africana Heritage answers, regraded with corrected elements by vllm_africana.sh
# after part of this ran: left out of grading and comparison once that has run
AFRICANA=$SRC/africana-2026-11-24/answer-ids.txt
mkdir -p "$D/analysis"

prepare() {
    [ -s "$D/responses-3-race-gender-memory.jsonl" ] && return 0
    [ -s "$SRC/responses.jsonl" ] && [ -s "$SRC/judgments.jsonl" ] ||
        { echo "no $SRC/responses.jsonl or judgments.jsonl: run vllm_cues_rubric3.sh first"; return 1; }
    python - "$SRC/responses.jsonl" runs/subset-rubric3/responses.jsonl "$D" <<'EOF'
import json, os, re, sys
src, subset, d = sys.argv[1:]
def wave(i):
    if i == "none" or re.match(r"S0[12]-CTRL-", i):
        return "1-baseline-placebo"
    if re.match(r"S0[357]-RG-", i):
        return "2-race-gender-user"
    if re.match(r"S0[468]-RG-", i):
        return "3-race-gender-memory"
rows = {}
for line in open(src, encoding="utf-8"):
    r = json.loads(line) if line.strip() else {}
    if r and r.get("error") is None and (r.get("response") or "").strip() and wave(r["identity"]):
        rows.setdefault(r["id"], r)
for w in ("1-baseline-placebo", "2-race-gender-user", "3-race-gender-memory"):
    out = os.path.join(d, f"responses-{w}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        n = 0
        for r in rows.values():
            if wave(r["identity"]) == w:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
    print(f"{n} answers -> {out}")
# the answers whose regrade came from the subset run, with the numeric prompt
numeric = set()
if os.path.exists(subset):
    numeric = {json.loads(l)["id"] for l in open(subset, encoding="utf-8") if l.strip()} & set(rows)
with open(os.path.join(d, "numeric-prompt-ids.txt"), "w", encoding="utf-8") as f:
    f.writelines(i + "\n" for i in sorted(numeric))
print(f"{len(numeric)} of them regraded with the numeric prompt")
EOF
}

run() {
    if pgrep -f "vllm_offline.py (answer|judge)|vllm_per_criterion.py judge" > /dev/null; then
        echo "another vLLM job is running; start this once it has finished"; return 1
    fi
    local w in
    for w in $WAVES; do
        echo "== wave $w, one prompt per criterion"
        in="$D/responses-$w.jsonl"
        if [ -s "$AFRICANA" ]; then
            grep -vFf <(sed 's/.*/"id": "&"/' "$AFRICANA") "$in" > "$D/to-grade-$w.jsonl"
            in="$D/to-grade-$w.jsonl"
        fi
        python vllm_per_criterion.py judge "$in" --prompts "$PROMPTS" \
            --only-valid "$SRC/judgments.jsonl" --out "$D/parts.jsonl" \
            --throughput throughput-per-criterion.jsonl $ARGS 2>&1 | tee -a "$D/judge.log"
        evaluate
    done
}

evaluate() {
    echo "== comparing"
    cat "$AFRICANA" 2>/dev/null > "$D/exclude.txt"
    cat "$D/exclude.txt" "$D/numeric-prompt-ids.txt" > "$D/exclude-numeric.txt"
    python vllm_per_criterion.py assemble "$D/parts.jsonl" --out "$D/judgments-per-criterion.jsonl"
    python vllm_per_criterion.py compare "$SRC/judgments.jsonl" \
        "$D/judgments-per-criterion.jsonl" --exclude "$D/exclude.txt" \
        --out-dir "$D/analysis" > /dev/null
    python vllm_per_criterion.py compare "$SRC/judgments.jsonl" \
        "$D/judgments-per-criterion.jsonl" --exclude "$D/exclude-numeric.txt" \
        --out-dir "$D/analysis/level-names" > /dev/null
    cp throughput-per-criterion.jsonl "$D/analysis/throughput.jsonl" 2>/dev/null
    date > "$D/analysis/AS_OF.txt"
    echo "done: $D/analysis/report.md"
}

publish() {
    gh auth status > /dev/null 2>&1 || { echo "sign in first: gh auth login"; return 1; }
    local W=../llm-project-results-per-criterion
    [ -d "$W" ] || git worktree add -B results/per-criterion "$W" HEAD
    rm -rf "$W/per-criterion" && cp -r "$D/analysis" "$W/per-criterion"
    git -C "$W" add -f per-criterion
    git -C "$W" commit -qm "One prompt per criterion against one prompt, 162-question sweep, as of $(cat "$D/analysis/AS_OF.txt")" &&
        git -C "$W" push -q -u origin results/per-criterion
    echo "pushed results/per-criterion; sign out with: gh auth logout"
}

case "${1:-all}" in
    all)
        prepare && run ;;
    evaluate)
        evaluate ;;
    publish)
        publish ;;
    *)
        echo "usage: bash vllm_per_criterion.sh [evaluate|publish]"; exit 1 ;;
esac
