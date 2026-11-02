#!/usr/bin/env python3
"""Offline Staging DB target lock regression. No Docker, SQL or ingestion I/O."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import ingest_manifest_v2 as ingester
import orchestrate_document_v2 as orchestrator
import staging_db_target_guard_v1 as guard
from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    evaluate_guardrails,
)


def registry():
    return {"source_registry_version": 1, "sources": {"SYNTHETIC": {"enabled": True}}}


def invoke_cli(module, flags, db_container=None):
    if module is ingester:
        argv = [
            "ingest_manifest_v2.py", "/tmp/jason-target-lock-nonexistent.json",
            "--title", "synthetic", "--domain", "test",
        ]
    else:
        argv = [
            "orchestrate_document_v2.py", "/tmp/jason-target-lock-nonexistent.pdf",
            "--title", "synthetic", "--domain", "test", "--topic", "test",
            "--document-type", "pdf",
        ]
    argv.extend(flags)
    if db_container is not None:
        argv.extend(["--db-container", db_container])

    with patch.object(sys, "argv", argv), patch.object(
        module.registry_detector, "load_registry", return_value=registry()
    ), patch.object(
        guard, "verify_runtime", return_value={"guard_ok": True}
    ) as runtime, patch.object(
        module, "read_existing_document"
    ) as db_read, patch.object(
        module, "run_checked" if module is orchestrator else "load_chunks"
    ) as file_processing:
        try:
            module.main()
        except (RuntimeError, SystemExit) as exc:
            result = str(exc)
        else:
            raise AssertionError("CLI unexpectedly accepted missing file")

        assert not db_read.called
        assert not file_processing.called
        return result, runtime.call_count


def check_explicit_target_before_any_io():
    assert ingester.DEFAULT_DB_CONTAINER == ""
    assert orchestrator.DEFAULT_DB_CONTAINER == ""

    # Raw write must never infer the historical Production DB.
    for module in (orchestrator, ingester):
        for flags in (["--write", "--synthetic"], ["--write", "--confirm-live-write"]):
            result, checked = invoke_cli(module, flags)
            assert "DB access requires explicit --db-container" in result, result
            assert checked == 0

            for forbidden in (PRODUCTION_DB_CONTAINER, "arbitrary-db"):
                result, checked = invoke_cli(module, flags, forbidden)
                assert "STAGING_DB_TARGET_REFUSED" in result, result
                assert checked == 0

            result, checked = invoke_cli(module, flags, "")
            assert "DB access requires explicit --db-container" in result, result
            assert checked == 0

            result, checked = invoke_cli(module, flags, STAGING_DB_CONTAINER)
            assert "file not found" in result.lower(), result
            assert checked == 1

    # Read-only/prepare operations needing DB must also state the DB target.
    for flags in (["--prepare"],):
        result, checked = invoke_cli(orchestrator, flags)
        assert "DB access requires explicit --db-container" in result
        assert checked == 0
    for flags in (["--check-db"], ["--prepare-write"]):
        result, checked = invoke_cli(ingester, flags)
        assert "DB access requires explicit --db-container" in result
        assert checked == 0

    # Validation/route-only without DB access retains historical behavior.
    for module in (orchestrator, ingester):
        result, checked = invoke_cli(module, [])
        assert "file not found" in result.lower(), result
        assert checked == 0


def check_low_level_sql_boundary():
    with patch.object(guard, "verify_runtime", return_value={"guard_ok": True}) as runtime, patch.object(
        ingester.subprocess, "run",
        return_value=SimpleNamespace(returncode=0, stdout="SYNTHETIC_OK", stderr=""),
    ) as sql_runner:
        for forbidden in (PRODUCTION_DB_CONTAINER, "arbitrary-db", ""):
            try:
                ingester.execute_transaction("SELECT 1;", forbidden)
            except RuntimeError as exc:
                assert "STAGING_DB_TARGET_REFUSED" in str(exc), str(exc)
            else:
                raise AssertionError("direct low-level SQL bypassed target guard")
        assert not sql_runner.called
        assert not runtime.called

        result = ingester.execute_transaction("SELECT 1;", STAGING_DB_CONTAINER)
        assert result == "SYNTHETIC_OK"
        assert runtime.call_count == 1
        assert sql_runner.call_count == 1
        assert STAGING_DB_CONTAINER in sql_runner.call_args.args[0]
        assert PRODUCTION_DB_CONTAINER not in sql_runner.call_args.args[0]


def check_runtime_failure_holds():
    with patch.object(guard, "verify_runtime", side_effect=RuntimeError("bad Git branch")):
        try:
            ingester.execute_transaction("SELECT 1;", STAGING_DB_CONTAINER)
        except RuntimeError as exc:
            assert "bad Git branch" in str(exc)
        else:
            raise AssertionError("runtime identity failure was bypassed")

    valid = {
        "Config": {"Labels": {
            "com.jasonos.environment": "staging",
            "com.jasonos.purpose": "knowledge-canary",
        }},
        "HostConfig": {"NetworkMode": "none", "PortBindings": {}},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }
    assert evaluate_guardrails("staging", STAGING_DB_CONTAINER, valid)["guard_ok"]
    assert not evaluate_guardrails("main", STAGING_DB_CONTAINER, valid)["guard_ok"]
    untrusted = {
        **valid, "State": {"Running": True, "Health": {"Status": "unhealthy"}},
    }
    assert not evaluate_guardrails("staging", STAGING_DB_CONTAINER, untrusted)["guard_ok"]


def main():
    check_explicit_target_before_any_io()
    check_low_level_sql_boundary()
    check_runtime_failure_holds()
    print("STAGING DB TARGET LOCK OFFLINE SYNTHETIC: PASS")
    print("No Docker, SQL, DB, OCR, embeddings or file ingestion executed.")


if __name__ == "__main__":
    main()
