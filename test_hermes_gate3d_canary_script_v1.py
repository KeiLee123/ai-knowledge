#!/usr/bin/env python3
"""Offline contract for the Gate 3D-B guarded canary script (no Docker calls)."""
import ast
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "scripts" / "hermes_gate3d_canary_install_staging.sh"


def test_shell_and_embedded_python_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", SCRIPT.read_text(), re.DOTALL)
    assert len(blocks) == 2, len(blocks)
    for code in blocks:
        ast.parse(code)


def test_staging_and_target_guards():
    source = SCRIPT.read_text()
    for expected in (
        'REPO="/opt/ai-knowledge-staging"',
        'EXPECTED="57315d3ea2859bd4ccef89ccd2bba19f05679fb4"',
        "git branch --show-current",
        "git status --porcelain",
        "State.Running",
        "HostConfig.Privileged",
        "test ! -L /opt/data/jason-os-pnap-staging",
        "test ! -e /opt/data/jason-os-pnap-staging",
        'HOST_SNAPSHOTS="/var/lib/jason-os/hermes-pnap-snapshots-staging"',
        "APP145",
        "APP149",
        'CONFIG_BEFORE=',
        'CONFIG_AFTER=',
        'test "$CONFIG_BEFORE" = "$CONFIG_AFTER"',
    ):
        assert expected in source, expected

    for forbidden in (
        "docker restart",
        "docker run ",
        "docker network connect",
        "docker exec -it",
        "docker stop",
        "docker compose",
        "chmod 777",
        "chmod 755 /opt/data",
        "docker exec $CID sh -c",
        "docker cp /opt/ai-knowledge-staging",
        "curl ",
        "rclone ",
        "pip install",
        "config.yaml >",
        "rm -rf",
    ):
        assert forbidden not in source, forbidden


def test_low_privilege_and_payload_integrity():
    source = SCRIPT.read_text()
    for expected in (
        "setpriv --reuid=65534 --regid=65534 --clear-groups",
        "/usr/bin/env -i",
        'os.access("/opt/data", os.X_OK)',
        'not os.access("/opt/data/.env", os.R_OK)',
        "docker cp",
        "sha256sum",
        "chmod 0555",
        "chmod 0444",
        'namespace["validated_snapshot"]',
        'Client(namespace["mcp"])',
        'list_tools()',
        'call_tool(',
        'result.is_error is False',
        'HERMES CHAT NOT ACTIVATED',
    ):
        assert expected in source, expected


def main():
    for test in (
        test_shell_and_embedded_python_syntax,
        test_staging_and_target_guards,
        test_low_privilege_and_payload_integrity,
    ):
        test()
        print(test.__name__ + ": PASS")
    print("HERMES GATE 3D-B CANARY SCRIPT CONTRACT: PASS")


if __name__ == "__main__":
    main()
