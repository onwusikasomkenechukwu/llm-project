#!/usr/bin/env python3
"""Freeze a run, execute recorded commands, and verify its artifacts.

    python run_manifest.py create prompts.xlsx --out runs/study/manifest.json --polarity pos
    python run_manifest.py run runs/study/manifest.json openai answer --dry-run
    python run_manifest.py run runs/study/manifest.json openai judge
    python run_manifest.py finish runs/study/manifest.json
    python run_manifest.py verify runs/study/manifest.json

The manifest is immutable. events.jsonl records invocations and artifact hashes.
No credentials or environment values are saved. Integrity hashes are not signatures.
"""

import argparse
import ast
import contextlib
import getpass
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS = {"openai": "openai_batch.py", "anthropic": "anthropic_batch.py",
           "google": "google_batch.py", "xai": "sequential.py",
           "muse": "sequential.py", "local": "sequential.py"}
DEFAULT_PROVIDERS = "openai,anthropic,google,xai,muse"
DEFAULT_IDENTITIES = ("none,black-american,white-american,latino-american,christian,muslim,jewish,"
                      "conservative,progressive,libertarian,woman,man,learning-disability,"
                      "disabled-veteran,immigrant,native-american,transgender-woman,non-binary")
PACKAGES = ("openpyxl", "openai", "anthropic", "google-genai")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def environment() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": platform.python_version(), "packages": versions}


def source_hashes(root: Path) -> dict:
    paths = list(root.glob("*.py")) + list((root / "samples").glob("*.py"))
    paths += [root / name for name in ("pyproject.toml", "uv.lock", "drift-baseline.json")]
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths) if path.is_file()}


def settings_snapshot(root: Path) -> dict:
    class LiteralDict(ast.NodeTransformer):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
                return ast.Dict(keys=[ast.Constant(k.arg) for k in node.keywords],
                                values=[self.visit(k.value) for k in node.keywords])
            raise ValueError("configuration must contain only literal values")
    result = {}
    names = {"PROVIDERS", "IDENTITIES", "USER_TEMPLATE", "JUDGE_PROMPT", "REFERENCE_BLOCK",
             "COMPONENTS_LINE", "CRITERIA", "RATINGS", "QUESTION_TYPES", "ANSWER_TOKENS", "JUDGE_TOKENS"}
    for filename in sorted(set(SCRIPTS.values())):
        settings = {}
        for node in ast.parse((root / filename).read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        settings[target.id] = ast.literal_eval(LiteralDict().visit(node.value))
        if names - settings.keys():
            raise ValueError(f"{filename}: required configuration is missing")
        result[filename] = settings
    return result


def git_state(root: Path) -> dict:
    result = {}
    for key, command in (("commit", ["rev-parse", "HEAD"]), ("status", ["status", "--porcelain"])):
        try:
            proc = subprocess.run(["git", "-C", str(root), *command], capture_output=True, text=True)
            result[key] = proc.stdout.strip() if proc.returncode == 0 else None
        except OSError:
            result[key] = None
    return result


@contextlib.contextmanager
def lock(path: Path, wait: bool = False):
    deadline = time.monotonic() + (10 if wait else 0)
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError(f"lock exists: {path}; check its process before removing a stale lock") from None
            time.sleep(.05)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "started_at": utc_now()}, stream)
        yield
    finally:
        path.unlink()


def read_events(directory: Path) -> list[dict]:
    with lock(directory / ".events.lock", wait=True):
        return _read_events(directory)


def _read_events(directory: Path) -> list[dict]:
    path = directory / "events.jsonl"
    if not path.exists():
        if (directory / "events.sha256").exists():
            raise ValueError("event log is missing")
        return []
    events, previous = [], None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"event {n} is not an object")
        claimed = event.get("sha256")
        payload = {k: v for k, v in event.items() if k != "sha256"}
        if event.get("previous") != previous or hashlib.sha256(canonical(payload)).hexdigest() != claimed:
            raise ValueError(f"event chain broken at row {n}")
        events.append(event)
        previous = claimed
    head = directory / "events.sha256"
    if not head.is_file() or head.read_text(encoding="ascii").strip() != previous:
        raise ValueError("event log head mismatch; log may have been truncated")
    return events


def record_event(directory: Path, event: dict) -> None:
    with lock(directory / ".events.lock", wait=True):
        events = _read_events(directory)
        payload = event | {"ts": utc_now(), "previous": events[-1]["sha256"] if events else None}
        payload["sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        head = directory / ".events-head.tmp"
        head.write_text(payload["sha256"] + "\n", encoding="ascii")
        os.replace(head, directory / "events.sha256")


def load_manifest(path: Path, artifacts: bool = False) -> dict:
    expected = path.with_suffix(".sha256").read_text(encoding="ascii").strip()
    if digest(path) != expected:
        raise ValueError("manifest hash mismatch; restore the manifest or create a new run")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema")
    root = Path(manifest["code_root"])
    if source_hashes(root) != manifest["sources"]:
        raise ValueError("source code changed since this run was frozen")
    if environment() != manifest["environment"]:
        raise ValueError("Python or package versions changed since this run was frozen")
    if digest(path.parent / "prompts.xlsx") != manifest["workbook"]["sha256"]:
        raise ValueError("frozen prompt workbook changed")
    events = read_events(path.parent)
    if not events or events[0].get("manifest_sha256") != expected:
        raise ValueError("manifest creation event missing or inconsistent")
    if artifacts:
        active = {e["invocation_id"] for e in events if e["event"] == "started"}
        active -= {e["invocation_id"] for e in events if e["event"] == "finished"}
        if active:
            raise ValueError(f"{len(active)} invocation(s) active or interrupted; inspect events.jsonl and locks")
        latest = {}
        for event in events:
            latest.update(event.get("artifacts", {}))
        for name, expected_hash in latest.items():
            target = path.parent / name
            if not target.is_file() or digest(target) != expected_hash:
                raise ValueError(f"artifact changed or missing: {name}")
        known = set(latest)
        for target in path.parent.glob("*.jsonl"):
            if target.name != "events.jsonl" and target.name not in known:
                raise ValueError(f"unrecorded output: {target.name}")
    return manifest


def grid_args(grid: dict) -> list[str]:
    args = ["--sheet", str(grid["sheet"]), "--polarity", grid["polarity"]]
    for key in ("id_col", "pos_col", "neg_col", "limit"):
        if grid.get(key) is not None:
            args.extend(["--" + key.replace("_", "-"), str(grid[key])])
    return args


def preflight_command(manifest: dict, directory: Path, outputs: bool = False) -> list[str]:
    grid = manifest["grid"]
    cmd = [sys.executable, str(Path(manifest["code_root"]) / "check_run.py"),
           str(directory / "prompts.xlsx"), *grid_args(grid),
           "--providers", grid["providers"], "--judges", grid["judges"],
           "--identities", grid["identities"], "--duplicates", str(grid["duplicates"]),
           "--passes", str(grid["passes"])]
    if outputs:
        cmd += ["--responses", str(directory / "responses.jsonl"),
                "--judgments", str(directory / "judgments.jsonl")]
    return cmd


def create_manifest(args) -> Path:
    path = args.out.resolve()
    if path.name != "manifest.json":
        raise ValueError("--out must name manifest.json in a new run directory")
    if path.parent.exists() and any(path.parent.iterdir()):
        raise ValueError("choose an empty run directory; existing artifacts must not enter a new run")
    path.parent.mkdir(parents=True, exist_ok=True)
    grid = {name: getattr(args, name) for name in (
        "providers", "judges", "identities", "duplicates", "passes", "polarity",
        "sheet", "id_col", "pos_col", "neg_col", "limit")}
    for key in ("providers", "judges", "identities"):
        grid[key] = ",".join(value.strip() for value in grid[key].split(",") if value.strip())
    manifest = {"schema_version": 1, "run_id": str(uuid.uuid4()), "created_at": utc_now(),
                "operator": args.operator, "label": args.label, "code_root": str(ROOT),
                "environment": environment(), "sources": source_hashes(ROOT), "git": git_state(ROOT),
                "settings": settings_snapshot(ROOT),
                "workbook": {"original_path": str(args.prompts.resolve()), "sha256": digest(args.prompts)},
                "grid": grid}
    frozen = path.parent / "prompts.xlsx"
    shutil.copyfile(args.prompts, frozen)
    result = subprocess.run(preflight_command(manifest, path.parent), cwd=ROOT)
    if result.returncode:
        frozen.unlink()
        raise ValueError("preflight failed; manifest was not created")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    path.with_suffix(".sha256").write_text(digest(path) + "\n", encoding="ascii")
    record_event(path.parent, {"event": "created", "run_id": manifest["run_id"],
                              "manifest_sha256": digest(path), "operator": args.operator})
    return path


def runner_command(manifest: dict, directory: Path, args) -> tuple[list[str], list[Path]]:
    provider, stage, grid = args.provider, args.stage, manifest["grid"]
    allowed = grid["providers"] if stage == "answer" else grid["judges"]
    if provider not in allowed.split(","):
        raise ValueError(f"{provider} is not in the manifest's {stage} panel")
    if not 0 <= args.pass_ < grid["passes"]:
        raise ValueError("judge pass is outside the manifest grid")
    if stage == "answer" and args.pass_ != 0:
        raise ValueError("--pass applies only to judging")
    root = Path(manifest["code_root"])
    output = directory / f"{'responses' if stage == 'answer' else 'judgments'}-{provider}.jsonl"
    source = directory / ("prompts.xlsx" if stage == "answer" else "responses.jsonl")
    command = [sys.executable, str(root / SCRIPTS[provider]), stage, str(source),
               "--providers", provider, "--out", str(output), "--duplicates", str(grid["duplicates"]),
               "--identities", grid["identities"], "--pass", str(args.pass_)]
    selection = dict(grid)
    if stage == "judge":
        # Judge --limit counts answers, whereas the manifest limit counts questions.
        selection["limit"] = None
        command += ["--prompts", str(directory / "prompts.xlsx")]
    command += grid_args(selection)
    artifacts = [output]
    if provider in ("openai", "anthropic", "google"):
        state = directory / f".batches-{provider}-{stage}-p{args.pass_}.jsonl"
        command += ["--state", str(state)]
        artifacts.append(state)
    elif args.now or args.wait or args.no_submit:
        raise ValueError("--now, --wait and --no-submit apply to batch providers only")
    for option in ("dry_run", "now", "wait", "no_submit"):
        if getattr(args, option):
            command.append("--" + option.replace("_", "-"))
    return command, artifacts


def execute(path: Path, manifest: dict, command: list[str], artifacts: list[Path], label: str,
            pipeline_locked: bool = False) -> int:
    directory = path.parent
    invocation = str(uuid.uuid4())
    with contextlib.ExitStack() as stack:
        if pipeline_locked:
            stack.enter_context(lock(directory / f".{label}.lock"))
        else:
            with lock(directory / ".pipeline.lock"):
                stack.enter_context(lock(directory / f".{label}.lock"))
        events = read_events(directory)
        latest = {}
        for event in events:
            latest.update(event.get("artifacts", {}))
        for target in artifacts:
            name = target.relative_to(directory).as_posix()
            if target.is_file() and latest.get(name) != digest(target):
                raise ValueError(f"unrecorded or changed output: {name}")
            if name in latest and not target.is_file():
                raise ValueError(f"recorded output is missing: {name}")
        if "judge" in command:
            answers = directory / "responses.jsonl"
            if not answers.is_file() or digest(answers) != latest.get("responses.jsonl"):
                raise ValueError("merge responses through the manifest before judging")
        before = {p.relative_to(directory).as_posix(): digest(p) for p in artifacts if p.is_file()}
        record_event(directory, {"event": "started", "run_id": manifest["run_id"],
                                 "invocation_id": invocation, "command": command,
                                 "pid": os.getpid(), "lock": f".{label}.lock",
                                 "artifact_targets": [p.relative_to(directory).as_posix() for p in artifacts],
                                 "operator": getpass.getuser(), "artifacts_before": before})
        env = dict(os.environ, BENCHMARK_RUN_ID=manifest["run_id"], BENCHMARK_INVOCATION_ID=invocation)
        code, failure = 130, None
        try:
            code = subprocess.run(command, cwd=manifest["code_root"], env=env).returncode
            return code
        except BaseException as exc:
            failure = type(exc).__name__
            raise
        finally:
            after = {p.relative_to(directory).as_posix(): digest(p) for p in artifacts if p.is_file()}
            record_event(directory, {"event": "finished", "run_id": manifest["run_id"],
                                     "invocation_id": invocation, "exit_code": code,
                                     "failure": failure, "artifacts": after})


def merge_outputs(path: Path, manifest: dict, kind: str | None) -> int:
    directory = path.parent
    with lock(directory / ".pipeline.lock"):
        if any(p.name != ".pipeline.lock" for p in directory.glob(".*.lock")):
            raise ValueError("provider commands are active; merge after they exit")
        command = [sys.executable, str(Path(manifest["code_root"]) / "merge.py")]
        if kind:
            command.append(kind)
        command += ["--in-dir", str(directory)]
        artifacts = [directory / f"{name}.jsonl" for name in ([kind] if kind else ["responses", "judgments"])]
        return execute(path, manifest, command, artifacts, "merge", pipeline_locked=True)


def recover(path: Path, manifest: dict, invocation: str, reason: str) -> None:
    if not reason.strip():
        raise ValueError("record a reason for recovering the interrupted invocation")
    directory = path.parent
    with lock(directory / ".pipeline.lock"):
        events = read_events(directory)
        started = next((e for e in events if e.get("invocation_id") == invocation and e["event"] == "started"), None)
        if not started or any(e.get("invocation_id") == invocation and e["event"] == "finished" for e in events):
            raise ValueError("invocation is not an unfinished recorded command")
        if (directory / started["lock"]).exists():
            raise ValueError("invocation lock remains; confirm its process stopped before removing the stale lock")
        artifacts = {name: digest(directory / name) for name in started["artifact_targets"]
                     if (directory / name).is_file()}
        record_event(directory, {"event": "finished", "run_id": manifest["run_id"],
                                 "invocation_id": invocation, "exit_code": 130,
                                 "failure": "recovered_interruption", "reason": reason,
                                 "operator": getpass.getuser(), "artifacts": artifacts})


def finish(path: Path, manifest: dict) -> int:
    with lock(path.parent / ".pipeline.lock"):
        return _finish(path, manifest)


def _finish(path: Path, manifest: dict) -> int:
    root, directory = Path(manifest["code_root"]), path.parent
    if any(p.name != ".pipeline.lock" for p in directory.glob(".*.lock")):
        raise ValueError("run commands are still active; finish after they exit")
    commands = [
        ([sys.executable, str(root / "merge.py"), "--in-dir", str(directory)],
         [directory / "responses.jsonl", directory / "judgments.jsonl"], "merge"),
        (preflight_command(manifest, directory, outputs=True), [], "preflight"),
        ([sys.executable, str(root / "analyze.py"), str(directory / "judgments.jsonl"),
          "--responses", str(directory / "responses.jsonl"), "--out-dir", str(directory / "analysis")],
         [directory / "analysis" / name for name in (
             "summary.json", "by_provider.csv", "by_identity.csv", "by_question_type.csv",
             "by_judge.csv", "by_polarity.csv", "judge_matrix.csv", "identity_differences.csv",
             "model_differences.csv", "self_preference.csv", "replicate_variability.csv")], "analysis")]
    for command, artifacts, label in commands:
        code = execute(path, manifest, command, artifacts, label, pipeline_locked=True)
        if code:
            return code
    record_event(directory, {"event": "complete", "run_id": manifest["run_id"]})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="freeze a new run")
    create.add_argument("prompts", type=Path)
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--operator", default=getpass.getuser())
    create.add_argument("--label", default="")
    create.add_argument("--providers", default=DEFAULT_PROVIDERS)
    create.add_argument("--judges", default=DEFAULT_PROVIDERS)
    create.add_argument("--identities", default=DEFAULT_IDENTITIES)
    create.add_argument("--duplicates", type=int, default=3)
    create.add_argument("--passes", type=int, default=1)
    create.add_argument("--polarity", choices=["auto", "pos", "pos-neg"], default="auto")
    create.add_argument("--sheet", default="0")
    create.add_argument("--id-col")
    create.add_argument("--pos-col")
    create.add_argument("--neg-col")
    create.add_argument("--limit", type=int)
    run = sub.add_parser("run", help="execute one provider and stage")
    run.add_argument("manifest", type=Path)
    run.add_argument("provider", choices=list(SCRIPTS))
    run.add_argument("stage", choices=["answer", "judge"])
    run.add_argument("--pass", dest="pass_", type=int, default=0)
    for flag in ("dry-run", "now", "wait", "no-submit"):
        run.add_argument("--" + flag, action="store_true")
    for name in ("finish", "verify"):
        sub.add_parser(name).add_argument("manifest", type=Path)
    merge_parser = sub.add_parser("merge")
    merge_parser.add_argument("manifest", type=Path)
    merge_parser.add_argument("kind", choices=["responses", "judgments"])
    recovery = sub.add_parser("recover")
    recovery.add_argument("manifest", type=Path)
    recovery.add_argument("invocation")
    recovery.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            print(f"Created {create_manifest(args)}")
            return 0
        path = args.manifest.resolve()
        manifest = load_manifest(path, artifacts=args.command in ("verify", "finish", "merge"))
        if args.command == "verify":
            events = read_events(path.parent)
            complete = events[-1]["event"] == "complete"
            print(f"Integrity verified: {manifest['run_id']}; completed pipeline: {complete}")
            return 0
        if args.command == "finish":
            return finish(path, manifest)
        if args.command == "merge":
            return merge_outputs(path, manifest, args.kind)
        if args.command == "recover":
            recover(path, manifest, args.invocation, args.reason)
            print("Interrupted invocation recorded; rerun its original command to resume.")
            return 0
        command, artifacts = runner_command(manifest, path.parent, args)
        return execute(path, manifest, command, artifacts, artifacts[0].stem)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
