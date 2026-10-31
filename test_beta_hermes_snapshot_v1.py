#!/usr/bin/env python3
"""Offline exporter + consumer and real in-memory MCP protocol contracts."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from mcp import Client

import beta_hermes_snapshot_export_v1 as ex
import beta_hermes_mcp_snapshot_stdio_v1 as rd
from beta_ask_staging_v1 import BetaRefused


def raw_row(chunk=121, text="Authorized Signatory paragraph 6"):
    return {
        "chunk_id": chunk, "page_start": 2, "page_end": 2,
        "evidence_origin": "native_text", "evidence_tier": "primary",
        "retrieval_role": "text-primary", "text": text,
    }


def snapshot():
    return {
        "schema_version": rd.VERSION,
        "environment": "staging",
        "source_id": "BD_PNAP_APP149",
        "official_title": "Temporary AS",
        "official_pdf_url": rd.APPROVED["BD_PNAP_APP149"]["url"],
        "approved_pdf_sha256": rd.APPROVED["BD_PNAP_APP149"]["sha256"],
        "revision_date": "NOT_VERIFIED",
        "current_legal_applicability": "NOT_VERIFIED",
        "read_only_source": True,
        "answer": None,
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "chunk_count": 1,
        "chunks": [{
            "id": "P1",
            "chunk_id": 121,
            "pdf_page_start": 2,
            "pdf_page_end": 2,
            "text": "Authorized Signatory paragraph 6",
        }],
    }


def expect_denied(call, exception):
    try:
        call()
    except exception:
        return
    raise AssertionError("Unsafe snapshot accepted")


def test_export_validation():
    result = ex.validate_all_chunks([raw_row()], 1)
    assert result[0]["chunk_id"] == 121
    assert result[0]["id"] == "P1"
    assert result[0]["pdf_page_start"] == 2
    assert result[0]["text"] == "Authorized Signatory paragraph 6"
    expect_denied(lambda: ex.validate_all_chunks([], 1), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([raw_row()], 2), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([raw_row(), raw_row()], 2), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([{**raw_row(), "page_start": 0}], 1), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([{**raw_row(), "evidence_tier": "supplementary"}], 1), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([{**raw_row(), "text": ""}], 1), BetaRefused)
    expect_denied(lambda: ex.validate_all_chunks([{**raw_row(), "text": "x" * (ex.MAX_TEXT_CHARS + 1)}], 1), BetaRefused)


def test_sql_checksum_only_and_select():
    stmt = ex.build_all_chunks_sql("A" * 64)
    assert "SELECT" in stmt
    assert "JOIN documents" in stmt
    assert "a" * 64 in stmt
    assert "INSERT " not in stmt
    assert "DELETE " not in stmt
    expect_denied(lambda: ex.build_all_chunks_sql("abc'; DROP TABLE chunks;--"), RuntimeError)


def test_export_end_to_end_without_db():
    source = {
        "title": "Temporary AS",
        "canonical_source": "Current/APP/APP149.pdf",
        "checksum": rd.APPROVED["BD_PNAP_APP149"]["sha256"],
        "official_url": rd.APPROVED["BD_PNAP_APP149"]["url"],
    }
    with patch.object(ex, "check_checkout"), \
         patch.object(ex, "approved_source", return_value=source), \
         patch.object(ex, "validate_integrity", return_value={"chunk_count": 1}), \
         patch.object(ex, "run_staging_query",
                      side_effect=['{"document_count":1}', json.dumps([raw_row()])]):
        out = ex.build_snapshot("BD_PNAP_APP149")
        assert out["read_only_source"] is True
        assert out["answer"] is None
        assert out["chunk_count"] == 1
        assert out["chunks"][0]["text"] == raw_row()["text"]
    expect_denied(lambda: ex.build_snapshot("BD_PNAP_APP999"), BetaRefused)


def test_snapshot_reader_and_tamper_refusals():
    with tempfile.TemporaryDirectory() as folder:
        p = Path(folder) / "BD_PNAP_APP149.json"
        base = snapshot()
        p.write_text(json.dumps(base), encoding="utf-8")
        assert rd.validated_snapshot("BD_PNAP_APP149", Path(folder)) == base

        altered = [
            {"approved_pdf_sha256": "0" * 64},
            {"source_id": "BD_PNAP_APP145"},
            {"official_pdf_url": "https://evil.example.org/APP149.pdf"},
            {"answer": "hallucinated"},
            {"current_legal_applicability": "CURRENT"},
            {"chunk_count": 2},
            {"chunks": []},
            {"chunks": [{**base["chunks"][0], "text": ""}]},
            {"chunks": [{**base["chunks"][0], "pdf_page_start": 0}]},
            {"chunks": [{**base["chunks"][0], "id": "S99"}]},
        ]
        for mutation in altered:
            p.write_text(json.dumps({**base, **mutation}), encoding="utf-8")
            expect_denied(
                lambda: rd.validated_snapshot("BD_PNAP_APP149", Path(folder)),
                rd.SnapshotRefused,
            )
        expect_denied(
            lambda: rd.validated_snapshot("BD_PNAP_APP999", Path(folder)),
            rd.SnapshotRefused,
        )
        p.unlink()
        expect_denied(
            lambda: rd.validated_snapshot("BD_PNAP_APP149", Path(folder)),
            rd.SnapshotRefused,
        )


async def test_true_mcp_tool_without_db_or_docker():
    with patch.object(rd, "validated_snapshot", return_value=snapshot()) as mocked:
        async with Client(rd.mcp) as client:
            listed = await client.list_tools()
            assert len(listed.tools) == 1
            assert listed.tools[0].name == rd.TOOL
            assert listed.tools[0].annotations.read_only_hint is True
            result = await client.call_tool(
                rd.TOOL, {"source_id": "BD_PNAP_APP149"}
            )
            assert result.is_error is False
            result_text = (
                json.dumps(result.structured_content, ensure_ascii=False)
                + " "
                + " ".join(getattr(item, "text", "") for item in result.content)
            )
            assert "BD_PNAP_APP149" in result_text
            assert "Authorized Signatory paragraph 6" in result_text
            assert "NOT_VERIFIED" in result_text
            mocked.assert_called_once_with("BD_PNAP_APP149")


async def test_mcp_refuses_without_exposing_error():
    with patch.object(rd, "validated_snapshot",
                      side_effect=OSError("secret pathname in host")):
        async with Client(rd.mcp) as client:
            result = await client.call_tool(
                rd.TOOL, {"source_id": "BD_PNAP_APP149"}
            )
            assert result.is_error is False
            result_text = (
                json.dumps(result.structured_content)
                + " "
                + " ".join(getattr(item, "text", "") for item in result.content)
            )
            assert "REFUSED" in result_text
            assert "secret pathname" not in result_text


def test_hermes_persistent_release_root_fixed():
    # This exact path is a narrow root-owned release within the existing
    # /opt/data mount. It must NOT be called a Docker read-only mount.
    assert str(rd.ROOT) == "/opt/data/jason-os-pnap-staging/snapshots"
    assert rd.ROOT.is_absolute()
    assert ".." not in rd.ROOT.parts


def test_explicit_canary_mode_changes_only_fixed_source_root():
    code = (
        "import beta_hermes_mcp_snapshot_stdio_v1 as m; "
        "assert str(m.ROOT) == '/tmp/jason-os-pnap-canary/snapshots'; "
        "assert str(m.PERSISTENT_ROOT) == '/opt/data/jason-os-pnap-staging/snapshots'"
    )
    env = {**os.environ, "JASON_OS_PNAP_CANARY": "1"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_consumer_no_privileged_dependency():
    text = Path(rd.__file__).read_text(encoding="utf-8")
    for bad in (
        "import subprocess", "docker exec", "docker.sock", "psql",
        "run_staging_query", "requests.post(", "urllib.request",
        "JASON_BETA_LLM_API_KEY", "API_SERVER_KEY",
        "0.0.0.0", "streamable-http",
    ):
        assert bad not in text, bad


def main():
    for name, fn in (
        ("test_export_validation", test_export_validation),
        ("test_sql_checksum_only_and_select", test_sql_checksum_only_and_select),
        ("test_export_end_to_end_without_db", test_export_end_to_end_without_db),
        ("test_snapshot_reader_and_tamper_refusals", test_snapshot_reader_and_tamper_refusals),
        ("test_hermes_persistent_release_root_fixed", test_hermes_persistent_release_root_fixed),
        ("test_explicit_canary_mode_changes_only_fixed_source_root", test_explicit_canary_mode_changes_only_fixed_source_root),
        ("test_consumer_no_privileged_dependency", test_consumer_no_privileged_dependency),
    ):
        fn()
        print(name + ": PASS")
    asyncio.run(test_true_mcp_tool_without_db_or_docker())
    print("test_true_mcp_tool_without_db_or_docker: PASS")
    asyncio.run(test_mcp_refuses_without_exposing_error())
    print("test_mcp_refuses_without_exposing_error: PASS")
    print("HERMES OFFLINE SNAPSHOT CONTRACT: PASS")


if __name__ == "__main__":
    main()
