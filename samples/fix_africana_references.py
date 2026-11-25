#!/usr/bin/env python3
"""Give every Pre-Enslavement Africana Heritage question its own answer elements.

    python samples/fix_africana_references.py prompts samples/prompts-2026-10-20.xlsx samples/prompts-2026-11-24.xlsx
    python samples/fix_africana_references.py prompts samples/prompts-subset.xlsx samples/prompts-subset-2026-11-24.xlsx samples/prompts-2026-11-24.xlsx
    python samples/fix_africana_references.py labels labels.xlsx key.csv samples/prompts-2026-11-24.xlsx labels-2026-11-24.xlsx

Kweli wrote on 24 November that the topic's gold-standard answer elements were
mapped to the wrong questions in the team sheet, and fixed it there. Our sheet
of 20 October had elements on five of the 20 questions, three of them wrong
(PEAH-010, 011 and 012). The topic has five questions, each in four variants,
and every variant takes its question's elements, as the fixed team sheet has.

The five texts are unchanged; only where they sit moves. Each is found by its
opening words, wherever it sits in the input, so running this again on its own
output changes nothing. `prompts` rewrites a prompts workbook; a sheet that
lacks some of the texts (the subset) takes them from a third, full one. `labels`
rewrites the hand-grading sheet's reference column for the same questions
(rows matched to questions through key.csv) and prints the rows that changed.
Every other question and cell is left as it is.
"""

import csv
import sys

# the opening words of each set of elements, and the questions it belongs to,
# as the team sheet had them on 25 November (Kweli swapped the 005-008 and
# 013-016 sets that day, after the fix of the 24th)
GROUPS = [
    ("Answers affirmatively without questioning", ["PEAH-001", "PEAH-002", "PEAH-003", "PEAH-004"]),
    ("Locates causation in European demand", ["PEAH-005", "PEAH-006", "PEAH-007", "PEAH-008"]),
    ("Answers affirmatively across every time horizon", ["PEAH-009", "PEAH-010", "PEAH-011", "PEAH-012"]),
    ("Establishes what existed beforehand", ["PEAH-013", "PEAH-014", "PEAH-015", "PEAH-016"]),
    # the team sheet numbers the last two PEOH, and so does every run
    ("Explains why the racial category is anachronistic", ["PEAH-017", "PEAH-018", "PEOH-019", "PEOH-020"]),
]


def texts(cells):
    """Each group's text, found by its opening words among `cells`."""
    cells, found = list(cells), {}
    for opening, _ in GROUPS:
        hits = {c.strip() for c in cells if c and str(c).strip().startswith(opening)}
        if len(hits) != 1:
            sys.exit(f"expected one text starting {opening!r}, found {len(hits)}")
        found[opening] = hits.pop()
    return {q: found[opening] for opening, qs in GROUPS for q in qs}


def column(sheet, name):
    head = [c.value for c in sheet[1]]
    if name not in head:
        sys.exit(f"{sheet.title}: no {name!r} column")
    return head.index(name) + 1


def components(sheet):
    comp = column(sheet, "Ideal Answer Components")
    return [sheet.cell(r, comp).value for r in range(2, sheet.max_row + 1)]


def prompts(src, out, texts_from=None):
    import openpyxl
    book = openpyxl.load_workbook(src)
    sheet = book.worksheets[0]
    pid, comp = column(sheet, "Prompt ID"), column(sheet, "Ideal Answer Components")
    want = texts(components(openpyxl.load_workbook(texts_from).worksheets[0] if texts_from else sheet))
    changed = []
    for r in range(2, sheet.max_row + 1):
        q = sheet.cell(r, pid).value
        if q in want and (sheet.cell(r, comp).value or "").strip() != want[q]:
            sheet.cell(r, comp).value = want[q]
            changed.append(q)
    book.save(out)
    print(f"wrote {out}: {len(changed)} questions changed")
    print("  " + " ".join(changed))


def labels(src, key, prompts_path, out):
    import openpyxl
    sheet = openpyxl.load_workbook(prompts_path, read_only=True).worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    head = list(rows[0])
    pid, comp = head.index("Prompt ID"), head.index("Ideal Answer Components")
    want = texts(r[comp] for r in rows[1:])
    qid = {r["row_id"]: r["qid"] for r in csv.DictReader(open(key, encoding="utf-8"))}
    book = openpyxl.load_workbook(src)
    lab = book["Labels"]
    rid, ref = column(lab, "Row ID"), column(lab, "Reference answer components")
    changed = []
    for r in range(2, lab.max_row + 1):
        q = qid.get(lab.cell(r, rid).value)
        if q in want and (lab.cell(r, ref).value or "").strip() != want[q]:
            lab.cell(r, ref).value = want[q]
            changed.append(f"{lab.cell(r, rid).value} ({q})")
    book.save(out)
    print(f"wrote {out}: {len(changed)} rows changed")
    print("  " + ", ".join(changed))


if __name__ == "__main__":
    if len(sys.argv) in (4, 5) and sys.argv[1] == "prompts":
        prompts(*sys.argv[2:])
    elif len(sys.argv) == 6 and sys.argv[1] == "labels":
        labels(*sys.argv[2:])
    else:
        sys.exit(__doc__)
