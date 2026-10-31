#!/usr/bin/env python3
"""Offline assertions for no-provider Hermes MCP discovery diagnostic."""
import ast
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts/hermes_gate3dc_mcp_discovery_staging.py"
SHELL = ROOT / "scripts/hermes_gate3dc_mcp_discovery_staging.sh"


def test_syntax():
    ast.parse(SCRIPT.read_text(encoding="utf-8"))
    check = subprocess.run(["bash", "-n", str(SHELL)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_isolated_config():
    spec = importlib.util.spec_from_file_location("mcp_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.diagnostic_config()
    assert cfg["toolsets"] == ["mcp-jason_os_pnap_canary"]
    assert list(cfg["mcp_servers"]) == ["jason_os_pnap_canary"]
    server = cfg["mcp_servers"]["jason_os_pnap_canary"]
    assert server["command"] == "/usr/bin/env"
    assert server["args"][0] == "-i"
    assert "JASON_OS_PNAP_CANARY=1" in server["args"]
    assert server["tools"]["include"] == ["read_approved_pnap_source"]
    assert server["tools"]["resources"] is False
    assert server["tools"]["prompts"] is False
    assert "DEEPSEEK" not in str(cfg)
    assert "[REDACTED]" in mod.clean_display("token=secret123456")
    assert "secret123456" not in mod.clean_display("token=secret123456")
    assert "[REDACTED_KEY]" in mod.clean_display("sk-secret1234567890")


def test_no_llm_and_no_live_changes():
    s = SCRIPT.read_text(encoding="utf-8")
    sh = SHELL.read_text(encoding="utf-8")
    for needle in (
        "mcp\", \"test", "config\", \"get", "HERMES_HOME",
        "setpriv", "--reuid=65534", "shutil.rmtree(folder)",
        "hashlib.sha256(LIVE_CONFIG.read_bytes()).hexdigest() == before",
        "CANARY", "DISCOVERY AUDIT COMPLETE",
    ):
        assert needle in s, needle
    for forbidden in (
        "DEEPSEEK_API_KEY", "chat\", \"-q", "agent_question",
        "docker restart", "docker cp", "docker stop",
        "chmod 755 /opt/data", "chmod 711 /opt/data",
        "write_text(LIVE_CONFIG", "mcp add",
        "env=os.environ.copy()",
    ):
        assert forbidden not in s + sh, forbidden
    assert "git merge-base --is-ancestor" in sh
    assert "git status --porcelain" in sh
    assert "docker exec -i" in sh


def main():
    for fn in (test_syntax, test_isolated_config, test_no_llm_and_no_live_changes):
        fn()
        print(fn.__name__ + ": PASS")
    print("HERMES MCP DISCOVERY AUDIT OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
