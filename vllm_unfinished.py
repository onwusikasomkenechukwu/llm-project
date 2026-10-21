#!/usr/bin/env python3
"""Mark answers that are unfinished thinking, in a run made before the fix.

    python vllm_unfinished.py vllm-responses.jsonl vllm-judgments.jsonl

Before 21 October, vllm_offline.py saved a reasoning model's thinking as its
answer when the model hit the answer ceiling before closing its thinking: the
chat template opens <think> in the prompt, so such an output has no tag to split
on. These are recognisable afterwards: the answer stopped at the ceiling with no
reasoning split off, from a model whose finished answers all had reasoning.

Such an answer becomes a failed response, as the runner now records it, and its
grades are marked failed too, since they graded thinking rather than an answer.
Both files are rewritten in place; a .bak copy of each is kept.
"""

import json
import shutil
import sys
from collections import defaultdict

ANSWER_TOKENS = 4000
ERROR = "Hit the max_tokens ceiling"


def rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write(path, data):
    shutil.copy(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    responses, judgments = rows(sys.argv[1]), rows(sys.argv[2])

    finished = defaultdict(list)
    for r in responses:
        if (r.get("output_tokens") or 0) < ANSWER_TOKENS and r.get("error") is None:
            finished[r["provider"]].append(r.get("reasoning_tokens") or 0)
    reasoners = {p for p, v in finished.items() if v and all(v)}

    bad = set()
    for r in responses:
        if (r["provider"] in reasoners and r.get("error") is None
                and (r.get("output_tokens") or 0) >= ANSWER_TOKENS
                and not r.get("reasoning_tokens")):
            r["reasoning_tokens"] = r["output_tokens"]
            r["response"], r["error"] = "", ERROR
            bad.add(r["id"])
    for j in judgments:
        if j["id"] in bad and j.get("error") is None:
            j["error"] = "Graded unfinished thinking, not an answer."

    write(sys.argv[1], responses)
    write(sys.argv[2], judgments)
    per = defaultdict(int)
    for r in responses:
        if r["id"] in bad:
            per[r["provider"]] += 1
    print(f"reasoning models: {sorted(reasoners)}")
    print(f"unfinished answers marked failed: {dict(per)}; "
          f"{sum(j['id'] in bad for j in judgments)} grades of them marked failed")


if __name__ == "__main__":
    main()
