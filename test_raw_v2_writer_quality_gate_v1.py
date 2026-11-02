#!/usr/bin/env python3
"""Offline raw v2 --write entrypoint boundary regression: no DB, OCR or network."""
import sys
from unittest.mock import patch

import ingest_manifest_v2 as ingester
import orchestrate_document_v2 as orchestrator
from pre_writer_document_quality_gate_v1 import (
    DocumentQualityHold,
    enforce_unattributed_raw_v2_write,
)
from staging_db_target_guard_v1 import STAGING_DB_WRITER_ROLE


HOLD = "QUALITY_GATE_UNATTRIBUTABLE_RAW_V2_WRITE_AUTO_HOLD"


def registry(enabled):
    return {
        "source_registry_version": 1,
        "sources": {
            "SYNTHETIC_SOURCE": {
                "document_quality_gate": {"enabled": enabled},
            },
        },
    }


def test_shared_contract():
    assert (
        enforce_unattributed_raw_v2_write(registry(False))
        == "QUALITY_GATE_RAW_V2_UNGATED_REGISTRY"
    )
    try:
        enforce_unattributed_raw_v2_write(registry(True))
    except DocumentQualityHold as exc:
        assert str(exc) == HOLD
    else:
        raise AssertionError("enabled policy did not hold")

    broken = registry(False)
    broken["sources"]["SYNTHETIC_SOURCE"]["document_quality_gate"]["enabled"] = "true"
    try:
        enforce_unattributed_raw_v2_write(broken)
    except DocumentQualityHold as exc:
        assert str(exc) == "QUALITY_GATE_POLICY_INVALID"
    else:
        raise AssertionError("malformed policy did not fail closed")


def test_orchestrator(write_flags, enabled):
    argv = [
        "orchestrate_document_v2.py", "/tmp/raw-v2-no-such-source-guard.pdf",
        "--title", "synthetic", "--domain", "test", "--topic", "test",
        "--document-type", "pdf", *write_flags,
        *(['--db-container', 'jason-os-knowledge-db-staging'] if any(x in write_flags for x in ('--write', '--prepare')) else []),
        *(['--db-role', STAGING_DB_WRITER_ROLE] if '--write' in write_flags else []),
    ]
    with patch.object(sys, "argv", argv), patch.object(
        orchestrator.registry_detector, "load_registry",
        return_value=registry(enabled),
    ) as read_registry, patch.object(
        orchestrator, "run_checked",
    ) as run_command, patch.object(
        orchestrator, "enforce_staging_write_target",
    ) as db_target, patch.object(
        orchestrator, "verify_staging_writer_role",
    ) as writer_check, patch.object(
        orchestrator, "write_state",
    ) as write_state, patch.object(
        orchestrator, "read_existing_document",
    ) as db_read:
        try:
            orchestrator.main()
        except (SystemExit, DocumentQualityHold) as exc:
            message = str(exc)
        else:
            raise AssertionError("orchestrator unexpectedly accepted missing file")
        if "--write" in write_flags and enabled:
            assert message == HOLD, message
            assert read_registry.called
        else:
            assert "Source file not found" in message, message
            assert read_registry.called is ("--write" in write_flags)
        assert db_target.called is ("--write" in write_flags and not enabled)
        assert writer_check.called is ("--write" in write_flags and not enabled)
        assert not run_command.called
        assert not write_state.called
        assert not db_read.called


def test_manifest(write_flags, enabled):
    argv = [
        "ingest_manifest_v2.py", "/tmp/raw-v2-no-such-chunks-guard.json",
        "--title", "synthetic", "--domain", "test", *write_flags,
        *(['--db-container', 'jason-os-knowledge-db-staging'] if any(x in write_flags for x in ('--write', '--prepare-write')) else []),
        *(['--db-role', STAGING_DB_WRITER_ROLE] if '--write' in write_flags else []),
    ]
    with patch.object(sys, "argv", argv), patch.object(
        ingester.registry_detector, "load_registry",
        return_value=registry(enabled),
    ) as read_registry, patch.object(
        ingester, "enforce_staging_write_target",
    ) as db_target, patch.object(
        ingester, "verify_staging_writer_role",
    ) as writer_check, patch.object(
        ingester, "load_chunks",
    ) as load_chunks, patch.object(
        ingester, "read_existing_document",
    ) as db_read, patch.object(
        ingester, "precompute_embeddings",
    ) as embeddings, patch.object(
        ingester, "execute_transaction",
    ) as sql_write:
        try:
            ingester.main()
        except (SystemExit, DocumentQualityHold) as exc:
            message = str(exc)
        else:
            raise AssertionError("manifest ingester unexpectedly accepted missing file")
        if "--write" in write_flags and enabled:
            assert message == HOLD, message
            assert read_registry.called
        else:
            assert "Chunks file not found" in message, message
            assert read_registry.called is ("--write" in write_flags)
        assert db_target.called is ("--write" in write_flags and not enabled)
        assert writer_check.called is ("--write" in write_flags and not enabled)
        assert not load_chunks.called
        assert not db_read.called
        assert not embeddings.called
        assert not sql_write.called


def test_loader_failure_is_not_bypassed():
    for module, args in (
        (orchestrator, [
            "orchestrate_document_v2.py", "/tmp/no-source.pdf",
            "--title", "t", "--domain", "d", "--topic", "t",
            "--document-type", "pdf", "--write", "--synthetic",
        ]),
        (ingester, [
            "ingest_manifest_v2.py", "/tmp/no-chunks.json",
            "--title", "t", "--domain", "d", "--write", "--synthetic",
        ]),
    ):
        with patch.object(sys, "argv", args), patch.object(
            module.registry_detector, "load_registry",
            side_effect=ValueError("invalid registry"),
        ), patch.object(module, "read_existing_document") as db_read:
            try:
                module.main()
            except ValueError as exc:
                assert str(exc) == "invalid registry"
            else:
                raise AssertionError("failed registry unexpectedly allowed write")
            assert not db_read.called


def main():
    test_shared_contract()
    for flags in (
        ["--write", "--synthetic"],
        ["--write", "--confirm-live-write"],
    ):
        test_orchestrator(flags, True)
        test_orchestrator(flags, False)
        test_manifest(flags, True)
        test_manifest(flags, False)
    for non_write in ([], ["--prepare"]):
        test_orchestrator(non_write, True)
    for non_write in ([], ["--prepare-write"]):
        test_manifest(non_write, True)
    test_loader_failure_is_not_bypassed()
    print("RAW V2 ORCHESTRATOR + MANIFEST QUALITY-GATE SYNTHETIC: PASS")
    print("No DB, file ingest, OCR, embedding, or network operation executed.")


if __name__ == "__main__":
    main()
