#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path


GUARD_VERSION = "production-promotion-guard-v1"

PRODUCTION_DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
STAGING_DB_CONTAINER = "jason-os-knowledge-db-staging"

REQUIRED_BRANCH = "main"


def run_checked(command):
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or (
                "Command failed with exit code "
                f"{result.returncode}: "
                + " ".join(command)
            )
        )

    return result


def get_repo_branch(repo_root):
    result = run_checked(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        ]
    )

    return result.stdout.strip()


def inspect_container(container):
    result = run_checked(
        [
            "docker",
            "inspect",
            container,
        ]
    )

    payload = json.loads(result.stdout)

    if (
        not isinstance(payload, list)
        or len(payload) != 1
    ):
        raise RuntimeError(
            "Unexpected docker inspect response"
        )

    return payload[0]


def evaluate_guardrails(
    *,
    branch,
    container,
    inspect_data,
):
    errors = []

    if branch != REQUIRED_BRANCH:
        errors.append(
            "Git branch must be 'main'"
        )

    if container != PRODUCTION_DB_CONTAINER:
        errors.append(
            "DB container must equal the fixed "
            "Production Knowledge DB container"
        )

    if container == STAGING_DB_CONTAINER:
        errors.append(
            "Staging DB container is forbidden"
        )

    if PRODUCTION_DB_CONTAINER == STAGING_DB_CONTAINER:
        errors.append(
            "Production and Staging DB constants must differ"
        )

    observed_name = str(
        inspect_data.get("Name")
        or ""
    ).lstrip("/")

    if observed_name != PRODUCTION_DB_CONTAINER:
        errors.append(
            "Docker inspect container name does not match "
            "the fixed Production DB container"
        )

    state = inspect_data.get("State") or {}
    running = bool(state.get("Running"))

    if not running:
        errors.append(
            "Production DB container must be running"
        )

    status = state.get("Status")

    if status and status != "running":
        errors.append(
            "Production DB container status must be running"
        )

    health = (
        (state.get("Health") or {}).get("Status")
    )

    if health and health != "healthy":
        errors.append(
            "Production DB container health must be healthy "
            "when a Docker health check is configured"
        )

    return {
        "guard_version": GUARD_VERSION,
        "required_branch": REQUIRED_BRANCH,
        "branch": branch,
        "production_db_container": PRODUCTION_DB_CONTAINER,
        "staging_db_container": STAGING_DB_CONTAINER,
        "db_container": container,
        "observed_container_name": observed_name,
        "running": running,
        "status": status,
        "health": health,
        "production_write_performed": False,
        "guard_ok": not errors,
        "errors": errors,
    }


def verify_runtime(repo_root):
    branch = get_repo_branch(repo_root)

    inspect_data = inspect_container(
        PRODUCTION_DB_CONTAINER
    )

    result = evaluate_guardrails(
        branch=branch,
        container=PRODUCTION_DB_CONTAINER,
        inspect_data=inspect_data,
    )

    if not result["guard_ok"]:
        raise RuntimeError(
            "Production promotion guard failed: "
            + "; ".join(result["errors"])
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Production Promotion v1 guard. "
            "Verifies the main branch and the fixed Production "
            "Knowledge DB container. It performs no database write."
        )
    )

    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Verify Production branch/container identity only. "
            "This command never writes to the database."
        ),
    )

    args = parser.parse_args()

    if not args.verify_only:
        raise SystemExit(
            "Only --verify-only is supported by P1"
        )

    repo_root = Path(__file__).resolve().parent

    try:
        result = verify_runtime(repo_root)
    except Exception as exc:
        raise SystemExit(
            "PRODUCTION PROMOTION GUARD FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print("PRODUCTION PROMOTION GUARD: PASS")
    print("No database query or write was executed.")


if __name__ == "__main__":
    main()
