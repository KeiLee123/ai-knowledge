#!/usr/bin/env python3
"""Gate 3D-D0: deterministic offline fault matrix for the frozen 3D-C contract.

No Docker, network, LLM, credentials, service changes or approved-source writes.
Import the 3D-C checker (without calling main) against synthetic public fixtures.
"""

import copy
import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATE = ROOT / "scripts" / "hermes_gate3dc_isolated_chat_staging.py"
EXPECTED_TOOL = "mcp__jason_os_pnap_canary__read_approved_pnap_source"
ID = "call-approved-001"


def load_gate():
    spec = importlib.util.spec_from_file_location("hermes_gate3dc_for_d0", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_packet(gate):
    return {
        "schema_version": "hermes-approved-snapshot-v0.1",
        "source_id": "BD_PNAP_APP149",
        "environment": "staging",
        "approved_pdf_sha256": gate.APPROVED["BD_PNAP_APP149"],
        "answer": None,
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "current_legal_applicability": "NOT_VERIFIED",
        "chunk_count": 8,
        "chunks": [
            {"id": "P" + str(i), "chunk_id": i,
             "pdf_page_start": 2 + (i - 1) // 3,
             "pdf_page_end": 2 + (i - 1) // 3,
             "text": "PUBLIC_TEST_EVIDENCE_" + str(i)}
            for i in range(1, 9)
        ],
    }


def call(name=EXPECTED_TOOL, args=None, cid=ID):
    if args is None:
        args = {"source_id": "BD_PNAP_APP149"}
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def wrapped(gate, packet, *, nested=False):
    """Replicate the allowed transport only; never forge a new accepted shape."""
    raw = json.dumps({"result": json.dumps(packet, ensure_ascii=False)},
                     ensure_ascii=False)
    if nested:
        return gate.UNTRUSTED_PREFIX + gate.UNTRUSTED_PREFIX + raw + (
            gate.UNTRUSTED_SUFFIX * 2
        )
    return gate.UNTRUSTED_PREFIX + raw + gate.UNTRUSTED_SUFFIX


def write_trace(con, calls, results):
    con.execute("DELETE FROM messages")
    if calls is not None:
        con.execute(
            "INSERT INTO messages "
            "(role, tool_calls, tool_call_id, tool_name, content, active) "
            "VALUES ('assistant', ?, NULL, NULL, NULL, 1)",
            (json.dumps(calls),),
        )
    for tool_id, tool_name, content in results:
        con.execute(
            "INSERT INTO messages "
            "(role, tool_calls, tool_call_id, tool_name, content, active) "
            "VALUES ('tool', NULL, ?, ?, ?, 1)",
            (tool_id, tool_name, content),
        )
    con.commit()


def test_trace_matrix(gate, profile, con, packet):
    success = wrapped(gate, packet)
    failures = []

    def check(label, calls, results, expected):
        write_trace(con, calls, results)
        accepted, reason = gate.verify_actual_mcp_dispatch(profile)
        assert accepted is expected, (label, reason)
        if expected:
            assert reason == "mcp_tool_call_and_result_proven", (label, reason)
        else:
            failures.append(label)

    rows = [(ID, EXPECTED_TOOL, success)]
    for i in range(3):
        check("deterministic_baseline_" + str(i), [call()], rows, True)

    # JSON key ordering is not evidence tampering: full semantic snapshot
    # equality, rather than serialized byte order, must continue to work.
    reordered = {key: packet[key] for key in reversed(list(packet))}
    check("same_full_snapshot_different_json_order", [call()],
          [(ID, EXPECTED_TOOL, wrapped(gate, reordered))], True)

    mutations = {}
    def mutate(label, fn):
        modified = copy.deepcopy(packet)
        fn(modified)
        mutations[label] = modified

    mutate("changed_pdf_sha", lambda p: p.update(approved_pdf_sha256="0" * 64))
    mutate("changed_chunk_text", lambda p: p["chunks"][3].update(text="tampered"))
    mutate("removed_chunk", lambda p: p["chunks"].pop())
    mutate("changed_source_id", lambda p: p.update(source_id="BD_PNAP_APP145"))
    mutate("added_unapproved_metadata", lambda p: p.update(extra="unapproved"))
    mutate("changed_page", lambda p: p["chunks"][2].update(pdf_page_start=99))
    mutate("answer_instead_of_evidence", lambda p: p.update(answer="not-null"))
    for label, changed in mutations.items():
        check(label, [call()], [(ID, EXPECTED_TOOL, wrapped(gate, changed))], False)

    check("missing_assistant_call", None, rows, False)
    check("empty_assistant_tool_calls", [], rows, False)
    check("unapproved_tool_invoked", [call(name="terminal_execute")], rows, False)
    check("wrong_tool_arguments", [call(args={"source_id": "BD_PNAP_APP145"})], rows, False)
    check("unexpected_extra_arguments",
          [call(args={"source_id": "BD_PNAP_APP149", "extra": True})], rows, False)
    check("duplicate_assistant_calls", [call(), call(cid="call-2")], rows, False)
    check("missing_tool_result", [call()], [], False)
    check("mismatched_tool_call_id", [call()],
          [("other-id", EXPECTED_TOOL, success)], False)
    check("mismatched_tool_result_name", [call()],
          [(ID, "other_tool", success)], False)
    check("duplicate_tool_results", [call()], rows + rows, False)
    check("error_result", [call()],
          [(ID, EXPECTED_TOOL, gate.UNTRUSTED_PREFIX
            + json.dumps({"isError": True, "result": json.dumps(packet)})
            + gate.UNTRUSTED_SUFFIX)], False)
    check("nested_untrusted_boundary", [call()],
          [(ID, EXPECTED_TOOL, wrapped(gate, packet, nested=True))], False)
    check("missing_untrusted_suffix", [call()],
          [(ID, EXPECTED_TOOL, success[:-len(gate.UNTRUSTED_SUFFIX)])], False)
    check("forged_untrusted_boundary", [call()],
          [(ID, EXPECTED_TOOL, success.replace(
              'source="' + EXPECTED_TOOL + '"', 'source="impostor"', 1))], False)
    check("persisted_output_not_inline_evidence", [call()],
          [(ID, EXPECTED_TOOL, "<persisted-output>preview</persisted-output>")], False)
    check("truncated_json", [call()],
          [(ID, EXPECTED_TOOL, gate.UNTRUSTED_PREFIX
            + '{"result":' + gate.UNTRUSTED_SUFFIX)], False)

    # Safe diagnostics cannot substitute for the strict proof.
    write_trace(con, [call()],
                [(ID, EXPECTED_TOOL, "<persisted-output>preview</persisted-output>")])
    diagnostics = gate.diagnose_mcp_payload_shape(profile)
    assert diagnostics["persisted_output_marker"] is True
    assert gate.verify_actual_mcp_dispatch(profile)[0] is False

    print("Gate 3D-D0 session fault matrix: PASS ("
          + str(len(failures)) + " fail-closed cases)")


def test_answer_contract(gate):
    good = {
        "source_id": "BD_PNAP_APP149",
        "approved_pdf_sha256": gate.APPROVED["BD_PNAP_APP149"],
        "chunk_count": 8,
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "summary": "PUBLIC TEST SUMMARY — professional review required",
        "pdf_pages": [2, 3, 4],
    }
    assert gate.check_answer(json.dumps(good))[0] is True
    negatives = (
        {"source_id": "BD_PNAP_APP145"},
        {"approved_pdf_sha256": "0" * 64},
        {"chunk_count": 7},
        {"answer_status": "VERIFIED"},
        {"summary": ""},
        {"pdf_pages": []},
        {"pdf_pages": [True]},
        {"pdf_pages": [999]},
    )
    for change in negatives:
        altered = dict(good)
        altered.update(change)
        assert gate.check_answer(json.dumps(altered))[0] is False, change
    assert gate.check_answer("INSUFFICIENT_EVIDENCE")[0] is False
    print("Gate 3D-D0 answer metadata rejection: PASS (" 
          + str(len(negatives) + 1) + " cases)")


def main():
    gate = load_gate()
    with tempfile.TemporaryDirectory(prefix="jason-os-gate3dd0-") as td:
        profile = Path(td)
        snapshots = profile / "snapshots"
        snapshots.mkdir()
        packet = fixture_packet(gate)
        (snapshots / "BD_PNAP_APP149.json").write_text(
            json.dumps(packet, ensure_ascii=False), encoding="utf-8"
        )
        gate.CANARY = profile
        with sqlite3.connect(profile / "state.db") as con:
            con.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
                "tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, "
                "content TEXT, active INTEGER)"
            )
            test_trace_matrix(gate, profile, con, packet)
            test_answer_contract(gate)
    print("HERMES GATE 3D-D0 OFFLINE RELIABILITY: PASS")


if __name__ == "__main__":
    main()
