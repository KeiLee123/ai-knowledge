#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from canonical_text_production_v2 import (
    CHUNKS_FILENAME,
    build_transaction_sql,
    build_zero_state_sql,
    parse_json_payload,
    run_production_query,
    validate_zero_state,
)
from ingest_manifest_v2 import (
    DEFAULT_EMBED_URL,
    check_database_contract,
    execute_transaction,
    inspect_transaction_sql,
    load_chunks,
    precompute_embeddings,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    verify_runtime,
)
from production_release_contract_v2 import (
    load_release_registry,
    resolve_release_source,
)
from validate_production_write_readiness_v2 import (
    git_identity,
    validate_prepared_artifacts,
)


VERSION = "canonical-text-production-write-v2"


def check_zero_state(
    checksum: str,
) -> dict:
    return validate_zero_state(
        parse_json_payload(
            run_production_query(
                build_zero_state_sql(
                    checksum
                )
            ),
            "Production v2 zero-state query",
        )
    )


def extract_document_id(
    output: str,
) -> int:
    match = re.search(
        r"DOCUMENT_ID\s+(\d+)",
        output,
    )

    if not match:
        raise RuntimeError(
            "Committed transaction did not "
            "report DOCUMENT_ID"
        )

    return int(
        match.group(1)
    )


def run_post_write_validator(
    *,
    repo_root: Path,
    source_id: str,
    registry_path: Path,
) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(
                repo_root
                / "validate_canonical_text_production_v2.py"
            ),
            source_id,
            "--registry",
            str(
                registry_path
            ),
        ],
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print()
        print(
            "POST_WRITE_VALIDATION"
        )
        print(
            result.stdout.rstrip()
        )

    if result.returncode != 0:
        raise RuntimeError(
            "WRITE COMMITTED BUT "
            "POST-WRITE VALIDATION FAILED: "
            + (
                result.stderr.strip()
                or result.stdout.strip()
                or "unknown validator failure"
            )
        )

    return {
        "validator_exit_code":
            0,
        "post_write_validation_ok":
            True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Explicit generic Production "
            "write executor v2."
        )
    )

    parser.add_argument(
        "source_id"
    )

    parser.add_argument(
        "--write",
        action="store_true",
    )

    parser.add_argument(
        "--confirm-production-write",
        action="store_true",
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

    parser.add_argument(
        "--embed-url",
        default=DEFAULT_EMBED_URL,
    )

    args = parser.parse_args()

    if (
        args.confirm_production_write
        and not args.write
    ):
        raise SystemExit(
            "--confirm-production-write "
            "requires --write"
        )

    if (
        args.write
        and not args.confirm_production_write
    ):
        raise SystemExit(
            "--write requires "
            "--confirm-production-write"
        )

    if not args.write:
        raise SystemExit(
            "Only explicit --write mode "
            "is supported"
        )

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    registry_path = (
        Path(args.registry)
        .expanduser()
        .resolve()
    )

    workdir = (
        Path(
            args.prepared_workdir
        )
        .expanduser()
        .resolve()
    )

    committed = False
    document_id = None

    try:
        guard = verify_runtime(
            repo_root
        )

        identity = git_identity(
            repo_root
        )

        registry = load_release_registry(
            registry_path
        )

        (
            source,
            config,
            defaults,
        ) = resolve_release_source(
            registry,
            args.source_id,
            require_write_authorized=
                True,
        )

        prepared = (
            validate_prepared_artifacts(
                workdir=workdir,
                config=config,
            )
        )

        checksum = config[
            "expected_sha256"
        ]

        initial_zero_state = (
            check_zero_state(
                checksum
            )
        )

        db_contract = (
            check_database_contract(
                checksum,
                PRODUCTION_DB_CONTAINER,
            )
        )

        if not db_contract[
            "contract_ok"
        ]:
            raise RuntimeError(
                "Production database "
                "contract failed"
            )

        if (
            db_contract.get(
                "duplicate_checksum"
            )
            is not None
        ):
            raise RuntimeError(
                "Production checksum "
                "already exists"
            )

        chunks_path = (
            workdir
            / CHUNKS_FILENAME
        )

        payload = load_chunks(
            chunks_path
        )

        vectors = precompute_embeddings(
            payload,
            args.embed_url,
        )

        sql = build_transaction_sql(
            payload=payload,
            vectors=vectors,
            chunks_path=
                chunks_path,
            source=source,
            config=config,
            defaults=defaults,
        )

        inspection = (
            inspect_transaction_sql(
                sql,
                config[
                    "expected_chunk_count"
                ],
            )
        )

        if not inspection[
            "transaction_contract_ok"
        ]:
            raise RuntimeError(
                "Production v2 transaction "
                "contract failed"
            )

        pre_commit_zero_state = (
            check_zero_state(
                checksum
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
                    **identity,
                    "db_container":
                        PRODUCTION_DB_CONTAINER,
                    "source_id":
                        args.source_id,
                    "release_id":
                        config[
                            "release_id"
                        ],
                    "checksum":
                        checksum,
                    "prepared_artifacts":
                        prepared,
                    "initial_zero_state":
                        initial_zero_state,
                    "pre_commit_zero_state":
                        pre_commit_zero_state,
                    "database_contract_ok":
                        db_contract[
                            "contract_ok"
                        ],
                    "transaction":
                        inspection,
                    "explicit_confirmation":
                        True,
                    "write_authorized":
                        True,
                    "database_write_requested":
                        True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        output = execute_transaction(
            sql,
            PRODUCTION_DB_CONTAINER,
        )

        committed = True
        document_id = (
            extract_document_id(
                output
            )
        )

        print()
        print(
            "PRODUCTION_V2_WRITE_COMMITTED"
        )
        print(
            "DOCUMENT_ID",
            document_id,
        )

        validation = (
            run_post_write_validator(
                repo_root=repo_root,
                source_id=
                    args.source_id,
                registry_path=
                    registry_path,
            )
        )

        print()
        print(
            json.dumps(
                {
                    "version":
                        VERSION,
                    "source_id":
                        args.source_id,
                    "release_id":
                        config[
                            "release_id"
                        ],
                    "checksum":
                        checksum,
                    "document_id":
                        document_id,
                    "database_write_performed":
                        True,
                    "post_write_validation":
                        validation,
                    "production_status":
                        "INGESTED_AND_VALIDATED",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "PRODUCTION_V2_TEXT_WRITE_VERIFIED"
        )

    except Exception as exc:
        if committed:
            raise SystemExit(
                "PRODUCTION V2 POST-COMMIT "
                "FAILURE: "
                f"{type(exc).__name__}: "
                f"{exc}\n"
                "The write was committed. "
                "Use v2 recovery only after "
                "manual review."
            ) from exc

        raise SystemExit(
            "PRODUCTION V2 WRITE FAILED "
            "BEFORE COMMIT: "
            f"{type(exc).__name__}: "
            f"{exc}\n"
            "Database writes performed: False"
        ) from exc


if __name__ == "__main__":
    main()
