#!/usr/bin/env python3
"""Gate 3D-C rootless Hermes MCP discovery diagnostic. NO LLM call, NO API key.

Runs inside existing Hermes Docker container, with source piped from GitHub
Staging. Makes a new one-time /tmp profile, executes Hermes as UID65534,
and runs only config-get and mcp-test. Never alters /opt/data/config.yaml.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

UID = 65534
CANARY = Path("/tmp/jason-os-pnap-canary")
CLI = "/opt/hermes/.venv/bin/hermes"
LIVE_CONFIG = Path("/opt/data/config.yaml")
PREFIX = "jason-os-pnap-discovery-"
SERVER = "jason_os_pnap_canary"
TOOL = "read_approved_pnap_source"


def require(cond, msg):
    if not cond:
        raise RuntimeError(msg)


def diagnostic_config():
    return {
        "toolsets": ["mcp-" + SERVER],
        "mcp_servers": {
            SERVER: {
                "command": "/usr/bin/env",
                "args": [
                    "-i", "PYTHONDONTWRITEBYTECODE=1",
                    "JASON_OS_PNAP_CANARY=1",
                    "/opt/hermes/.venv/bin/python",
                    str(CANARY / "server.py"),
                ],
                "tools": {"include": [TOOL], "resources": False, "prompts": False},
            }
        },
    }


def clean_display(raw):
    # Isolated env has no provider secrets; still cap and scrub key-shaped text.
    raw = re.sub(r"(?i)(api[_-]?key|token|authorization)(\\s*[:=]\\s*)[^\\s,]+",
                 r"\\1\\2[REDACTED]", raw or "")
    raw = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", raw)
    return raw.replace("\\x1b", "")[-1600:]


def run_cli(args, env, folder, seconds=35):
    return subprocess.run(
        ["/usr/bin/setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
         CLI] + args,
        cwd=folder, env=env, capture_output=True, text=True, timeout=seconds,
    )


def main():
    require(os.geteuid() == 0, "audit_wrapper_expected_root")
    require(LIVE_CONFIG.is_file(), "live_config_missing")
    require(CANARY.is_dir() and (CANARY / "server.py").is_file(), "accepted_canary_missing")
    for name in ("BD_PNAP_APP145", "BD_PNAP_APP149"):
        require((CANARY / "snapshots" / (name + ".json")).is_file(), "accepted_snapshot_missing")
    before = hashlib.sha256(LIVE_CONFIG.read_bytes()).hexdigest()
    folder = Path(tempfile.mkdtemp(prefix=PREFIX, dir="/tmp"))
    try:
        os.chown(folder, UID, UID)
        folder.chmod(0o700)
        cfg = folder / "config.yaml"
        cfg.write_text(yaml.safe_dump(diagnostic_config()), encoding="utf-8")
        os.chown(cfg, UID, UID)
        cfg.chmod(0o600)
        env = {
            "HERMES_HOME": str(folder), "HOME": str(folder),
            "PATH": "/opt/hermes/.venv/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
            "XDG_CACHE_HOME": str(folder / ".cache"),
        }
        require("DEEPSEEK_API_KEY" not in env, "unexpected_model_credential")
        print("=== NO-MODEL HERMES MCP DISCOVERY AUDIT ===", flush=True)
        version = run_cli(["--version"], env, folder, 20)
        print("CLI version:", clean_display(version.stdout).strip() or "NOT_SHOWN", flush=True)
        print("CLI version exit:", version.returncode, flush=True)
        read = run_cli(["config", "get", "mcp_servers", "--json"], env, folder, 30)
        visible = read.returncode == 0 and SERVER in read.stdout
        print("Isolated mcp_servers visible to Hermes:", visible, flush=True)
        print("Config get exit:", read.returncode, flush=True)
        if not visible:
            print("Config get diagnostic:", clean_display(read.stderr or read.stdout), flush=True)

        help_result = run_cli(["mcp", "--help"], env, folder, 20)
        test_supported = help_result.returncode == 0 and "test" in (
            help_result.stdout + help_result.stderr
        ).lower()
        print("Hermes mcp test available:", test_supported, flush=True)
        if test_supported and visible:
            mcp = run_cli(["mcp", "test", SERVER], env, folder, 65)
            print("Hermes mcp test exit:", mcp.returncode, flush=True)
            print("Hermes mcp test result:", clean_display(mcp.stdout + "\\n" + mcp.stderr),
                  flush=True)
        else:
            print("Hermes mcp test: SKIPPED (config or CLI prerequisite failed)", flush=True)
        chat_help = run_cli(["chat", "--help"], env, folder, 20)
        supports_stream = ("stream-json" in chat_help.stdout or
                           "--format" in chat_help.stdout)
        print("Structured Chat output support:", supports_stream, flush=True)
        print("Existing global Hermes config not changed", flush=True)
        print("DISCOVERY AUDIT COMPLETE (NOT AN E2E ACCEPTANCE)", flush=True)
    finally:
        require(folder.parent == Path("/tmp") and folder.name.startswith(PREFIX),
                "temporary_folder_guard_failed")
        shutil.rmtree(folder)
        require(hashlib.sha256(LIVE_CONFIG.read_bytes()).hexdigest() == before,
                "global_hermes_config_changed")
        print("Temporary discovery profile deleted; live config SHA unchanged", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("MCP DISCOVERY AUDIT FAILED:", type(exc).__name__, flush=True)
        raise SystemExit(1) from None
