#!/usr/bin/env python3
"""No-network regression for Gate 3D-C metadata-only failure diagnosis."""
import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "hermes_gate3dc_isolated_chat_staging.py"


def module():
    spec = importlib.util.spec_from_file_location("gate3dc_payload_diagnostic", SCRIPT)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def main():
    m = module()
    secret = "SENSITIVE_PRIVATE_SOURCE_TEXT_12345"
    packet = {
        "source_id": "BD_PNAP_APP149",
        "chunks": [{"text": secret}],
        "approved_pdf_sha256": m.APPROVED["BD_PNAP_APP149"],
    }
    wire = json.dumps({"result": json.dumps(packet)})
    wrapped = m.UNTRUSTED_PREFIX + wire + m.UNTRUSTED_SUFFIX
    shape = m.summarize_mcp_tool_result_shape(wrapped)
    assert shape["untrusted_wrapper"] == "exact"
    assert shape["approved_snapshot_shape_reached"] is True
    assert shape["json_decodes"] == 2
    assert secret not in json.dumps(shape)
    assert m.summarize_mcp_tool_result_shape(
        m.UNTRUSTED_PREFIX + "<persisted-output>preview</persisted-output>"
        + m.UNTRUSTED_SUFFIX
    )["persisted_output_marker"] is True
    assert m.summarize_mcp_tool_result_shape(
        "untrusted_tool_result malformed"
    )["untrusted_wrapper"] == "unexpected"
    assert m.summarize_mcp_tool_result_shape(
        json.dumps({"result": {"structuredContent": packet}})
    )["approved_snapshot_shape_reached"] is True
    assert m.summarize_mcp_tool_result_shape(
        json.dumps({"structuredContent": packet})
    )["structured_content_present"] is True
    assert m.summarize_mcp_tool_result_shape("x" * 500001)["state"] == "oversize"
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td)
        with sqlite3.connect(profile / "state.db") as con:
            con.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
                "tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, "
                "content TEXT, active INTEGER)"
            )
            con.execute(
                "INSERT INTO messages VALUES(1,'tool',NULL,'call1','name',?,1)",
                (wrapped,),
            )
        out = m.diagnose_mcp_payload_shape(profile)
        assert out["approved_snapshot_shape_reached"] is True
        assert secret not in json.dumps(out)
        assert m.verify_actual_mcp_dispatch(profile)[0] is False
    print("GATE 3D-C PAYLOAD DIAGNOSTICS OFFLINE: PASS")


if __name__ == "__main__":
    main()
