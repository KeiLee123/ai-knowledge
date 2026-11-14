#!/usr/bin/env python3
"""Offline contracts for private, root-owned, loopback-only Beta systemd MVP."""
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import private_beta_systemd_staging_v1 as service

UNIT = Path(__file__).parent / "deploy/systemd/jason-os-private-beta-staging.service"
FAKE_TOKEN_1 = "synthetic-test-token-aaaaaaaaaaaa11111111111"
FAKE_TOKEN_2 = "synthetic-test-token-bbbbbbbbbbbb22222222222"


def must_refuse(action, expected):
    try:
        action()
    except service.ServiceRefused as exc:
        assert expected == str(exc), str(exc)
    else:
        raise AssertionError("unsafe action was accepted")


def test_atomic_root_private_token_creation_and_rotation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        token_file = root / "session-token-8765"
        service.publish_token(FAKE_TOKEN_1, token_file)
        assert token_file.read_text() == FAKE_TOKEN_1 + "\n"
        original = token_file.stat()
        assert stat.S_IMODE(original.st_mode) == 0o600
        assert original.st_uid == os.geteuid()
        assert original.st_nlink == 1

        service.publish_token(FAKE_TOKEN_2, token_file)
        assert token_file.read_text() == FAKE_TOKEN_2 + "\n"
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert sorted(p.name for p in root.iterdir()) == ["session-token-8765"]


def test_unsafe_token_paths_fail_closed():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        token_file = root / "session-token-8765"
        other = root / "other"
        other.write_text("local test sentinel")
        token_file.symlink_to(other)
        must_refuse(lambda: service.publish_token(FAKE_TOKEN_1, token_file),
                    "existing_token_file_unsafe")
        assert other.read_text() == "local test sentinel"
        token_file.unlink()

        token_file.write_text("insecure", encoding="utf-8")
        token_file.chmod(0o644)
        must_refuse(lambda: service.publish_token(FAKE_TOKEN_1, token_file),
                    "existing_token_file_unsafe")
        assert token_file.read_text() == "insecure"

        token_file.unlink()
        root.chmod(0o755)
        must_refuse(lambda: service.publish_token(FAKE_TOKEN_1, token_file),
                    "private_state_directory_unsafe")
        root.chmod(0o700)
        must_refuse(lambda: service.publish_token("bad", token_file),
                    "invalid_generated_token")


def test_replacement_failure_leaves_old_token_usable():
    with tempfile.TemporaryDirectory() as directory:
        token_file = Path(directory) / "session-token-8765"
        service.publish_token(FAKE_TOKEN_1, token_file)
        with patch.object(service.os, "replace", side_effect=OSError("synthetic")):
            try:
                service.publish_token(FAKE_TOKEN_2, token_file)
            except OSError as exc:
                assert str(exc) == "synthetic"
            else:
                raise AssertionError("atomic replacement error was hidden")
        assert token_file.read_text() == FAKE_TOKEN_1 + "\n"
        assert list(Path(directory).glob(".*.tmp")) == []


def test_pdf_cache_permission_guard_no_content_read():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for code in ("145", "149"):
            p = folder / ("APP" + code + ".pdf")
            p.write_bytes(b"synthetic-only-not-a-real-source")
            p.chmod(0o600)
        with patch.object(service.ui, "APPROVED_PDF_DIR", folder):
            service.require_private_originals()
            (folder / "APP149.pdf").chmod(0o644)
            must_refuse(service.require_private_originals,
                        "approved_original_unsafe")


def test_unit_exact_staging_paths_and_token_nonleakage():
    text = UNIT.read_text(encoding="utf-8")
    assert "User=root" in text and "Group=root" in text
    assert "UMask=0077" in text
    assert "WorkingDirectory=/opt/ai-knowledge-staging" in text
    assert "ExecStart=/opt/ai-knowledge-staging/.venv/bin/python -B /opt/ai-knowledge-staging/private_beta_systemd_staging_v1.py" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=15" in text
    assert "StartLimitIntervalSec=0" in text  # DB containers may initialize after Docker
    assert "StandardOutput=null" in text and "StandardError=null" in text
    assert "NoNewPrivileges=true" in text
    assert "WantedBy=multi-user.target" in text
    assert "0.0.0.0" not in text
    for forbidden in ("Environment=TOKEN", "EnvironmentFile=", "ExecStart=/bin/sh",
                      "ExecStart=/bin/bash", "StandardOutput=journal"):
        assert forbidden not in text


def test_existing_ui_entrypoint_and_checkout_guard_unmodified():
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "ui.qa.check_checkout()" in source
    assert "ui.build_server(ui.DEFAULT_PORT, token=secrets.token_urlsafe(32))" in source
    assert "publish_token(server.ui_token)" in source
    assert source.index("ui.build_server(") < source.index("publish_token(server.ui_token)")
    assert "server.serve_forever" in source
    assert "print(" not in source
    assert "os.environ" not in source
    assert service.ui.HOST == "127.0.0.1"
    assert service.ui.DEFAULT_PORT == 8765
    assert service.STATE_ROOT == Path("/var/lib/jason-os/private-beta-staging")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("PRIVATE BETA SYSTEMD STAGING OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
