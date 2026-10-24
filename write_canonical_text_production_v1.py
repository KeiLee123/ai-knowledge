#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

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
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from production_release_source_v1 import (
    load_release_registry,
)
from promote_canonical_text_production_v1 import (
    build_production_transaction_sql,
    resolve_promotion_source,
)
from validate_production_write_readiness_v1 import (
    build_zero_state_sql,
    git_head,
    is_ancestor,
    parse_json_payload,
    validate_prepared_artifacts,
    validate_zero_state,
)
from validate_canonical_text_production_v1 import (
    run_production_query,
)


VERSION = "canonical-text-production-write-v1"

REQUIRED_WRITE_BASE_COMMIT = (
    "b5aed0b7619f4bb9beec175e0d913b136d9225b4"
)


def resolve_write_config(registry, source_id):
    source, promotion, defaults = resolve_promotion_source(
        registry,
        source_id,
    )

    write_config = source.get(
        "canonical_text_production_write"
    )

    if not isinstance(write_config, dict):
        raise RuntimeError(
            "canonical_text_production_write config missing"
        )

    errors = []

    if write_config.get("enabled") is not True:
        errors.append(
            "canonical_text_production_write must be enabled"
        )

    if (
        write_config.get("controller_environment")
        != "production"
    ):
        errors.append(
            "controller_environment must be production"
        )

    if (
        write_config.get("db_container")
        != PRODUCTION_DB_CONTAINER
    ):
        errors.append(
            "db_container must be the fixed Production DB"
        )

    if (
        write_config.get("db_container")
        == STAGING_DB_CONTAINER
    ):
        errors.append(
            "Staging DB container is forbidden"
        )

    if (
        write_config.get("required_route")
        != promotion.get("required_route")
    ):
        errors.append(
            "write required_route must match promotion profile"
        )

    if (
        write_config.get("expected_sha256")
        != promotion.get("expected_sha256")
    ):
        errors.append(
            "write checksum must match promotion profile"
        )

    chunks_sha = str(
        write_config.get("expected_chunks_sha256")
        or ""
    )

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        chunks_sha,
    ):
        errors.append(
            "expected_chunks_sha256 must be lowercase SHA-256"
        )

    if (
        write_config.get("expected_chunk_count")
        != promotion.get("expected_chunk_count")
    ):
        errors.append(
            "write chunk count must match promotion profile"
        )

    if (
        write_config.get("expected_embedding_count")
        != promotion.get("expected_embedding_count")
    ):
        errors.append(
            "write embedding count must match promotion profile"
        )

    if write_config.get("require_confirmation") is not True:
        errors.append(
            "require_confirmation must be true"
        )

    if errors:
        raise RuntimeError(
            "; ".join(errors)
        )

    return (
        source,
        promotion,
        write_config,
        defaults,
    )


def assert_reviewed_write_baseline(repo_root):
    head = git_head(repo_root)

    if not is_ancestor(
        repo_root,
        REQUIRED_WRITE_BASE_COMMIT,
        head,
    ):
        raise RuntimeError(
            "Current main does not contain the reviewed "
            "Production write-readiness baseline"
        )

    return head


def check_zero_state(checksum):
    return validate_zero_state(
        parse_json_payload(
            run_production_query(
                build_zero_state_sql(checksum)
            ),
            "Production zero-state query",
        )
    )


def validate_prepared_write_candidate(
    *,
    workdir,
    promotion_config,
    write_config,
):
    prepared = validate_prepared_artifacts(
        workdir=workdir,
        config=promotion_config,
    )

    if (
        prepared["chunks_file_sha256"]
        != write_config["expected_chunks_sha256"]
    ):
        raise RuntimeError(
            "Prepared chunks SHA-256 does not match "
            "the Git-controlled Production write authorization"
        )

    if (
        prepared["chunk_count"]
        != write_config["expected_chunk_count"]
    ):
        raise RuntimeError(
            "Prepared chunk count does not match write authorization"
        )

    return prepared


def build_write_transaction(
    *,
    workdir,
    source,
    promotion_config,
    write_config,
    defaults,
    embed_url,
):
    chunks_path = (
        workdir
        / "retrieval-chunks-production-v1.json"
    )

    payload = load_chunks(
        chunks_path
    )

    vectors = precompute_embeddings(
        payload,
        embed_url,
    )

    if (
        len(vectors)
        != write_config["expected_embedding_count"]
    ):
        raise RuntimeError(
            "Embedding count does not match "
            "Production write authorization"
        )

    sql = build_production_transaction_sql(
        payload=payload,
        vectors=vectors,
        chunks_path=chunks_path,
        title=str(
            source.get("title")
            or source.get("document_code")
            or "Canonical document"
        ),
        domain=str(
            source.get("domain")
            or "unknown"
        ),
        topic=str(
            source.get("topic")
            or ""
        ),
        document_type=str(
            promotion_config.get("document_type")
            or source.get("source_type")
            or "official-document"
        ),
        authority=str(
            source.get("authority_code")
            or ""
        ),
        jurisdiction=str(
            defaults.get("jurisdiction")
            or "HK"
        ),
        language=str(
            promotion_config.get("language")
            or "en"
        ),
        source_url=str(
            source.get("canonical_url")
            or ""
        ),
        canonical_source=promotion_config["source"],
        canonical_sha256=promotion_config["expected_sha256"],
    )

    inspection = inspect_transaction_sql(
        sql,
        write_config["expected_chunk_count"],
    )

    if not inspection["transaction_contract_ok"]:
        raise RuntimeError(
            "Generated Production write transaction "
            "failed structural validation"
        )

    return (
        sql,
        inspection,
    )


def extract_document_id(output):
    match = re.search(
        r"DOCUMENT_ID\s+(\d+)",
        output,
    )

    if not match:
        raise RuntimeError(
            "Committed transaction did not report DOCUMENT_ID"
        )

    return int(
        match.group(1)
    )


def run_post_write_validator(
    repo_root,
    source_id,
):
    command = [
        sys.executable,
        str(
            repo_root
            / "validate_canonical_text_production_v1.py"
        ),
        source_id,
    ]

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print()
        print("POST_WRITE_VALIDATION")
        print(
            result.stdout.rstrip()
        )

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Production post-write validator failed"
        )

        raise RuntimeError(
            "WRITE COMMITTED BUT POST-WRITE VALIDATION FAILED: "
            + detail
        )

    return {
        "validator_exit_code": 0,
        "post_write_validation_ok": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Explicit one-document Production write executor for "
            "Canonical Text Production Promotion v1."
        )
    )

    parser.add_argument(
        "source_id",
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Execute the reviewed Production transaction."
        ),
    )

    parser.add_argument(
        "--confirm-production-write",
        action="store_true",
        help=(
            "Required explicit acknowledgement for the Production write."
        ),
    )

    parser.add_argument(
        "--prepared-workdir",
        required=True,
        help=(
            "P7 prepared artifact directory previously verified by P8."
        ),
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent
            / "production_release_registry_v1.yaml"
        ),
    )

    parser.add_argument(
        "--embed-url",
        default=DEFAULT_EMBED_URL,
    )

    args = parser.parse_args()

    if args.confirm_production_write and not args.write:
        raise SystemExit(
            "--confirm-production-write requires --write"
        )

    if args.write and not args.confirm_production_write:
        raise SystemExit(
            "--write requires --confirm-production-write"
        )

    if not args.write:
        raise SystemExit(
            "Only explicit --write mode is supported"
        )

    repo_root = Path(__file__).resolve().parent
    workdir = Path(
        args.prepared_workdir
    ).expanduser().resolve()

    committed = False
    document_id = None

    try:
        guard = verify_runtime(
            repo_root
        )

        head = assert_reviewed_write_baseline(
            repo_root
        )

        registry = load_release_registry(
            Path(args.registry).expanduser().resolve()
        )

        (
            source,
            promotion_config,
            write_config,
            defaults,
        ) = resolve_write_config(
            registry,
            args.source_id,
        )

        checksum = write_config[
            "expected_sha256"
        ]

        prepared = validate_prepared_write_candidate(
            workdir=workdir,
            promotion_config=promotion_config,
            write_config=write_config,
        )

        initial_zero_state = check_zero_state(
            checksum
        )

        db_contract = check_database_contract(
            checksum,
            PRODUCTION_DB_CONTAINER,
        )

        if not db_contract["contract_ok"]:
            raise RuntimeError(
                "Production database contract failed"
            )

        if db_contract.get("duplicate_checksum") is not None:
            raise RuntimeError(
                "Production checksum already exists"
            )

        sql, inspection = build_write_transaction(
            workdir=workdir,
            source=source,
            promotion_config=promotion_config,
            write_config=write_config,
            defaults=defaults,
            embed_url=args.embed_url,
        )

        pre_commit_zero_state = check_zero_state(
            checksum
        )

        print()
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "guard_ok": guard["guard_ok"],
                    "branch": guard["branch"],
                    "git_head": head,
                    "required_write_base_commit":
                        REQUIRED_WRITE_BASE_COMMIT,
                    "db_container":
                        PRODUCTION_DB_CONTAINER,
                    "source_id": args.source_id,
                    "checksum": checksum,
                    "prepared_artifacts": prepared,
                    "initial_zero_state":
                        initial_zero_state,
                    "pre_commit_zero_state":
                        pre_commit_zero_state,
                    "database_contract_ok":
                        db_contract["contract_ok"],
                    "expected_chunk_count":
                        write_config[
                            "expected_chunk_count"
                        ],
                    "expected_embedding_count":
                        write_config[
                            "expected_embedding_count"
                        ],
                    "transaction":
                        inspection,
                    "explicit_confirmation": True,
                    "database_write_requested": True,
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
        document_id = extract_document_id(
            output
        )

        print()
        print("PRODUCTION_WRITE_COMMITTED")
        print(
            "DOCUMENT_ID",
            document_id,
        )

        validation = run_post_write_validator(
            repo_root,
            args.source_id,
        )

        print()
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "source_id": args.source_id,
                    "checksum": checksum,
                    "document_id": document_id,
                    "database_write_performed": True,
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
            "STATUS: PRODUCTION_TEXT_WRITE_VERIFIED"
        )

    except Exception as exc:
        if committed:
            raise SystemExit(
                "PRODUCTION WRITE POST-COMMIT FAILURE: "
                f"{type(exc).__name__}: {exc}\n"
                "The database write was committed. "
                "Use the dedicated Production recovery command "
                "only after reviewing the failure."
            ) from exc

        raise SystemExit(
            "PRODUCTION WRITE FAILED BEFORE COMMIT: "
            f"{type(exc).__name__}: {exc}\n"
            "Database writes performed: False"
        ) from exc


if __name__ == "__main__":
    main()
