#!/usr/bin/env bash
# On the GPU machine, after grading: merge retries, analyze, record the failures.
#
#     bash vllm_finish.sh
#
# Failed grades stay excluded, as graded; failures.txt records which and why,
# so the results can be reported with them.
set -euo pipefail
cd "$(dirname "$0")"

python merge.py responses --out vllm-responses.jsonl
python merge.py judgments --out vllm-judgments.jsonl
python analyze.py vllm-judgments.jsonl --responses vllm-responses.jsonl --out-dir analysis/vllm
python vllm_failures.py judgments-vllm_offline.jsonl > analysis/vllm/failures.txt
echo "done: analysis/vllm (failures in analysis/vllm/failures.txt)"
