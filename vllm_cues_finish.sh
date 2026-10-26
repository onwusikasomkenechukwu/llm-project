#!/usr/bin/env bash
# On the GPU machine, after vllm_cues.sh: analyse the cue run, then pack it onto
# a results branch for the laptop.
#
#     bash vllm_cues_finish.sh
#
# analyze.py and cue_model.py each run under the strict premise rule and the
# lenient one. The raw rows are gzipped and split under GitHub's 100 MB file
# limit; on the laptop, `cat cues-judgments.jsonl.gz.part-* | gunzip` rebuilds
# them. Nothing is pushed: the last lines print the commands for that.
set -euo pipefail
cd "$(dirname "$0")"

R=cues-responses.jsonl
J=cues-judgments.jsonl
python -c "import statsmodels" 2>/dev/null || pip install -q statsmodels pandas

echo "== analyze.py, strict and lenient"
python analyze.py $J --responses $R --out-dir analysis/cues-strict
python analyze.py $J --responses $R --out-dir analysis/cues-lenient --ignore-stray-premise

echo "== cue_stats.py: agreement, correlations, length, test-retest, per-question gaps"
python cue_stats.py $R $J --out-dir analysis/cue-stats-strict > /dev/null
python cue_stats.py $R $J --out-dir analysis/cue-stats-lenient --lenient > /dev/null
python cue_report.py $R $J > analysis/cue-report.txt
echo "   analysis/cue-stats-strict/report.md, analysis/cue-stats-lenient/report.md"

echo "== cue_model.py (about an hour)"
mkdir -p analysis/cue-model
python cue_model.py $R $J --outcomes total,sourcing --out-dir analysis/cue-model \
    | tee analysis/cue-model/report.md

echo "== packing the raw rows"
mkdir -p results-cues
for f in $R $J; do
    gzip -c "$f" | split -b 90M - "results-cues/$f.gz.part-"
done
ls -la results-cues

cat <<'EOF'

Done. To push, from ~/llm-project:

  git checkout -b results/cues-2026-10-21
  git add -f analysis/cues-strict analysis/cues-lenient analysis/cue-model results-cues \
      analysis/cue-stats-strict analysis/cue-stats-lenient analysis/cue-report.txt \
      cues-failures.txt cues-answer.log cues-judge.log throughput-vllm_offline.jsonl
  git commit -m "Open-weight cue run results, 21-26 October"
  gh auth login
  git push -u origin results/cues-2026-10-21
  gh auth logout
  git checkout main
EOF
