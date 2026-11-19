#!/usr/bin/env bash
# The frontier cue shortlist (cues-shortlist.jsonl) checked on the open-weight
# models before any frontier money is spent: all 162 questions, the 51 prompts
# per question, the five models, graded on the law school's rubric of 3 November.
#
#     bash vllm_shortlist.sh             # reuse saved answers, answer the rest, grade, analyse
#     bash vllm_shortlist.sh evaluate    # just re-analyse what is graded
#     bash vllm_shortlist.sh publish     # push the analysis (never the raw rows), once gh is signed in
#
# 41,310 answers. 25,515 already exist and are copied in rather than asked
# again: the baseline, placebo and education answers from the 21 October run
# (all 162 questions), and the demographic screen's answers (81 questions, run
# 1). The first lot are already graded on the new rubric, and those grades are
# copied in too. That leaves 15,795 answers (about 2 hours) and 157,950 grades
# (about 39 hours at the 21 October rate of 4.4 s per answer for five grades).
# Settings are frozen from 21 October, as for every earlier cue run.
#
# The question it answers: does each contrast the shortlist was picked for
# still hold on all 162 questions and on the new rubric? cue_pooled.py gives the
# same pooled table as the demographic screen.
#
# Run inside tmux and the llm conda env. Safe to rerun: saved rows are skipped.
set -uo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
CUES=cues-shortlist.jsonl
D=runs/shortlist
MODELS=Qwen/Qwen3.8-27B,RedHatAI/Llama-4-Scout-17B-16E-Instruct-quantized.w4a16,allenai/Olmo-3.1-32B-Instruct,google/gemma-4-31B-it,openai/gpt-oss-120b
ARGS="--models $MODELS --tensor-parallel-size 2 --max-model-len 8192 --reasoning low \
    --gpu-memory-utilization 0.95 --max-num-seqs 512 --max-num-batched-tokens 32768 --chunk 10000"
# per model and stage, from vllm_tune.py
[ -s vllm-engine.json ] && ARGS="$ARGS --engine-config vllm-engine.json"
mkdir -p "$D/analysis"

prepare() {
    [ -s "$CUES" ] || python cues_shortlist.py
    # Saved answers to the shortlist's cues, and their new-rubric grades, once.
    # Answers come from wherever the earlier runs left them; grades only from
    # the rubric v3 regrade, since the screen's were on the September rubric.
    [ -s "$D/responses-shortlist.jsonl" ] && return 0
    python - "$CUES" "$D/responses-shortlist.jsonl" "$D/judgments-shortlist.jsonl" <<'EOF'
import glob, json, sys
cues, out_answers, out_grades = sys.argv[1:]
want = {json.loads(l)["identity"] for l in open(cues, encoding="utf-8") if l.strip()}

def rows(path):
    for line in open(path, encoding="utf-8"):
        if line.strip():
            yield json.loads(line)

answer_files = ["runs/cues-rubric3/responses.jsonl", "runs/cues-vllm-2026-10-21/cues-responses.jsonl",
                "cues-responses.jsonl", *sorted(glob.glob("runs/demographics/responses-*.jsonl"))]
answers = {}
for path in answer_files:
    try:
        for r in rows(path):
            ok = r.get("error") is None and (r.get("response") or "").strip()
            if ok and r["id"].split("|")[2] in want:
                answers.setdefault(r["id"], r)
        print(f"read {path}")
    except FileNotFoundError:
        pass
with open(out_answers, "w", encoding="utf-8") as f:
    for r in answers.values():
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"copied {len(answers)} saved answers -> {out_answers}")

n = 0
with open(out_grades, "w", encoding="utf-8") as f:
    for path in ["runs/cues-rubric3/judgments.jsonl"]:
        try:
            for g in rows(path):
                if g["id"] in answers:
                    f.write(json.dumps(g, ensure_ascii=False) + "\n")
                    n += 1
        except FileNotFoundError:
            print(f"no {path}: every answer will be graded")
print(f"copied {n} new-rubric grades (retries included) -> {out_grades}")
EOF
}

run() {
    echo "== answering what is not saved"
    python vllm_offline.py answer "$PROMPTS" --cues "$CUES" \
        --out "$D/responses-shortlist.jsonl" $ARGS 2>&1 | tee -a "$D/answer.log"
    echo "== grading, one pass, as on 21 October"
    python vllm_offline.py judge "$D/responses-shortlist.jsonl" --prompts "$PROMPTS" \
        --out "$D/judgments-shortlist.jsonl" $ARGS 2>&1 | tee -a "$D/judge.log"
}

evaluate() {
    local A="$D/analysis"
    echo "== analysing"
    # retried rows must be merged first, or analyze.py stops on duplicates
    python merge.py responses --in-dir "$D" --out "$D/all-responses.jsonl"
    python merge.py judgments --in-dir "$D" --out "$D/all-judgments.jsonl"
    local R="$D/all-responses.jsonl" J="$D/all-judgments.jsonl"
    python cue_pooled.py $R $J --out-dir "$A/pooled-strict" > /dev/null
    python cue_pooled.py $R $J --out-dir "$A/pooled-lenient" --lenient > /dev/null
    python cue_screen.py $R $J --out-dir "$A/screen-strict" > /dev/null
    python cue_screen.py $R $J --out-dir "$A/screen-lenient" --lenient > /dev/null
    python analyze.py $J --responses $R --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores-strict"
    python analyze.py $J --responses $R --prompts "$PROMPTS" --bootstrap 500 --out-dir "$A/scores-lenient" \
        --ignore-stray-premise
    python vllm_failures.py $J > "$A/failures.txt"
    date > "$A/AS_OF.txt"
    echo "done: $A (pooled-lenient/report.md first)"
}

publish() {
    gh auth status > /dev/null 2>&1 || { echo "sign in first: gh auth login"; return 1; }
    local W=../llm-project-results-shortlist
    [ -d "$W" ] || git worktree add -B results/shortlist "$W" HEAD
    rm -rf "$W/shortlist" && cp -r "$D/analysis" "$W/shortlist"
    git -C "$W" add -f shortlist
    git -C "$W" commit -qm "Shortlist check on 162 questions, rubric v3" &&
        git -C "$W" push -q -u origin results/shortlist
    echo "pushed results/shortlist; sign out with: gh auth logout"
}

case "${1:-all}" in
    all)
        prepare && run && evaluate ;;
    evaluate)
        evaluate ;;
    publish)
        publish ;;
    *)
        echo "usage: bash vllm_shortlist.sh [evaluate|publish]"; exit 1 ;;
esac
