#!/usr/bin/env python3
"""Take one question per topic x question type, for the first run on the new rubric.

    python samples/subset_prompts.py samples/prompts-2026-10-20.xlsx

Writes prompts-subset.xlsx beside the input: the questions the AI judges grade
on the 3 November rubric and the law school grades by hand. Only topics with
all four question types count (Env Justice has two Factual questions and
nothing else). Within a cell the pick prefers, in turn, a question with a
reference answer that the demographic screen also asked (prompts-half.xlsx, so
its answers can be reused), then one with a reference, then one the screen
asked, then any. Ties go to the lowest hash of the question id, so the same
subset comes out every time.

CE-002 and JS-006 are left out: their reference answers belong to other
questions (CE-002's is African Communities Together v. Lyons; JS-006's says
cocaine for a heroin question).
"""

import hashlib
import pathlib
import sys
from collections import defaultdict

EXCLUDE = {"CE-002", "JS-006"}


def main():
    import openpyxl

    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source = pathlib.Path(sys.argv[1])

    def read(path):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        return list(rows[0]), [r for r in rows[1:] if any(c is not None for c in r)]

    head, body = read(source)
    topic, qtype, pid = (head.index(h) for h in ("Topic", "Question Type", "Prompt ID"))
    comp = head.index("Ideal Answer Components")
    half_path = source.with_name("prompts-half.xlsx")
    half = {r[pid] for r in read(half_path)[1]} if half_path.exists() else set()

    cells = defaultdict(list)
    for r in body:
        if r[pid] not in EXCLUDE:
            cells[(r[topic], r[qtype])].append(r)
    types = sorted({k[1] for k in cells})
    topics = sorted(t for t in {k[0] for k in cells} if all((t, q) in cells for q in types))

    def rank(r):
        has_ref = bool(str(r[comp] or "").strip())
        return (not (has_ref and r[pid] in half), not has_ref, r[pid] not in half,
                hashlib.sha256(str(r[pid]).encode()).hexdigest())

    keep = [min(cells[(t, q)], key=rank) for t in topics for q in types]
    order = {r[pid]: i for i, r in enumerate(body)}
    keep.sort(key=lambda r: order[r[pid]])

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "prompts"
    sheet.append(head)
    for r in keep:
        sheet.append(list(r))
    out = source.with_name("prompts-subset.xlsx")
    book.save(out)

    print(f"wrote {out}: {len(keep)} questions, {len(topics)} topics x {len(types)} types")
    print(f"  asked in the demographic screen: {sum(r[pid] in half for r in keep)}; "
          f"with a reference answer: {sum(bool(str(r[comp] or '').strip()) for r in keep)}")
    missing = [r[pid] for r in keep if not str(r[comp] or "").strip()]
    if missing:
        print(f"  no reference answer: {', '.join(missing)}")
    print("  " + " ".join(r[pid] for r in keep))


if __name__ == "__main__":
    main()
