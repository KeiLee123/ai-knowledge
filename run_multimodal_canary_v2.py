#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


CANARY_GUARD_VERSION = "canary-guard-v1"
STAGING_DB_CONTAINER = "jason-os-knowledge-db-staging"
PRODUCTION_DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"

EXPECTED_LABELS = {
    "com.jasonos.environment": "staging",
    "com.jasonos.purpose": "knowledge-canary",
}


def run_checked(
    command: list[str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        text=True,
        capture_output=capture_output,
    )

    if result.returncode != 0:
        if capture_output:
            if result.stdout:
                print(
                    result.stdout,
                    file=sys.stderr,
                )
            if result.stderr:
                print(
                    result.stderr,
                    file=sys.stderr,
                )

        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + " ".join(command)
        )

    return result


def read_json_command(
    command: list[str],
):
    result = run_checked(
        command,
        capture_output=True,
    )

    return json.loads(
        result.stdout
    )


def get_repo_branch(
    repo_root: Path,
) -> str:
    result = run_checked(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        ],
        capture_output=True,
    )

    return result.stdout.strip()


def inspect_container(
    container: str,
) -> dict:
    payload = read_json_command(
        [
            "docker",
            "inspect",
            container,
        ]
    )

    if (
        not isinstance(payload, list)
        or len(payload) != 1
    ):
        raise RuntimeError(
            "Unexpected docker inspect response"
        )

    return payload[0]


def evaluate_guardrails(
    branch: str,
    container: str,
    inspect_data: dict,
) -> dict:
    errors = []

    if branch != "staging":
        errors.append(
            "Git branch must be 'staging'"
        )

    if container != STAGING_DB_CONTAINER:
        errors.append(
            "DB container must equal the fixed "
            "staging canary container"
        )

    if container == PRODUCTION_DB_CONTAINER:
        errors.append(
            "Production DB container is forbidden"
        )

    config = (
        inspect_data.get("Config")
        or {}
    )

    labels = (
        config.get("Labels")
        or {}
    )

    for key, expected in EXPECTED_LABELS.items():
        actual = labels.get(key)

        if actual != expected:
            errors.append(
                f"Container label {key!r} must be "
                f"{expected!r}; got {actual!r}"
            )

    host_config = (
        inspect_data.get("HostConfig")
        or {}
    )

    network_mode = (
        host_config.get(
            "NetworkMode"
        )
    )

    if network_mode != "none":
        errors.append(
            "Staging DB network mode must be 'none'"
        )

    port_bindings = (
        host_config.get(
            "PortBindings"
        )
        or {}
    )

    published_ports = {
        key: value
        for key, value
        in port_bindings.items()
        if value
    }

    if published_ports:
        errors.append(
            "Staging DB must not publish ports"
        )

    state = (
        inspect_data.get("State")
        or {}
    )

    running = bool(
        state.get("Running")
    )

    if not running:
        errors.append(
            "Staging DB container must be running"
        )

    health = (
        (
            state.get("Health")
            or {}
        ).get("Status")
    )

    if health != "healthy":
        errors.append(
            "Staging DB container must be healthy"
        )

    return {
        "guard_version":
            CANARY_GUARD_VERSION,
        "branch":
            branch,
        "db_container":
            container,
        "expected_labels":
            dict(EXPECTED_LABELS),
        "observed_labels": {
            key: labels.get(key)
            for key in EXPECTED_LABELS
        },
        "network_mode":
            network_mode,
        "published_ports":
            published_ports,
        "running":
            running,
        "health":
            health,
        "guard_ok":
            not errors,
        "errors":
            errors,
    }


def verify_runtime(
    repo_root: Path,
) -> dict:
    branch = get_repo_branch(
        repo_root
    )

    inspect_data = (
        inspect_container(
            STAGING_DB_CONTAINER
        )
    )

    result = evaluate_guardrails(
        branch=branch,
        container=STAGING_DB_CONTAINER,
        inspect_data=inspect_data,
    )

    if not result["guard_ok"]:
        raise RuntimeError(
            "Canary guardrail failed: "
            + "; ".join(
                result["errors"]
            )
        )

    return result


def orchestrator_path(
    repo_root: Path,
) -> Path:
    path = (
        repo_root
        / "orchestrate_document_v2.py"
    )

    if not path.is_file():
        raise RuntimeError(
            f"Missing orchestrator: {path}"
        )

    return path


def build_orchestrator_command(
    repo_root: Path,
    python: str,
    source: Path,
    title: str,
    domain: str,
    topic: str,
    document_type: str,
    authority: str,
    jurisdiction: str,
    language: str,
    source_url: str,
    workdir: str,
    write: bool,
) -> list[str]:
    command = [
        python,
        str(
            orchestrator_path(
                repo_root
            )
        ),
        str(source),
        "--title",
        title,
        "--domain",
        domain,
        "--topic",
        topic,
        "--document-type",
        document_type,
        "--authority",
        authority,
        "--jurisdiction",
        jurisdiction,
        "--language",
        language,
        "--db-container",
        STAGING_DB_CONTAINER,
    ]

    if source_url:
        command.extend([
            "--source-url",
            source_url,
        ])

    if workdir:
        command.extend([
            "--workdir",
            workdir,
        ])

    if write:
        command.extend([
            "--write",
            "--confirm-live-write",
        ])
    else:
        command.append(
            "--prepare"
        )

    return command


def require_ingest_args(
    args,
) -> None:
    required = {
        "file":
            args.file,
        "--title":
            args.title,
        "--domain":
            args.domain,
        "--topic":
            args.topic,
        "--document-type":
            args.document_type,
    }

    missing = [
        name
        for name, value
        in required.items()
        if not value
    ]

    if missing:
        raise SystemExit(
            "Missing required canary arguments: "
            + ", ".join(missing)
        )

    if (
        args.write
        and not args.confirm_staging_write
    ):
        raise SystemExit(
            "--write requires "
            "--confirm-staging-write"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only multimodal v2 canary guard. "
            "Locks the DB target to the isolated staging "
            "container and refuses to run outside the "
            "staging Git branch."
        )
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="Canary source document",
    )

    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Verify staging branch/container isolation "
            "without running ingestion"
        ),
    )

    parser.add_argument(
        "--title",
        default="",
    )

    parser.add_argument(
        "--domain",
        default="",
    )

    parser.add_argument(
        "--topic",
        default="",
    )

    parser.add_argument(
        "--document-type",
        default="",
    )

    parser.add_argument(
        "--authority",
        default="",
    )

    parser.add_argument(
        "--jurisdiction",
        default="HK",
    )

    parser.add_argument(
        "--language",
        default="en",
    )

    parser.add_argument(
        "--source-url",
        default="",
    )

    parser.add_argument(
        "--workdir",
        default="",
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write the canary to the isolated staging DB. "
            "Without this option the wrapper runs prepare-only."
        ),
    )

    parser.add_argument(
        "--confirm-staging-write",
        action="store_true",
        help=(
            "Explicit confirmation required with --write"
        ),
    )

    args = parser.parse_args()

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    try:
        guard = verify_runtime(
            repo_root
        )

    except Exception as exc:
        raise SystemExit(
            "CANARY GUARD FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print(
        json.dumps(
            guard,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        "CANARY GUARD: PASS"
    )

    if args.verify_only:
        print(
            "No ingestion command executed."
        )
        return

    require_ingest_args(
        args
    )

    source = (
        Path(args.file)
        .expanduser()
        .resolve()
    )

    if not source.is_file():
        raise SystemExit(
            f"Canary source not found: {source}"
        )

    command = build_orchestrator_command(
        repo_root=repo_root,
        python=sys.executable,
        source=source,
        title=args.title,
        domain=args.domain,
        topic=args.topic,
        document_type=args.document_type,
        authority=args.authority,
        jurisdiction=args.jurisdiction,
        language=args.language,
        source_url=args.source_url,
        workdir=args.workdir,
        write=bool(args.write),
    )

    print()
    print(
        "CANARY MODE:",
        (
            "STAGING WRITE"
            if args.write
            else "PREPARE ONLY"
        ),
    )
    print(
        "LOCKED DB:",
        STAGING_DB_CONTAINER,
    )
    print()

    run_checked(
        command
    )


if __name__ == "__main__":
    main()
