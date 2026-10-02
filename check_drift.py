#!/usr/bin/env python3
"""Check duplicated benchmark contracts and reviewed configuration fingerprints.

    python check_drift.py
    python check_drift.py --write-baseline   # only after reviewing intentional changes

Parses source with ast; never imports runners or makes API calls.
"""

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path


RUNNERS = ("openai_batch.py", "anthropic_batch.py", "google_batch.py", "sequential.py")
CONSTANTS = ("IDENTITIES", "USER_TEMPLATE", "COMPONENTS_LINE", "REFERENCE_BLOCK", "JUDGE_PROMPT",
             "CRITERIA", "RATINGS", "QUESTION_TYPES", "ANSWER_TOKENS", "JUDGE_TOKENS")
FUNCTIONS = ("load_prompts", "answer_cells", "judge_cells", "parse_score", "make_row",
             "usable", "read_jsonl", "done_ids", "load_env", "verify_drift")
BATCH_FUNCTIONS = ("pending_batches", "batch_digest", "matching_batches")


class WithoutDocstrings(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            if isinstance(node.body[0].value.value, str):
                node.body = node.body[1:]
        return node


def definitions(path: Path) -> dict[str, ast.AST]:
    result = {}
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value
        elif isinstance(node, ast.FunctionDef):
            result[node.name] = WithoutDocstrings().visit(node)
    return result


def fingerprint(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def snapshot(root: Path) -> tuple[dict, list[str]]:
    trees, errors, hashes = {}, [], {}
    for filename in RUNNERS:
        tree = definitions(root / filename)
        trees[filename] = tree
        required = (*CONSTANTS, *FUNCTIONS, "PROVIDERS")
        if filename != "sequential.py":
            required += BATCH_FUNCTIONS
        hashes[filename] = {}
        for name in required:
            if name not in tree:
                errors.append(f"{filename}: missing {name}")
            else:
                hashes[filename][name] = fingerprint(tree[name])
    reference = hashes[RUNNERS[0]]
    for filename in RUNNERS[1:]:
        names = (*CONSTANTS, *FUNCTIONS)
        if filename != "sequential.py":
            names += BATCH_FUNCTIONS
        for name in names:
            if hashes[filename].get(name) != reference.get(name):
                errors.append(f"{filename}: {name} differs from {RUNNERS[0]}")
    for filename, names in (("check_run.py", ("CRITERIA", "QUESTION_TYPES", "verify_drift")),
                            ("analyze.py", ("CRITERIA",))):
        tree = definitions(root / filename)
        for name in names:
            if name not in tree or fingerprint(tree[name]) != reference.get(name):
                errors.append(f"{filename}: {name} differs from runner contract")
    runner_ids = tuple(ast.literal_eval(trees[RUNNERS[0]]["IDENTITIES"]))
    preflight = definitions(root / "check_run.py")
    if ast.literal_eval(preflight["IDENTITIES"]) != runner_ids:
        errors.append("check_run.py: identity list differs from runner identities")
    wrapper = definitions(root / "run_manifest.py")
    if tuple(ast.literal_eval(wrapper["DEFAULT_IDENTITIES"]).split(",")) != runner_ids:
        errors.append("run_manifest.py: default identities differ from runner identities")
    providers = ast.literal_eval(preflight["PROVIDERS"])
    if tuple(ast.literal_eval(wrapper["DEFAULT_PROVIDERS"]).split(",")) != providers:
        errors.append("run_manifest.py: default provider panel differs from preflight")
    return {"schema_version": 1, "fingerprints": hashes}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    baseline = args.baseline or args.root / "drift-baseline.json"
    try:
        current, errors = snapshot(args.root)
        if not errors and args.write_baseline:
            baseline.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Wrote reviewed baseline: {baseline}")
            return 0
        if not args.write_baseline:
            expected = json.loads(baseline.read_text(encoding="utf-8"))
            if expected.get("schema_version") != 1:
                errors.append("unsupported drift baseline schema")
            for filename, symbols in current["fingerprints"].items():
                old = expected.get("fingerprints", {}).get(filename, {})
                for name, value in symbols.items():
                    if old.get(name) != value:
                        errors.append(f"{filename}: {name} changed from the reviewed baseline")
        if errors:
            for error in errors:
                print(f"DRIFT: {error}", file=sys.stderr)
            return 1
        print("Drift guard passed: shared contracts agree and configuration matches the baseline.")
        return 0
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        print(f"DRIFT: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
