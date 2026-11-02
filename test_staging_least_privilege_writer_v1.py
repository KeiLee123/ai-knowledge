#!/usr/bin/env python3
"""Offline Staging writer role regression: no Docker, PostgreSQL or ingestion."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ingest_manifest_v2 as ingester
import orchestrate_document_v2 as orchestrator
import staging_db_target_guard_v1 as guard
from run_multimodal_canary_v2 import (
    STAGING_DB_CONTAINER,
    PRODUCTION_DB_CONTAINER,
    build_orchestrator_command,
)
from write_prepared_canary_v2 import build_prepared_write_command


ROLE = guard.STAGING_DB_WRITER_ROLE


def refused(call, reason):
    try:
        call()
    except (RuntimeError, SystemExit) as exc:
        assert reason in str(exc), str(exc)
    else:
        raise AssertionError("Expected fail-closed refusal: " + reason)


def test_role_identity_and_privileges():
    assert ROLE != "ai_knowledge"
    for bad in ("", "ai_knowledge", "postgres", "arbitrary_role"):
        refused(
            lambda bad=bad: guard.enforce_staging_writer_role(bad),
            "STAGING_DB_ROLE_REFUSED",
        )

    # Simulate psql output: no actual subprocess, Docker, or DB connection.
    ok = SimpleNamespace(returncode=0, stdout="STAGING_ROLE_OK\n", stderr="")
    with patch("subprocess.run", return_value=ok) as runner:
        guard.verify_staging_writer_role(STAGING_DB_CONTAINER, ROLE)
        command = runner.call_args.args[0]
        assert command[0:3] == ["docker", "exec", "-i"]
        assert command[3] == STAGING_DB_CONTAINER
        assert command[command.index("-U") + 1] == ROLE
        assert command[command.index("-d") + 1] == "ai_knowledge"
        sql = command[command.index("-c") + 1]
        for marker in (
            "current_user", "rolsuper", "rolcreatedb", "rolcreaterole",
            "rolreplication", "rolbypassrls", "rolcanlogin",
            "pg_has_role", "STAGING_ROLE_OK",
        ):
            assert marker in sql, marker
        assert "INSERT" not in sql and "UPDATE" not in sql

    for simulated in (
        SimpleNamespace(returncode=0, stdout="STAGING_ROLE_REFUSED\n", stderr=""),
        SimpleNamespace(returncode=2, stdout="", stderr="role does not exist"),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ):
        with patch("subprocess.run", return_value=simulated):
            refused(
                lambda: guard.verify_staging_writer_role(STAGING_DB_CONTAINER, ROLE),
                "STAGING_DB_ROLE_PRIVILEGE_REFUSED",
            )


def test_low_level_sql_write_boundary():
    assert ingester.DEFAULT_DB_ROLE == ""
    fake = SimpleNamespace(returncode=0, stdout="OFFLINE_SYNTHETIC_OK", stderr="")
    with patch.object(ingester, "enforce_staging_write_target") as target, patch.object(
        ingester, "verify_staging_writer_role"
    ) as privileged, patch.object(ingester.subprocess, "run", return_value=fake) as sql:
        for bad in ("", "ai_knowledge", "postgres", "not-the-writer"):
            refused(
                lambda bad=bad: ingester.execute_transaction(
                    "SELECT 1;", STAGING_DB_CONTAINER, bad
                ),
                "STAGING_DB_ROLE_REFUSED",
            )
        assert not sql.called and not privileged.called

        result = ingester.execute_transaction("SELECT 1;", STAGING_DB_CONTAINER, ROLE)
        assert result == "OFFLINE_SYNTHETIC_OK"
        assert target.call_count == 5
        assert privileged.call_count == 1
        cmd = sql.call_args.args[0]
        assert cmd[cmd.index("-U") + 1] == ROLE
        assert cmd[cmd.index("-d") + 1] == "ai_knowledge"
        assert PRODUCTION_DB_CONTAINER not in cmd

    with patch.object(ingester, "enforce_staging_write_target"), patch.object(
        ingester, "verify_staging_writer_role", side_effect=RuntimeError("privileged")
    ), patch.object(ingester.subprocess, "run") as sql:
        refused(
            lambda: ingester.execute_transaction("SELECT 1;", STAGING_DB_CONTAINER, ROLE),
            "privileged",
        )
        assert not sql.called


def test_prewrite_role_boundary():
    for module in (ingester, orchestrator):
        if module is ingester:
            argv = [
                "ingest_manifest_v2.py", "/tmp/no-such-staging-role-chunks.json",
                "--title", "synthetic", "--domain", "test",
            ]
        else:
            argv = [
                "orchestrate_document_v2.py", "/tmp/no-such-staging-role.pdf",
                "--title", "synthetic", "--domain", "test",
                "--topic", "test", "--document-type", "pdf",
            ]
        argv += ["--write", "--synthetic", "--db-container", STAGING_DB_CONTAINER]

        for role_args in ([], ["--db-role", "ai_knowledge"], ["--db-role", "postgres"]):
            with patch.object(sys, "argv", argv + role_args), patch.object(
                module.registry_detector, "load_registry",
                return_value={"source_registry_version": 1, "sources": {}},
            ), patch.object(module, "enforce_staging_write_target") as target, patch.object(
                module, "verify_staging_writer_role"
            ) as checked, patch.object(module, "read_existing_document") as duplicate, patch.object(
                module, "load_chunks" if module is ingester else "run_checked"
            ) as processing:
                refused(module.main, "STAGING_DB_ROLE_REFUSED")
                assert target.called
                assert not checked.called
                assert not duplicate.called
                assert not processing.called

        with patch.object(sys, "argv", argv + ["--db-role", ROLE]), patch.object(
            module.registry_detector, "load_registry",
            return_value={"source_registry_version": 1, "sources": {}},
        ), patch.object(module, "enforce_staging_write_target"), patch.object(
            module, "verify_staging_writer_role"
        ) as checked, patch.object(
            module, "read_existing_document"
        ) as duplicate, patch.object(
            module, "load_chunks" if module is ingester else "run_checked"
        ) as processing:
            refused(module.main, "file not found")
            assert checked.call_count == 1
            assert not duplicate.called
            assert not processing.called


def test_db_reads_and_existing_canary_contract():
    response = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch.object(ingester.subprocess, "run", return_value=response) as process:
        ingester.read_existing_document("a" * 64, STAGING_DB_CONTAINER, ROLE)
        assert process.call_args.args[0][
            process.call_args.args[0].index("-U") + 1
        ] == ROLE
        ingester.run_db_query("SELECT 1;", STAGING_DB_CONTAINER, ROLE)
        assert process.call_args.args[0][
            process.call_args.args[0].index("-U") + 1
        ] == ROLE

    root = Path(__file__).resolve().parent
    command = build_orchestrator_command(
        repo_root=root, python="/venv/bin/python",
        source=Path("/tmp/no-such.pdf"), title="synthetic", domain="test",
        topic="test", document_type="pdf", authority="", jurisdiction="HK",
        language="en", source_url="", workdir="", write=True,
    )
    assert command[command.index("--db-role") + 1] == ROLE
    assert command[command.index("--db-container") + 1] == STAGING_DB_CONTAINER

    prepared = build_prepared_write_command(
        repo_root=root, python="/venv/bin/python",
        chunks_path=Path("/tmp/no-such-prepared.json"), title="synthetic",
        domain="test", topic="test", document_type="pdf", authority="",
        jurisdiction="HK", language="en", source_url="",
    )
    assert prepared[prepared.index("--db-role") + 1] == ROLE
    assert prepared[prepared.index("--db-container") + 1] == STAGING_DB_CONTAINER
    assert "--check-db" in prepared and "--write" in prepared


def main():
    test_role_identity_and_privileges()
    test_low_level_sql_write_boundary()
    test_prewrite_role_boundary()
    test_db_reads_and_existing_canary_contract()
    print("STAGING LEAST-PRIVILEGE WRITER OFFLINE: PASS")
    print("No live Docker, SQL, DB, embedding or ingestion executed.")


if __name__ == "__main__":
    main()
