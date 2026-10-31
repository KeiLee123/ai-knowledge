#!/usr/bin/env python3
"""No-network Gate 3D-C contract tests. Never start Docker/Hermes/DeepSeek."""
import ast
import importlib.util
import json
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
        'validate_toolset(server)',
        'Non-root Hermes MCP Registry: PASS',
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


def main():
    for t in (
        test_scripts_syntax,
        test_single_tool_and_no_persistent_config_changes,
        test_fingerprint_and_page_proof,
    ):
        t()
        print(t.__name__ + ": PASS")
    print("HERMES GATE 3D-C ISOLATED CHAT OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
