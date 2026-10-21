#!/usr/bin/env bash
# On the laptop: copy the open-weight run's results back from the GPU machine.
#
#     bash vllm_fetch.sh                 # from abl-workstation2
#     bash vllm_fetch.sh user@host       # from somewhere else
#
# Run vllm_finish.sh on the GPU machine first. Lands in runs/vllm-2026-10-20/.
set -euo pipefail
cd "$(dirname "$0")"

HOST=${1:-abl-workstation2@abl-workstation2}
OUT=runs/vllm-2026-10-20
mkdir -p "$OUT"

ssh "$HOST" 'cd ~/llm-project && tar czf - analysis/vllm vllm-responses.jsonl \
    vllm-judgments.jsonl throughput-vllm_offline.jsonl judge.log' | tar xzf - -C "$OUT"
ls -R "$OUT"
