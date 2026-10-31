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
        'EXPECTED_BASE="57315d3ea2859bd4ccef89ccd2bba19f05679fb4"',
        "git branch --show-current",
        "git merge-base --is-ancestor",
        "git rev-parse origin/staging",
        "git status --porcelain",
        "State.Running",
        "HostConfig.Privileged",
        "test ! -L /tmp/jason-os-pnap-canary",
        "test ! -e /tmp/jason-os-pnap-canary",
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
        "chmod 711 /opt/data",
        "chmod 751 /opt/data",
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
        'os.access("/tmp", os.X_OK)',
        'not os.access("/opt/data/.env", os.R_OK)',
        "docker cp",
        "JASON_OS_PNAP_CANARY=1",
        "RELEASE=\"/tmp/jason-os-pnap-canary\"",
        "sha256sum",
        "chmod 0555",
        "chmod 0444",
        'namespace["validated_snapshot"]',
        'Client(namespace["mcp"])',
        'list_tools()',
        'call_tool(',
        'result.is_error is False',
        'CANARY EPHEMERAL',
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
