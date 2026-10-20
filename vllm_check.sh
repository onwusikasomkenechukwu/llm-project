#!/usr/bin/env bash
# Before grading: check the answers, then grade 30 of them with one judge.
#
#     bash vllm_check.sh
#
# Run inside the llm conda env, after the answer stage has finished.
set -euo pipefail
cd "$(dirname "$0")"

PROMPTS=samples/prompts-2026-10-20.xlsx
JUDGE=google/gemma-4-31B-it

echo "== answers per model (want 486 each, 0 errors)"
python - <<'EOF'
import json, collections
rows = [json.loads(l) for l in open("responses-vllm_offline.jsonl")]
n, err, cut = collections.Counter(), collections.Counter(), collections.Counter()
for r in rows:
    p = r["provider"]
    n[p] += 1
    err[p] += bool(r.get("error"))
    cut[p] += (r.get("output_tokens") or 0) >= 4000
for p in n:
    print(f"  {p:55} {n[p]:4}  errors {err[p]:3}  cut off {cut[p]:3}")
EOF

echo "== test grading: $JUDGE on 30 answers"
rm -f test-judge.jsonl
python vllm_offline.py judge responses-vllm_offline.jsonl --prompts "$PROMPTS" \
    --models "$JUDGE" --limit 30 --tensor-parallel-size 2 --max-model-len 8192 \
    --out test-judge.jsonl > test-judge.log 2>&1 || true

python - <<'EOF'
import json
rows = [json.loads(l) for l in open("test-judge.jsonl")]
bad = [r for r in rows if r.get("error")]
print(f"  {len(rows)} grades, {len(bad)} failed")
for r in bad[:5]:
    print("   ", (r.get("raw") or r.get("response") or r["error"])[:200].replace("\n", " "))
print("  OK to run vllm_judge.sh" if rows and len(bad) <= 3 else
      "  STOP: send a photo of this before grading (full log in test-judge.log)")
EOF
