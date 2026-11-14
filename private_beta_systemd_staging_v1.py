#!/usr/bin/env python3
"""Staging-only systemd entrypoint: never print the Private Beta session token.

Keep the existing HTTP UI, retrieval pipeline, feedback ownership and source
checks unchanged. A token rotates on every start/restart and is delivered via
the root-private filesystem, never stdout, stderr, argv, env, or journald.
"""
import os
import secrets
import stat
from pathlib import Path

import beta_private_ui_staging_v1 as ui

STATE_ROOT = Path("/var/lib/jason-os/private-beta-staging")
TOKEN_FILE = STATE_ROOT / "session-token-8765"
EXPECTED_ROOT = Path("/opt/ai-knowledge-staging")


class ServiceRefused(RuntimeError):
    pass


def require_private_directory(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise ServiceRefused("private_state_directory_missing") from exc
    if (not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ServiceRefused("private_state_directory_unsafe")


def require_private_originals():
    pdf_dir = ui.APPROVED_PDF_DIR
    require_private_directory(pdf_dir)
    for code in ("145", "149"):
        path = pdf_dir / ("APP" + code + ".pdf")
        try:
            info = os.lstat(path)
        except FileNotFoundError as exc:
            raise ServiceRefused("approved_original_missing") from exc
        if (not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ServiceRefused("approved_original_unsafe")
    # Original SHA and page identity are verified by existing PDF citation code.


def publish_token(token, destination=TOKEN_FILE):
    """Write rotated token atomically with 0600 permissions and no symlinks."""
    if not isinstance(token, str) or not 24 <= len(token) <= 256:
        raise ServiceRefused("invalid_generated_token")
    destination = Path(destination)
    require_private_directory(destination.parent)
    try:
        existing = os.lstat(destination)
    except FileNotFoundError:
        existing = None
    if existing and (not stat.S_ISREG(existing.st_mode)
                     or existing.st_uid != os.geteuid()
                     or existing.st_nlink != 1
                     or stat.S_IMODE(existing.st_mode) != 0o600):
        raise ServiceRefused("existing_token_file_unsafe")
    temporary = destination.parent / (
        "." + destination.name + "." + secrets.token_hex(16) + ".tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ServiceRefused("root_private_staging_identity_required")
    if ui.qa.ROOT != EXPECTED_ROOT:
        raise ServiceRefused("wrong_staging_checkout")
    ui.qa.check_checkout()
    if not ui.PAGE_PATH.is_file():
        raise ServiceRefused("missing_private_beta_html")
    require_private_directory(STATE_ROOT)
    require_private_originals()

    # Bind 127.0.0.1:8765 BEFORE rotating the token; a port conflict must
    # never invalidate the token belonging to the existing foreground server.
    server = ui.build_server(ui.DEFAULT_PORT, token=secrets.token_urlsafe(32))
    try:
        publish_token(server.ui_token)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
