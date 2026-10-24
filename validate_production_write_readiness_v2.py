#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

from canonical_text_production_v2 import (
    CHUNKS_FILENAME,
    build_zero_state_sql,
    parse_json_payload,
    run_production_query,
    sha256_file,
    validate_chunk_contract,
    validate_chunks_file,
    validate_zero_state,
)
from ingest_manifest_v2 import (
    load_chunks,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    verify_runtime,
)
from production_release_contract_v2 import (
    load_release_registry,
    resolve_release_source,
)
from recover_canonical_text_production_v2 import (
    build_recovery_sql,
    inspect_recovery_sql,
)


VERSION = "canonical-text-production-write-readiness-v2"


def git_identity(
    repo_root: Path,
) -> dict:
    head = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "HEAD",
        ],
        text=True,
        capture_output=True,
    )

    if head.returncode != 0:
        raise RuntimeError(
            "Unable to read Git HEAD"
        )

    status = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain",
        ],
        text=True,
        capture_output=True,
    )

    if status.returncode != 0:
        raise RuntimeError(
            "Unable to read Git worktree status"
        )

    clean = (
        status.stdout.strip()
        == ""
    )

    if not clean:
        raise RuntimeError(
            "Production worktree must be clean"
        )

    return {
        "git_head":
            head.stdout.strip(),
        "worktree_clean":
            True,
    }


def validate_prepared_artifacts(
    *,
    workdir: Path,
    config: dict,
) -> dict:
    source_path = (
        workdir
        / Path(
            config["source"]
        ).name
    )

    chunks_path = (
        workdir
        / CHUNKS_FILENAME
    )

    if not source_path.is_file():
        raise RuntimeError(
            "Prepared canonical PDF missing"
        )

    if not chunks_path.is_file():
        raise RuntimeError(
            "Prepared chunks file missing"
        )

    canonical_sha = sha256_file(
        source_path
    )

    if (
        canonical_sha
        != config[
            "expected_sha256"
        ]
    ):
        raise RuntimeError(
            "Prepared canonical PDF "
            "checksum mismatch"
        )

    chunks_payload = load_chunks(
        chunks_path
    )

    contract = validate_chunk_contract(
        chunks_payload,
        config,
    )

    chunks_sha = validate_chunks_file(
        chunks_path,
        config,
    )

    return {
        "workdir":
            str(workdir),
        "canonical_pdf":
            source_path.name,
        "canonical_sha256":
            canonical_sha,
        "chunks_file":
            chunks_path.name,
        "chunks_sha256":
            chunks_sha,
        "chunk_count":
            contract[
                "chunk_count"
            ],
        "prepared_artifacts_ok":
            True,
    }


def validate_validator_readiness(
    repo_root: Path,
) -> dict:
    path = (
        repo_root
        / "validate_canonical_text_production_v2.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "execute_transaction",
        "DELETE FROM",
        "INSERT INTO",
        "--write",
        "--recover",
    )

    found = [
        token
        for token in forbidden
        if token in source
    ]

    if found:
        raise RuntimeError(
            "Production v2 validator "
            "contains write path(s): "
            + ", ".join(found)
        )

    required = (
        "run_production_query",
        "semantic_check",
        "release_id",
        "integrity_ok",
    )

    missing = [
        token
        for token in required
        if token not in source
    ]

    if missing:
        raise RuntimeError(
            "Production v2 validator "
            "readiness missing: "
            + ", ".join(missing)
        )

    return {
        "read_only":
            True,
        "integrity_check":
            True,
        "semantic_check":
            True,
        "validator_ready":
            True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Final read-only readiness gate "
            "for Generic Production Promotion v2."
        )
    )

    parser.add_argument(
        "source_id"
    )

    parser.add_argument(
        "--prepared-workdir",
        required=True,
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__)
            .resolve()
            .parent
            / "production_release_registry_v2.yaml"
        ),
    )

    args = parser.parse_args()

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    try:
        guard = verify_runtime(
            repo_root
        )

        identity = git_identity(
            repo_root
        )

        registry = load_release_registry(
            Path(args.registry)
            .expanduser()
            .resolve()
        )

        _, config, _ = (
            resolve_release_source(
                registry,
                args.source_id,
                require_write_authorized=
                    True,
            )
        )

        workdir = (
            Path(
                args.prepared_workdir
            )
            .expanduser()
            .resolve()
        )

        prepared = (
            validate_prepared_artifacts(
                workdir=workdir,
                config=config,
            )
        )

        zero_state = (
            validate_zero_state(
                parse_json_payload(
                    run_production_query(
                        build_zero_state_sql(
                            config[
                                "expected_sha256"
                            ]
                        )
                    ),
                    "Production v2 "
                    "zero-state query",
                )
            )
        )

        recovery_sql = (
            build_recovery_sql(
                config[
                    "expected_sha256"
                ],
                config[
                    "release_id"
                ],
            )
        )

        recovery = (
            inspect_recovery_sql(
                recovery_sql
            )
        )

        if not recovery[
            "recovery_contract_ok"
        ]:
            raise RuntimeError(
                "Production v2 recovery "
                "contract is not ready"
            )

        validator = (
            validate_validator_readiness(
                repo_root
            )
        )

        print(
            json.dumps(
                {
                    "version":
                        VERSION,
                    "guard_ok":
                        guard[
                            "guard_ok"
                        ],
                    "branch":
                        guard[
                            "branch"
                        ],
                    "db_container":
                        PRODUCTION_DB_CONTAINER,
                    "source_id":
                        args.source_id,
                    "release_id":
                        config[
                            "release_id"
                        ],
                    "write_authorized":
                        config[
                            "write_authorized"
                        ],
                    **identity,
                    "prepared_artifacts":
                        prepared,
                    "zero_state":
                        zero_state,
                    "recovery":
                        recovery,
                    "validator":
                        validator,
                    "database_write_performed":
                        False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "PRODUCTION_V2_WRITE_READINESS_VERIFIED"
        )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION V2 WRITE READINESS "
            "FAILED: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


if __name__ == "__main__":
    main()
