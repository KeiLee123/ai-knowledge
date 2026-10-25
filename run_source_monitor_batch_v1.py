#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from validate_source_monitor_schedule_v1 import (
    validate_schedule,
)


VERSION = "source-monitor-batch-v1"


def utc_stamp() -> str:
    return datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")


def git_identity(
    repo_root: Path,
) -> dict:
    branch = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "branch",
            "--show-current",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    if branch != "staging":
        raise RuntimeError(
            "Batch checkout must be on staging branch"
        )

    status = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    if status:
        raise RuntimeError(
            "Batch checkout worktree must be clean"
        )

    commit = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "HEAD",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    return {
        "branch": branch,
        "commit": commit,
        "worktree_clean": True,
    }


def extract_monitor_result(
    text: str,
) -> dict | None:
    decoder = json.JSONDecoder()

    for index, char in enumerate(text):
        if char != "{":
            continue

        try:
            obj, _ = decoder.raw_decode(
                text[index:]
            )
        except Exception:
            continue

        if (
            isinstance(obj, dict)
            and obj.get("version")
            == "official-source-monitor-v1"
        ):
            return obj

    return None


def execute_sources(
    source_ids: list[str],
    run_one,
) -> list[dict]:
    results = []

    for source_id in source_ids:
        try:
            result = run_one(
                source_id
            )
        except Exception as exc:
            result = {
                "source_id": source_id,
                "execution_status":
                    "EXECUTION_FAILED",
                "return_code": None,
                "error":
                    f"{type(exc).__name__}: {exc}",
                "production_access": False,
                "production_write": False,
            }

        results.append(
            result
        )

    return results


def run_one_source(
    *,
    source_id: str,
    runner: Path,
    repo_root: Path,
    python: Path,
    state_root: Path,
    run_root: Path,
) -> dict:
    env = dict(
        os.environ
    )

    env.update(
        {
            "JASON_REPO_ROOT":
                str(repo_root),
            "JASON_PYTHON":
                str(python),
            "JASON_SOURCE_MONITOR_SOURCE_ID":
                source_id,
            "JASON_SOURCE_MONITOR_STATE_ROOT":
                str(state_root),
            "JASON_SOURCE_MONITOR_RUN_ROOT":
                str(run_root),
            "JASON_SOURCE_MONITOR_LOCK_FILE":
                (
                    "/run/lock/"
                    "jason-os-source-monitor-staging-"
                    + source_id
                    + ".lock"
                ),
        }
    )

    result = subprocess.run(
        [
            "/bin/bash",
            str(runner),
        ],
        text=True,
        capture_output=True,
        env=env,
    )

    stdout = result.stdout
    stderr = result.stderr

    if (
        "STATUS: SOURCE_MONITOR_STAGING_V2 "
        "SKIPPED_ALREADY_RUNNING"
        in stdout
    ):
        return {
            "source_id": source_id,
            "execution_status":
                "SKIPPED_ALREADY_RUNNING",
            "return_code":
                result.returncode,
            "decision": None,
            "action": None,
            "run_dir": None,
            "production_access": False,
            "production_write": False,
        }

    monitor = extract_monitor_result(
        stdout
    )

    if result.returncode != 0:
        return {
            "source_id": source_id,
            "execution_status":
                "EXECUTION_FAILED",
            "return_code":
                result.returncode,
            "decision":
                (
                    monitor.get("decision")
                    if monitor
                    else None
                ),
            "action":
                (
                    monitor.get("action")
                    if monitor
                    else None
                ),
            "error":
                stderr.strip()
                or "monitor runner failed",
            "production_access": False,
            "production_write": False,
        }

    if monitor is None:
        return {
            "source_id": source_id,
            "execution_status":
                "EXECUTION_FAILED",
            "return_code":
                result.returncode,
            "decision": None,
            "action": None,
            "error":
                "monitor result JSON missing",
            "production_access": False,
            "production_write": False,
        }

    if (
        monitor.get(
            "production_access"
        )
        is not False
        or monitor.get(
            "production_write"
        )
        is not False
    ):
        return {
            "source_id": source_id,
            "execution_status":
                "EXECUTION_FAILED",
            "return_code": 65,
            "decision":
                monitor.get("decision"),
            "action":
                monitor.get("action"),
            "error":
                "unsafe Production flag in monitor result",
            "production_access": False,
            "production_write": False,
        }

    run_dir = None

    for line in stdout.splitlines():
        if line.startswith(
            "run_dir="
        ):
            run_dir = line.split(
                "=",
                1,
            )[1]
            break

    return {
        "source_id": source_id,
        "execution_status":
            "EXECUTION_SUCCESS",
        "return_code":
            result.returncode,
        "baseline_status":
            monitor.get(
                "baseline_status"
            ),
        "decision":
            monitor.get("decision"),
        "action":
            monitor.get("action"),
        "candidate_downloaded":
            monitor.get(
                "candidate_downloaded"
            ),
        "run_dir":
            run_dir,
        "production_access": False,
        "production_write": False,
    }


def overall_status(
    results: list[dict],
) -> str:
    if all(
        result.get(
            "execution_status"
        )
        in (
            "EXECUTION_SUCCESS",
            "SKIPPED_ALREADY_RUNNING",
        )
        for result in results
    ):
        return "SUCCESS"

    return "PARTIAL_FAILURE"


def write_summary(
    path: Path,
    payload: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_batch(
    *,
    repo_root: Path,
    schedule_path: Path,
    registry_path: Path,
    state_root: Path,
    runner: Path,
    python: Path,
    batch_lock: Path,
) -> dict:
    git = git_identity(
        repo_root
    )

    schedule = validate_schedule(
        schedule_path=
            schedule_path,
        registry_path=
            registry_path,
        state_root=
            state_root,
        require_references=True,
    )

    batch_lock.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock_stream = batch_lock.open(
        "a+",
        encoding="utf-8",
    )

    try:
        try:
            fcntl.flock(
                lock_stream.fileno(),
                fcntl.LOCK_EX
                | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            return {
                "version": VERSION,
                "status":
                    "SKIPPED_ALREADY_RUNNING",
                "source_ids":
                    schedule["source_ids"],
                "production_access":
                    False,
                "production_write":
                    False,
            }

        stamp = utc_stamp()

        batch_dir = (
            state_root
            / "batches"
            / stamp
        )

        summary_path = (
            batch_dir
            / "summary.json"
        )

        run_root = (
            state_root
            / "runs"
        )

        def invoke(
            source_id: str,
        ) -> dict:
            return run_one_source(
                source_id=source_id,
                runner=runner,
                repo_root=repo_root,
                python=python,
                state_root=state_root,
                run_root=run_root,
            )

        results = execute_sources(
            schedule[
                "source_ids"
            ],
            invoke,
        )

        payload = {
            "version": VERSION,
            "batch_timestamp":
                stamp,
            "git_branch":
                git["branch"],
            "git_commit":
                git["commit"],
            "source_ids":
                schedule[
                    "source_ids"
                ],
            "results":
                results,
            "overall_status":
                overall_status(
                    results
                ),
            "production_access":
                False,
            "production_write":
                False,
        }

        write_summary(
            summary_path,
            payload,
        )

        payload[
            "summary_path"
        ] = str(
            summary_path
        )

        return payload
    finally:
        lock_stream.close()


def main() -> None:
    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    parser = argparse.ArgumentParser(
        description=(
            "Sequential M9 Staging source-monitor batch "
            "dispatcher. No Production access or writes."
        )
    )

    parser.add_argument(
        "--schedule",
        default=str(
            repo_root
            / "source_monitor_schedule_v1.yaml"
        ),
    )
    parser.add_argument(
        "--registry",
        default=str(
            repo_root
            / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--state-root",
        default=(
            "/var/lib/jason-os/"
            "source-monitor-staging"
        ),
    )
    parser.add_argument(
        "--runner",
        default=str(
            repo_root
            / "ops"
            / "run_source_monitor_staging_v2.sh"
        ),
    )
    parser.add_argument(
        "--python",
        default=str(
            repo_root
            / ".venv"
            / "bin"
            / "python"
        ),
    )
    parser.add_argument(
        "--batch-lock",
        default=(
            "/run/lock/"
            "jason-os-source-monitor-staging-batch.lock"
        ),
    )

    args = parser.parse_args()

    result = run_batch(
        repo_root=repo_root,
        schedule_path=Path(
            args.schedule
        ).expanduser().resolve(),
        registry_path=Path(
            args.registry
        ).expanduser().resolve(),
        state_root=Path(
            args.state_root
        ).expanduser(),
        runner=Path(
            args.runner
        ).expanduser().resolve(),
        python=Path(
            args.python
        ).expanduser().resolve(),
        batch_lock=Path(
            args.batch_lock
        ).expanduser(),
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    print()

    if (
        result.get("status")
        == "SKIPPED_ALREADY_RUNNING"
    ):
        print(
            "STATUS: SOURCE_MONITOR_BATCH "
            "SKIPPED_ALREADY_RUNNING"
        )
        return

    print(
        "STATUS: SOURCE_MONITOR_BATCH "
        + result[
            "overall_status"
        ]
    )

    if (
        result[
            "overall_status"
        ]
        != "SUCCESS"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
