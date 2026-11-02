#!/usr/bin/env python3
"""Fail-closed, Staging-only database write target guard for raw v2 writers.

Reuse the existing canary guard's branch and Docker identity checks. This
module authorizes a target identity, NOT an actual ingestion or a Quality
Gate pass. The calling writer must still apply all of its other checks.
"""
from pathlib import Path

from run_multimodal_canary_v2 import (
    STAGING_DB_CONTAINER,
    verify_runtime,
)


def enforce_staging_write_target(
    db_container: str,
    repo_root: Path,
) -> dict:
    if db_container != STAGING_DB_CONTAINER:
        raise RuntimeError(
            "STAGING_DB_TARGET_REFUSED: explicit fixed staging DB required"
        )

    # verify_runtime checks Git branch, Docker container labels, network,
    # port bindings, running and health. Fail closed on any error.
    return verify_runtime(repo_root)


# Proposed Staging-only writer login; not created by this code-only change.
STAGING_DB_WRITER_ROLE = "ai_knowledge_writer_staging"


def enforce_staging_writer_role(db_role: str) -> None:
    """Reject implicit, superuser, and caller-chosen writer identities."""
    if db_role != STAGING_DB_WRITER_ROLE:
        raise RuntimeError(
            "STAGING_DB_ROLE_REFUSED: explicit fixed staging writer role required"
        )


def verify_staging_writer_role(db_container: str, db_role: str) -> None:
    """Read-only runtime privilege check. Never grants privileges or writes SQL."""
    import subprocess

    enforce_staging_writer_role(db_role)
    # Executed as the actual proposed writer role. Reject unexpected database,
    # privileged role flags, or membership in the existing superuser account.
    sql = (
        "SELECT CASE WHEN "
        "current_user = 'ai_knowledge_writer_staging' "
        "AND current_database() = 'ai_knowledge' "
        "AND NOT (rolsuper OR rolcreatedb OR rolcreaterole "
        "OR rolreplication OR rolbypassrls) "
        "AND NOT pg_has_role(current_user, 'ai_knowledge', 'MEMBER') "
        "THEN 'STAGING_ROLE_OK' ELSE 'STAGING_ROLE_REFUSED' END "
        "FROM pg_catalog.pg_roles WHERE rolname = current_user;"
    )
    result = subprocess.run(
        [
            "docker", "exec", "-i", db_container,
            "psql", "-X", "-U", db_role, "-d", "ai_knowledge",
            "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "STAGING_ROLE_OK":
        raise RuntimeError(
            "STAGING_DB_ROLE_PRIVILEGE_REFUSED: expected non-privileged "
            "Staging writer login/database; inspect role grants before writes"
        )
