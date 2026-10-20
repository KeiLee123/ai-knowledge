#!/usr/bin/env python3

from pathlib import Path

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    build_orchestrator_command,
    evaluate_guardrails,
)


def healthy_staging_inspect():
    return {
        "Config": {
            "Labels": {
                "com.jasonos.environment":
                    "staging",
                "com.jasonos.purpose":
                    "knowledge-canary",
            }
        },
        "HostConfig": {
            "NetworkMode": "none",
            "PortBindings": {},
        },
        "State": {
            "Running": True,
            "Health": {
                "Status": "healthy",
            },
        },
    }


def assert_guard_accepts_staging():
    result = evaluate_guardrails(
        branch="staging",
        container=STAGING_DB_CONTAINER,
        inspect_data=healthy_staging_inspect(),
    )

    assert result["guard_ok"] is True
    assert result["errors"] == []


def assert_guard_rejects_main_branch():
    result = evaluate_guardrails(
        branch="main",
        container=STAGING_DB_CONTAINER,
        inspect_data=healthy_staging_inspect(),
    )

    assert result["guard_ok"] is False
    assert any(
        "branch"
        in error.lower()
        for error in result["errors"]
    )


def assert_guard_rejects_production_db():
    result = evaluate_guardrails(
        branch="staging",
        container=PRODUCTION_DB_CONTAINER,
        inspect_data=healthy_staging_inspect(),
    )

    assert result["guard_ok"] is False
    assert any(
        "production"
        in error.lower()
        or "fixed staging"
        in error.lower()
        for error in result["errors"]
    )


def assert_guard_rejects_network_or_ports():
    inspect_data = healthy_staging_inspect()

    inspect_data["HostConfig"] = {
        "NetworkMode": "bridge",
        "PortBindings": {
            "5432/tcp": [
                {
                    "HostIp": "0.0.0.0",
                    "HostPort": "5432",
                }
            ]
        },
    }

    result = evaluate_guardrails(
        branch="staging",
        container=STAGING_DB_CONTAINER,
        inspect_data=inspect_data,
    )

    assert result["guard_ok"] is False
    assert any(
        "network mode"
        in error.lower()
        for error in result["errors"]
    )
    assert any(
        "publish ports"
        in error.lower()
        for error in result["errors"]
    )


def assert_command_locks_staging_db():
    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    command = build_orchestrator_command(
        repo_root=repo_root,
        python="/venv/bin/python",
        source=Path("/tmp/example.pdf"),
        title="Example",
        domain="test",
        topic="canary",
        document_type="pdf",
        authority="",
        jurisdiction="HK",
        language="en",
        source_url="",
        workdir="/tmp/work",
        write=True,
    )

    assert "--db-container" in command

    index = command.index(
        "--db-container"
    )

    assert command[
        index + 1
    ] == STAGING_DB_CONTAINER

    assert PRODUCTION_DB_CONTAINER not in command
    assert "--write" in command
    assert "--confirm-live-write" in command


def main():
    assert_guard_accepts_staging()
    assert_guard_rejects_main_branch()
    assert_guard_rejects_production_db()
    assert_guard_rejects_network_or_ports()
    assert_command_locks_staging_db()

    print(
        "Multimodal canary guard test PASS"
    )
    print(
        "Staging branch lock: PASS"
    )
    print(
        "Production DB rejection: PASS"
    )
    print(
        "Network/port isolation guard: PASS"
    )
    print(
        "Fixed staging DB command: PASS"
    )


if __name__ == "__main__":
    main()
