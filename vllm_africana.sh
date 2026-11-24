#!/usr/bin/env bash
# Regrade the Pre-Enslavement Africana Heritage answers with their corrected
# answer elements (samples/fix_africana_references.py), in every rubric v3 run.
#
#     bash vllm_africana.sh             # regrade, swap the new grades in, re-analyse
#     bash vllm_africana.sh evaluate    # just re-analyse
#
# Kweli fixed the topic's mapping in the team sheet on 24 November. 18 of its
# 20 questions change: three had another question's elements, fifteen had none.
# The answers stay; only their grades are redone, on the same rubric and
# prompt as the rest, so the new grades sit beside the others unchanged.
#
#   runs/cues-rubric3     the full regrade, 18 questions x 525 answers = 9,450
#   runs/subset-rubric3   PEAH-010, 011 and 012: 4,635 answers, about a third
#                         of them shared with the full regrade and copied over
#   runs/shortlist        18 questions x 255 = 4,590, about two thirds copied
#
# About 17 hours at the 21 October rate. In each run the old grades of these
# questions are moved to <run>/africana-2026-11-24/, never deleted, and the
# new ones written where the old were. vllm_per_criterion.sh leaves these
# questions out once this has run.
#
# Stop any other vLLM job first (the per-criterion sweep resumes where it
# stopped). Run inside tmux and the llm conda env. Safe to rerun: the old grades
# are moved once, and saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
# per model and stage, from vllm_tune.py
[ -s vllm-engine.json ] && ARGS="$ARGS --engine-config vllm-engine.json"
TAG=africana-2026-11-24

# set aside one run's old grades of the changed questions, and list its answers
# to them: prepare <run dir> <old prompts> <new prompts>
prepare() {
    local D=$1 F=$1/$TAG
    mkdir -p "$F"
    python - "$D" "$F" "$2" "$3" <<'EOF'
import glob, json, os, sys
import openpyxl
d, f, old, new = sys.argv[1:]

def refs(path):
    rows = list(openpyxl.load_workbook(path, read_only=True).worksheets[0].iter_rows(values_only=True))
    pid, comp = rows[0].index("Prompt ID"), rows[0].index("Ideal Answer Components")
    return {r[pid]: (r[comp] or "").strip() for r in rows[1:] if r[pid]}

a, b = refs(old), refs(new)
changed = {q for q in b if b[q] != a.get(q, "")}
qid = lambda r: r.get("qid") or r["id"].split("|")[0]
read = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

answers = {}
for p in sorted(glob.glob(os.path.join(d, "*responses*.jsonl"))):
    for r in read(p):
        if qid(r) in changed and r.get("error") is None and (r.get("response") or "").strip():
            answers.setdefault(r["id"], r)
with open(os.path.join(f, "responses.jsonl"), "w", encoding="utf-8") as out:
    out.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in answers.values())
with open(os.path.join(f, "answer-ids.txt"), "w", encoding="utf-8") as out:
    out.writelines(i + "\n" for i in sorted(answers))
print(f"{d}: {len(changed)} questions changed, {len(answers)} answers to them")

marker = os.path.join(f, "MOVED")
if not os.path.exists(marker):
    for p in sorted(glob.glob(os.path.join(d, "*judgments*.jsonl"))):
        rows = read(p)
        keep = [r for r in rows if qid(r) not in changed]
        with open(os.path.join(f, "old-" + os.path.basename(p)), "a", encoding="utf-8") as out:
            out.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if qid(r) in changed)
        with open(p + ".tmp", "w", encoding="utf-8") as out:
            out.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
        os.replace(p + ".tmp", p)
        print(f"  moved {len(rows) - len(keep)} old grades out of {p}")
    open(marker, "w").close()
EOF
}

# copy new grades of shared answers from one run into another: copy <from> <to file> <answer ids>
copy() {
    python - "$1" "$2" "$3" <<'EOF'
import json, sys
src, dst, ids = sys.argv[1:]
want = {l.strip() for l in open(ids, encoding="utf-8") if l.strip()}
have = set()
try:
    have = {(r["id"], r["judge"]) for r in map(json.loads, filter(str.strip, open(dst, encoding="utf-8")))}
except FileNotFoundError:
    pass
n = 0
with open(dst, "a", encoding="utf-8") as out:
    for line in open(src, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r["id"] in want and (r["id"], r["judge"]) not in have and r.get("error") is None:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
print(f"copied {n} new grades from {src} -> {dst}")
EOF
}

grade() {   # grade <run dir> <new prompts> <judgments file>
    python vllm_offline.py judge "$1/$TAG/responses.jsonl" --prompts "$2" \
        --out "$3" $ARGS 2>&1 | tee -a "$1/$TAG/judge.log"
}

run() {
    if pgrep -f "vllm_offline.py (answer|judge)|vllm_per_criterion.py judge" > /dev/null; then
        echo "another vLLM job is running; stop it first (Ctrl-C in its tmux window)"; return 1
    fi
    python -c "import openpyxl, vllm" 2> /dev/null ||
        { echo "the llm env is not active: conda activate llm, then run this again"; return 1; }
    local FULL=samples/prompts-2026-11-24.xlsx SUB=samples/prompts-subset-2026-11-24.xlsx
    [ -s "$FULL" ] && [ -s "$SUB" ] || { echo "no $FULL or $SUB: git pull"; return 1; }

    echo "== the full regrade"
    prepare runs/cues-rubric3 samples/prompts-2026-10-20.xlsx "$FULL" &&
        grade runs/cues-rubric3 "$FULL" runs/cues-rubric3/judgments.jsonl

    echo "== the subset"
    prepare runs/subset-rubric3 samples/prompts-subset.xlsx "$SUB" &&
        copy runs/cues-rubric3/judgments.jsonl runs/subset-rubric3/judgments.jsonl \
            "runs/subset-rubric3/$TAG/answer-ids.txt" &&
        grade runs/subset-rubric3 "$SUB" runs/subset-rubric3/judgments.jsonl

    echo "== the shortlist"
    prepare runs/shortlist samples/prompts-2026-10-20.xlsx "$FULL" &&
        copy runs/cues-rubric3/judgments.jsonl runs/shortlist/judgments-shortlist.jsonl \
            "runs/shortlist/$TAG/answer-ids.txt" &&
        grade runs/shortlist "$FULL" runs/shortlist/judgments-shortlist.jsonl
}

evaluate() {
    bash vllm_cues_rubric3.sh evaluate
    bash vllm_shortlist.sh evaluate
    # the subset's own evaluate also redraws the hand-grading files; this does not
    local D=runs/subset-rubric3 P=samples/prompts-subset-2026-11-24.xlsx
    python analyze.py $D/judgments.jsonl --responses $D/responses.jsonl --prompts $P \
        --bootstrap 500 --out-dir $D/analysis/scores
    python cue_stats.py $D/responses.jsonl $D/judgments.jsonl --out-dir $D/analysis/cue-stats-strict > /dev/null
    python cue_stats.py $D/responses.jsonl $D/judgments.jsonl --out-dir $D/analysis/cue-stats-lenient --lenient > /dev/null
    echo "done: the three runs' analyses are redone"
}

case "${1:-all}" in
    all)
        run && evaluate ;;
    evaluate)
        evaluate ;;
    *)
        echo "usage: bash vllm_africana.sh [evaluate]"; exit 1 ;;
esac
