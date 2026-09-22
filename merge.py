#!/usr/bin/env python3
"""Merge the per-script output files into one.

    python merge.py                 # merges both responses-*.jsonl and judgments-*.jsonl
    python merge.py responses       # just the answers
    python merge.py judgments       # just the judgments

Each of the four run scripts writes its own file, so they can all run at once
without racing each other for the same handle. This puts them back together.

Duplicates are resolved rather than concatenated. A cell that failed and was
later retried has both rows on disk; the successful one wins, and among several
successes the most recent timestamp wins. Nothing is deleted -- the per-script
files stay as they are, and this can be rerun any time.
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

KINDS = {
    # kind: (glob pattern, merged filename, what makes a row unique)
    "responses": ("responses-*.jsonl", "responses.jsonl", ("id",)),
    "judgments": ("judgments-*.jsonl", "judgments.jsonl", ("id", "judge", "pass")),
}


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"  skipped {path}:{n}, not valid JSON", file=sys.stderr)


def better(new, old):
    """True if `new` should replace `old` for the same key."""
    if old is None:
        return True
    new_ok, old_ok = new.get("error") is None, old.get("error") is None
    if new_ok != old_ok:
        return new_ok                       # a success always beats a failure
    return str(new.get("ts", "")) >= str(old.get("ts", ""))  # else the later one


def merge(kind, in_dir, out_path):
    pattern, default_out, key_fields = KINDS[kind]
    sources = sorted(glob.glob(os.path.join(in_dir, pattern)))
    out_path = out_path or os.path.join(in_dir, default_out)
    # never fold a previous merge back into itself
    sources = [s for s in sources if os.path.abspath(s) != os.path.abspath(out_path)]
    if not sources:
        print(f"{kind}: no {pattern} files in {in_dir or '.'}")
        return

    best, seen = {}, 0
    for path in sources:
        n = 0
        for row in read_jsonl(path):
            n += 1
            key = tuple(row.get(f) for f in key_fields)
            if better(row, best.get(key)):
                best[key] = row
        seen += n
        print(f"  {os.path.basename(path)}: {n} rows")

    rows = sorted(best.values(), key=lambda r: tuple(str(r.get(f)) for f in key_fields))
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, out_path)

    ok = sum(1 for r in rows if r.get("error") is None)
    print(f"{kind}: {seen} rows in, {len(rows)} unique, {ok} ok, "
          f"{len(rows) - ok} still failing -> {out_path}")

    by_provider = Counter(r.get("provider") for r in rows if r.get("error") is None)
    if by_provider:
        print("  ok by provider: " +
              ", ".join(f"{k}={v}" for k, v in sorted(by_provider.items(), key=str)))
    if len(rows) - ok:
        stuck = [r for r in rows if r.get("error") is not None][:3]
        print("  still failing, e.g. " +
              "; ".join(f"{r.get('id')}: {str(r.get('error'))[:70]}" for r in stuck))
        print("  rerun that provider's script to retry them")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", nargs="?", choices=list(KINDS), help="default: both")
    p.add_argument("--in-dir", default=".", help="where the per-script files are")
    p.add_argument("--out", help="merged file (only valid with a single kind)")
    args = p.parse_args()

    if args.out and not args.kind:
        sys.exit("--out needs a kind: merge.py responses --out ... ")
    for kind in ([args.kind] if args.kind else list(KINDS)):
        merge(kind, args.in_dir, args.out)


if __name__ == "__main__":
    main()
