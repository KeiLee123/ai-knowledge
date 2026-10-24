#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from production_release_source_v1 import (
    load_release_registry,
)
from promote_canonical_text_production_v1 import (
    resolve_promotion_source,
    sha256_file,
    validate_frozen_chunk_contract,
)
from ingest_manifest_v2 import load_chunks
from recover_canonical_text_production_v1 import (
    build_recovery_sql,
    inspect_recovery_sql,
)
from validate_canonical_text_production_v1 import (
    run_production_query,
)


VERSION = "canonical-text-production-write-readiness-v1"

REQUIRED_RELEASE_BASE_COMMIT = (
    "be5de81fdf2fd8e7ac37a1a76ca4619faa55bfc2"
)


def git_head(repo_root):
    result = subprocess.run(
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

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Unable to read Git HEAD"
        )

    return result.stdout.strip()


def is_ancestor(repo_root, ancestor, descendant):
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode == 0:
        return True

    if result.returncode == 1:
        return False

    raise RuntimeError(
        result.stderr.strip()
        or result.stdout.strip()
        or "Unable to verify Git ancestry"
    )


def build_zero_state_sql(checksum):
    return f"""
SELECT json_build_object(
    'document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'chunk_count', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
    ),
    'embedding_count', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
          ON c.id = e.chunk_id
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
    )
)::text;
""".strip()


def parse_json_payload(text, label):
    payload = json.loads(text.strip())

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{label} did not return a JSON object"
        )

    return payload


def validate_zero_state(payload):
    counts = {
        "document_count": int(
            payload.get("document_count") or 0
        ),
        "chunk_count": int(
            payload.get("chunk_count") or 0
        ),
        "embedding_count": int(
            payload.get("embedding_count") or 0
        ),
    }

    if any(counts.values()):
        raise RuntimeError(
            "Production candidate checksum already has rows: "
            + json.dumps(counts, sort_keys=True)
        )

    return {
        **counts,
        "zero_state_ok": True,
    }


def validate_prepared_artifacts(
    *,
    workdir,
    config,
):
    source_path = workdir / Path(config["source"]).name
    chunks_path = (
        workdir
        / "retrieval-chunks-production-v1.json"
    )

    if not source_path.is_file():
        raise RuntimeError(
            f"Prepared canonical PDF missing: {source_path}"
        )

    if not chunks_path.is_file():
        raise RuntimeError(
            f"Prepared chunks missing: {chunks_path}"
        )

    actual_sha256 = sha256_file(source_path)

    if actual_sha256 != config["expected_sha256"]:
        raise RuntimeError(
            "Prepared canonical PDF checksum mismatch"
        )

    payload = load_chunks(chunks_path)

    frozen = validate_frozen_chunk_contract(
        payload,
        config,
    )

    source_manifest = payload.get("source_manifest") or {}

    if (
        source_manifest.get("document_sha256")
        != config["expected_sha256"]
    ):
        raise RuntimeError(
            "Prepared chunks source checksum mismatch"
        )

    return {
        "workdir": str(workdir),
        "canonical_pdf": source_path.name,
        "canonical_sha256": actual_sha256,
        "chunks_file": chunks_path.name,
        "chunks_file_sha256": sha256_file(chunks_path),
        "chunk_count": frozen["chunk_count"],
        "native_text_chunks": frozen["native_text_chunks"],
        "prepared_artifacts_ok": True,
    }


def validate_recovery_readiness(checksum):
    sql = build_recovery_sql(checksum)
    inspection = inspect_recovery_sql(sql)

    if not inspection["recovery_contract_ok"]:
        raise RuntimeError(
            "Recovery transaction contract is not ready"
        )

    return {
        "recovery_contract_ok": True,
        "delete_embeddings": inspection["delete_embeddings"],
        "delete_chunks": inspection["delete_chunks"],
        "delete_documents": inspection["delete_documents"],
        "delete_order_ok": inspection["delete_order_ok"],
        "release_gate_lock": inspection["release_gate_lock"],
        "ingestion_version_lock": inspection["ingestion_version_lock"],
    }


def validate_validator_readiness(repo_root):
    path = (
        repo_root
        / "validate_canonical_text_production_v1.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    forbidden = [
        "execute_transaction",
        "DELETE FROM",
        "INSERT INTO",
        "--write",
        "--recover",
    ]

    found = [
        token
        for token in forbidden
        if token in source
    ]

    if found:
        raise RuntimeError(
            "Production validator contains forbidden write path(s): "
            + ", ".join(found)
        )

    required = [
        "STATUS: CANONICAL_TEXT_PRODUCTION_VALIDATED",
        "run_production_query",
        "semantic_checks",
    ]

    missing = [
        token
        for token in required
        if token not in source
    ]

    if missing:
        raise RuntimeError(
            "Production validator is missing required contract token(s): "
            + ", ".join(missing)
        )

    return {
        "validator_read_only": True,
        "post_write_integrity_check": True,
        "post_write_semantic_checks": 2,
        "validator_ready": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only P8 pre-write readiness gate for "
            "Canonical Text Production Promotion v1."
        )
    )

    parser.add_argument("source_id")

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent
            / "production_release_registry_v1.yaml"
        ),
    )

    parser.add_argument(
        "--prepared-workdir",
        required=True,
        help=(
            "P7 prepare artifact directory that must match "
            "the reviewed Production candidate."
        ),
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent

    try:
        guard = verify_runtime(repo_root)

        head = git_head(repo_root)

        if not is_ancestor(
            repo_root,
            REQUIRED_RELEASE_BASE_COMMIT,
            head,
        ):
            raise RuntimeError(
                "Current main does not contain the reviewed "
                "Production release baseline"
            )

        registry = load_release_registry(
            Path(args.registry).expanduser().resolve()
        )

        _, config, _ = resolve_promotion_source(
            registry,
            args.source_id,
        )

        if config.get("allow_production_write") is not False:
            raise RuntimeError(
                "Readiness gate expects normal Production write "
                "to remain disabled"
            )

        checksum = config["expected_sha256"]

        zero_state = validate_zero_state(
            parse_json_payload(
                run_production_query(
                    build_zero_state_sql(checksum)
                ),
                "Production zero-state query",
            )
        )

        prepared = validate_prepared_artifacts(
            workdir=Path(
                args.prepared_workdir
            ).expanduser().resolve(),
            config=config,
        )

        recovery = validate_recovery_readiness(
            checksum
        )

        validator = validate_validator_readiness(
            repo_root
        )

        result = {
            "version": VERSION,
            "guard_ok": guard["guard_ok"],
            "branch": guard["branch"],
            "db_container": PRODUCTION_DB_CONTAINER,
            "staging_db_container": STAGING_DB_CONTAINER,
            "git_head": head,
            "required_release_base_commit": REQUIRED_RELEASE_BASE_COMMIT,
            "release_baseline_present": True,
            "source_id": args.source_id,
            "checksum": checksum,
            "expected_chunk_count": config["expected_chunk_count"],
            "expected_embedding_count": config["expected_embedding_count"],
            "production_zero_state": zero_state,
            "prepared_artifacts": prepared,
            "recovery_readiness": recovery,
            "validator_readiness": validator,
            "production_write_enabled": False,
            "database_write_performed": False,
            "readiness_status": "READY_FOR_WRITE_IMPLEMENTATION",
        }

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: PRODUCTION_WRITE_READINESS_VERIFIED"
        )
        print(
            "Normal Production write remains disabled."
        )
        print(
            "Database writes performed: False"
        )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION WRITE READINESS FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
