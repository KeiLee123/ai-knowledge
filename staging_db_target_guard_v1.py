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
