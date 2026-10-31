#!/usr/bin/env python3
"""No-network Gate 3D-C contract tests. Never start Docker/Hermes/DeepSeek."""
import ast
import importlib.util
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "hermes_gate3dc_isolated_chat_staging.py"
SHELL = ROOT / "scripts" / "hermes_gate3dc_isolated_chat_staging.sh"


def module():
    spec = importlib.util.spec_from_file_location("gate3dc_module", SCRIPT)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def test_scripts_syntax():
    ast.parse(SCRIPT.read_text(encoding="utf-8"))
    r = subprocess.run(["bash", "-n", str(SHELL)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_single_tool_and_no_persistent_config_changes():
    m = module()
    data = m.isolated_config()
    assert data["toolsets"] == ["jason_os_pnap_canary"]
    assert data["tools"] == {"tool_search": {"enabled": "off"}}
    assert list(data["mcp_servers"]) == ["jason_os_pnap_canary"]
    svr = data["mcp_servers"]["jason_os_pnap_canary"]
    assert svr["tools"]["include"] == ["read_approved_pnap_source"]
    assert svr["tools"]["resources"] is False
    assert svr["tools"]["prompts"] is False
    assert svr["command"] == "/usr/bin/env"
    assert svr["args"][0] == "-i"
    assert "JASON_OS_PNAP_CANARY=1" in svr["args"]
    assert "DEEPSEEK_API_KEY" not in json.dumps(data)

    sh = SHELL.read_text()
    src = SCRIPT.read_text()
    for needed in (
        "--preflight", "--run", "/opt/ai-knowledge-staging",
        "git merge-base --is-ancestor", "git status --porcelain",
        "docker inspect", "docker exec -i", "python -",
    ):
        assert needed in sh, needed
    for needed in (
        '"HERMES_HOME": str(profile)', "os.chown(profile, USER_ID, USER_ID)",
        '"/usr/bin/setpriv"', '"--reuid=65534"',
        '"--toolsets", "jason_os_pnap_canary"',
        '"--provider", "deepseek"', '"--max-turns", "4"',
        "DEEPSEEK_API_KEY", "shutil.rmtree(profile)",
        'set_mcp_server_filter(server)',
        'discover_mcp_tools(allowed_mcp_names=selected)',
        'get_tool_names_for_toolset("mcp-" + server)',
        'get_toolset_alias_target(server)',
        'assert names == ["mcp__jason_os_pnap_canary__read_approved_pnap_source"]',
        "MCP trace metadata (names only):",
        "diagnose_mcp_tool_names(profile)",
        'validate_toolset(server)',
        'Non-root Hermes MCP Registry: PASS',
        'tool_search_config.enabled == "off"',
        'assert not assembled.activated',
        'bridge_modified_scope',
        'HERMES MCP REGISTRY: ONE DIRECT APPROVED TOOL (BRIDGE OFF)',
        '"tools": {"tool_search": {"enabled": "off"}}',
        'if MODE == "--preflight":',
        "hashlib.sha256(CONFIG.read_bytes()).hexdigest() == baseline",
    ):
        assert needed in src, needed
    for forbidden in (
        "docker restart", "docker cp", "docker network connect",
        "chmod 755 /opt/data", "chmod 711 /opt/data",
        "mcp_servers.jason_os_pnap_staging",
        "write_text(DOTENV", "write_text(CONFIG",
        "shutil.copyfile(DOTENV", "subprocess.Popen(shell=True",
        '"--toolsets", "mcp-jason_os_pnap_canary"',
        '"tool_search": {"enabled": "auto"}',
        '"tool_search": {"enabled": "on"}',
    ):
        assert forbidden not in sh + src, forbidden


def test_fingerprint_and_page_proof():
    m = module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "snapshots").mkdir()
        approved = {
            "chunks": [
                {"pdf_page_start": 2, "pdf_page_end": 2},
                {"pdf_page_start": 5, "pdf_page_end": 5},
            ],
        }
        (root / "snapshots" / "BD_PNAP_APP149.json").write_text(json.dumps(approved))
        m.CANARY = root
        answer = {
            "source_id": "BD_PNAP_APP149",
            "approved_pdf_sha256": m.APPROVED["BD_PNAP_APP149"],
            "chunk_count": 8,
            "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
            "summary": "來源描述有關暫委授權簽署人的安排，需要核實原文。",
            "pdf_pages": [2],
        }
        assert m.check_answer(json.dumps(answer, ensure_ascii=False))[0] is True

        for changed in (
            {"approved_pdf_sha256": "0" * 64},
            {"chunk_count": 7},
            {"answer_status": "VERIFIED"},
            {"pdf_pages": [10]},
            {"summary": ""},
        ):
            assert not m.check_answer(json.dumps({**answer, **changed}))[0], changed
        assert not m.check_answer("Unverified answer")[0]



def test_known_hermes_notices_and_failclosed_json():
    m = module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "snapshots").mkdir()
        (root / "snapshots" / "BD_PNAP_APP149.json").write_text(
            json.dumps({"chunks": [
                {"pdf_page_start": 1, "pdf_page_end": 5},
            ]})
        )
        m.CANARY = root
        answer = {
            "source_id": "BD_PNAP_APP149",
            "approved_pdf_sha256": m.APPROVED["BD_PNAP_APP149"],
            "chunk_count": 8,
            "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
            "summary": "根據來源摘要；目前法律適用性未經核實。",
            "pdf_pages": [1, 2, 3, 4, 5],
        }
        raw = json.dumps(answer, ensure_ascii=False, indent=2)
        notices = (
            "⚠️  Normalized model 'deepseek-chat' to 'deepseek-flash' for deepseek.\n"
            "  ⚠ tirith security scanner enabled but not available — command scanning will use pattern matching only\n"
        )
        assert m.extract_model_json(notices + raw) == answer
        assert m.check_answer(notices + raw)[0] is True
        for bad in (
            "Warning: Unknown toolsets: mcp-jason_os_pnap_canary\n" + raw,
            "I'll call the tool\n" + raw,
            raw + "\n" + raw,
            notices + notices + raw,
            "⚠ unexpected security warning\n" + raw,
            "garbage {" + raw,
        ):
            assert not m.check_answer(bad)[0], bad[:40]


def test_real_session_db_mcp_tool_dispatch():
    m = module()
    exact_name = "mcp__jason_os_pnap_canary__read_approved_pnap_source"
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td)
        db = profile / "state.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
            "tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, content TEXT, active INTEGER)"
        )

        def record(name=exact_name, source="BD_PNAP_APP149", tool_result=True,
                   source_sha=None):
            con.execute("DELETE FROM messages")
            call = [{
                "id": "call-approved-001",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps({"source_id": source}),
                }
            }]
            con.execute(
                "INSERT INTO messages VALUES (1, 'assistant', ?, NULL, NULL, NULL, 1)",
                (json.dumps(call),),
            )
            if tool_result:
                packet = {
                    "source_id": "BD_PNAP_APP149",
                    "approved_pdf_sha256": source_sha or m.APPROVED["BD_PNAP_APP149"],
                    "chunk_count": 8, "answer": None,
                    "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
                    "chunks": [{"id": "P" + str(i)} for i in range(1, 9)],
                }
                con.execute(
                    "INSERT INTO messages VALUES "
                    "(2, 'tool', NULL, 'call-approved-001', ?, ?, 1)",
                    (name, json.dumps(packet)),
                )
            con.commit()

        assert m.verify_actual_mcp_dispatch(profile) == (False, "no_unique_approved_mcp_call")
        record()
        assert m.verify_actual_mcp_dispatch(profile) == (
            True, "mcp_tool_call_and_result_proven",
        )
        record(tool_result=False)
        assert not m.verify_actual_mcp_dispatch(profile)[0]
        record(name="terminal_execute")
        assert not m.verify_actual_mcp_dispatch(profile)[0]
        record(source="BD_PNAP_APP145")
        assert not m.verify_actual_mcp_dispatch(profile)[0]
        record(source_sha="0" * 64)
        assert not m.verify_actual_mcp_dispatch(profile)[0]
        con.close()


def test_sanitized_tool_trace_metadata_diagnostic_only():
    m = module()
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td)
        con = sqlite3.connect(profile / "state.db")
        con.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
            "tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, content TEXT, active INTEGER)"
        )
        tool_name = "mcp__jason_os_pnap_canary__read_approved_pnap_source"
        calls = [
            {
                "id": "tool-call-1",
                "function": {
                    "name": tool_name,
                    "arguments": '{"source_id":"BD_PNAP_APP149"}',
                },
            },
            {
                "id": "tool-call-2",
                "function": {
                    "name": "other_tool",
                    "arguments": "sensitive private data must not be printed",
                },
            },
        ]
        con.execute(
            "INSERT INTO messages VALUES (1, 'assistant', ?, NULL, NULL, NULL, 1)",
            (json.dumps(calls),),
        )
        con.execute(
            "INSERT INTO messages VALUES (2, 'tool', NULL, 'tool-call-1', ?, ?, 1)",
            (tool_name, "sensitive tool contents must not be printed"),
        )
        con.commit()
        result = m.diagnose_mcp_tool_names(profile)
        assert result["assistant_tool_calls"] == 2
        assert result["assistant_names"] == [tool_name, "other_tool"]
        assert result["result_names"] == [tool_name]
        assert "sensitive" not in json.dumps(result)
        assert m.verify_actual_mcp_dispatch(profile)[0] is False
        con.close()


def main():
    for t in (
        test_scripts_syntax,
        test_single_tool_and_no_persistent_config_changes,
        test_fingerprint_and_page_proof,
        test_known_hermes_notices_and_failclosed_json,
        test_real_session_db_mcp_tool_dispatch,
        test_sanitized_tool_trace_metadata_diagnostic_only,
    ):
        t()
        print(t.__name__ + ": PASS")
    print("HERMES GATE 3D-C ISOLATED CHAT OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
