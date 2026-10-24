#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

from ingest_manifest_v2 import run_db_query, sql_quote
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from canonical_text_release_contract_v1 import (
    FROZEN_INGESTION_VERSION,
)
from production_release_source_v1 import (
    load_release_registry,
)
from promote_canonical_text_production_v1 import (
    VERSION as RELEASE_GATE_VERSION,
    resolve_promotion_source,
)


VERSION = "canonical-text-production-recovery-v1"


def build_preview_sql(checksum):
    checksum_sql = sql_quote(checksum)
    release_sql = sql_quote(RELEASE_GATE_VERSION)
    ingestion_sql = sql_quote(FROZEN_INGESTION_VERSION)

    return f"""
SELECT json_build_object(
    'checksum_document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'recovery_target_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
          AND source_type = 'canonical-drive-text'
          AND metadata->>'release_gate' = '{release_sql}'
          AND metadata->>'ingestion_version' = '{ingestion_sql}'
    ),
    'document_id', (
        SELECT MIN(id)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
          AND source_type = 'canonical-drive-text'
          AND metadata->>'release_gate' = '{release_sql}'
          AND metadata->>'ingestion_version' = '{ingestion_sql}'
    ),
    'source_type', (
        SELECT MIN(source_type)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'release_gate', (
        SELECT MIN(metadata->>'release_gate')
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'ingestion_version', (
        SELECT MIN(metadata->>'ingestion_version')
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'chunk_count', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum_sql}'
    ),
    'embedding_count', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
          ON c.id = e.chunk_id
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum_sql}'
    )
)::text;
""".strip()


def parse_json_result(text, label):
    payload = json.loads(text.strip())

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{label} query did not return a JSON object"
        )

    return payload


def validate_preview(payload, checksum):
    checksum_document_count = int(
        payload.get("checksum_document_count") or 0
    )
    recovery_target_count = int(
        payload.get("recovery_target_count") or 0
    )

    errors = []

    if checksum_document_count != 1:
        errors.append(
            "checksum_document_count must be exactly 1, "
            f"got {checksum_document_count}"
        )

    if recovery_target_count != 1:
        errors.append(
            "recovery_target_count must be exactly 1, "
            f"got {recovery_target_count}"
        )

    if payload.get("source_type") != "canonical-drive-text":
        errors.append(
            "source_type must be canonical-drive-text"
        )

    if payload.get("release_gate") != RELEASE_GATE_VERSION:
        errors.append(
            "release_gate does not match Production promotion v1"
        )

    if (
        payload.get("ingestion_version")
        != FROZEN_INGESTION_VERSION
    ):
        errors.append(
            "ingestion_version does not match the frozen contract"
        )

    document_id = payload.get("document_id")

    if document_id is None:
        errors.append("document_id is missing")

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "checksum": checksum,
        "document_id": int(document_id),
        "chunk_count": int(
            payload.get("chunk_count") or 0
        ),
        "embedding_count": int(
            payload.get("embedding_count") or 0
        ),
        "release_gate": RELEASE_GATE_VERSION,
        "ingestion_version": FROZEN_INGESTION_VERSION,
        "recovery_target_ok": True,
    }


def build_recovery_sql(checksum):
    checksum_sql = sql_quote(checksum)
    release_sql = sql_quote(RELEASE_GATE_VERSION)
    ingestion_sql = sql_quote(FROZEN_INGESTION_VERSION)

    return f"""
\\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE recovery_target_ids ON COMMIT DROP AS
SELECT d.id AS document_id
FROM documents d
WHERE d.checksum_sha256 = '{checksum_sql}'
  AND d.source_type = 'canonical-drive-text'
  AND d.metadata->>'release_gate' = '{release_sql}'
  AND d.metadata->>'ingestion_version' = '{ingestion_sql}'
FOR UPDATE;

DO $$
DECLARE
    target_count integer;
BEGIN
    SELECT COUNT(*)
      INTO target_count
      FROM recovery_target_ids;

    IF target_count <> 1 THEN
        RAISE EXCEPTION
            'Recovery target count must be exactly 1, got %',
            target_count;
    END IF;
END
$$;

CREATE TEMP TABLE recovery_chunk_ids ON COMMIT DROP AS
SELECT c.id AS chunk_id
FROM chunks c
JOIN recovery_target_ids t
  ON c.document_id = t.document_id;

DELETE FROM embeddings e
USING recovery_chunk_ids r
WHERE e.chunk_id = r.chunk_id;

DELETE FROM chunks c
USING recovery_target_ids t
WHERE c.document_id = t.document_id;

DELETE FROM documents d
USING recovery_target_ids t
WHERE d.id = t.document_id
  AND d.checksum_sha256 = '{checksum_sql}'
  AND d.source_type = 'canonical-drive-text'
  AND d.metadata->>'release_gate' = '{release_sql}'
  AND d.metadata->>'ingestion_version' = '{ingestion_sql}';

DO $$
DECLARE
    remaining_documents integer;
BEGIN
    SELECT COUNT(*)
      INTO remaining_documents
      FROM documents
     WHERE checksum_sha256 = '{checksum_sql}';

    IF remaining_documents <> 0 THEN
        RAISE EXCEPTION
            'Recovery left % document(s) for checksum',
            remaining_documents;
    END IF;
END
$$;

SELECT json_build_object(
    'remaining_documents', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'remaining_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN recovery_target_ids t
          ON c.document_id = t.document_id
    ),
    'remaining_embeddings', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN recovery_chunk_ids r
          ON e.chunk_id = r.chunk_id
    ),
    'recovery_ok', true
)::text;

COMMIT;
""".strip() + "\n"


def inspect_recovery_sql(sql):
    normalized = sql.lower()

    required = {
        "begin": normalized.count("begin;") == 1,
        "commit": normalized.count("commit;") == 1,
        "on_error_stop": "\\set on_error_stop on" in normalized,
        "delete_embeddings": "delete from embeddings" in normalized,
        "delete_chunks": "delete from chunks" in normalized,
        "delete_documents": "delete from documents" in normalized,
        "release_gate_lock": (
            "metadata->>'release_gate'" in normalized
            and RELEASE_GATE_VERSION.lower() in normalized
        ),
        "ingestion_version_lock": (
            "metadata->>'ingestion_version'" in normalized
            and FROZEN_INGESTION_VERSION.lower() in normalized
        ),
        "staging_db_absent": STAGING_DB_CONTAINER.lower() not in normalized,
    }

    order = [
        normalized.find("delete from embeddings"),
        normalized.find("delete from chunks"),
        normalized.find("delete from documents"),
    ]

    delete_order_ok = (
        all(index >= 0 for index in order)
        and order == sorted(order)
    )

    required["delete_order_ok"] = delete_order_ok

    return {
        **required,
        "recovery_contract_ok": all(required.values()),
    }


def execute_recovery_transaction(sql):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            PRODUCTION_DB_CONTAINER,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Production recovery transaction failed"
        )

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("{")
    ]

    if len(lines) != 1:
        raise RuntimeError(
            "Recovery transaction did not return exactly one "
            "verification JSON object"
        )

    return parse_json_result(
        lines[0],
        "Recovery transaction",
    )


def validate_recovery_result(payload):
    remaining_documents = int(
        payload.get("remaining_documents") or 0
    )
    remaining_chunks = int(
        payload.get("remaining_chunks") or 0
    )
    remaining_embeddings = int(
        payload.get("remaining_embeddings") or 0
    )

    if (
        remaining_documents != 0
        or remaining_chunks != 0
        or remaining_embeddings != 0
        or payload.get("recovery_ok") is not True
    ):
        raise RuntimeError(
            "Recovery zero-row verification failed"
        )

    return {
        "remaining_documents": 0,
        "remaining_chunks": 0,
        "remaining_embeddings": 0,
        "recovery_ok": True,
    }


def build_post_recovery_sql(checksum, document_id):
    checksum_sql = sql_quote(checksum)

    return f"""
SELECT json_build_object(
    'checksum_document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum_sql}'
    ),
    'document_id_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE id = {int(document_id)}
    ),
    'chunk_count', (
        SELECT COUNT(*)
        FROM chunks
        WHERE document_id = {int(document_id)}
    )
)::text;
""".strip()


def validate_post_recovery(payload):
    values = {
        "checksum_document_count": int(
            payload.get("checksum_document_count") or 0
        ),
        "document_id_count": int(
            payload.get("document_id_count") or 0
        ),
        "chunk_count": int(
            payload.get("chunk_count") or 0
        ),
    }

    if any(values.values()):
        raise RuntimeError(
            "Post-recovery read-only verification found remaining rows"
        )

    return {
        **values,
        "post_recovery_ok": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Checksum-locked Production recovery for a canonical "
            "text promotion. Preview is read-only. Recovery requires "
            "explicit confirmation and deletes only the exact "
            "Git-controlled release candidate."
        )
    )

    parser.add_argument("source_id")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preview",
        action="store_true",
        help="Read-only preview of the exact recovery target.",
    )
    mode.add_argument(
        "--recover",
        action="store_true",
        help="Execute the checksum-locked recovery transaction.",
    )

    parser.add_argument(
        "--confirm-production-recovery",
        action="store_true",
        help="Required together with --recover.",
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "production_release_registry_v1.yaml"
        ),
    )

    args = parser.parse_args()

    if args.confirm_production_recovery and not args.recover:
        raise SystemExit(
            "--confirm-production-recovery requires --recover"
        )

    if args.recover and not args.confirm_production_recovery:
        raise SystemExit(
            "--recover requires --confirm-production-recovery"
        )

    repo_root = Path(__file__).resolve().parent

    try:
        guard = verify_runtime(repo_root)
        registry = load_release_registry(
            Path(args.registry).expanduser().resolve()
        )
        _, config, _ = resolve_promotion_source(
            registry,
            args.source_id,
        )

        checksum = config["expected_sha256"]

        preview_payload = parse_json_result(
            run_db_query(
                build_preview_sql(checksum),
                PRODUCTION_DB_CONTAINER,
            ),
            "Recovery preview",
        )
        preview = validate_preview(
            preview_payload,
            checksum,
        )

        print(
            json.dumps(
                {
                    "version": VERSION,
                    "mode": (
                        "recover"
                        if args.recover
                        else "preview"
                    ),
                    "guard_ok": guard["guard_ok"],
                    "branch": guard["branch"],
                    "db_container": PRODUCTION_DB_CONTAINER,
                    "source_id": args.source_id,
                    "target": preview,
                    "production_recovery_requested": bool(
                        args.recover
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        if args.preview:
            print()
            print("STATUS: PRODUCTION_RECOVERY_PREVIEW_READY")
            print("No database mutation was executed.")
            return

        sql = build_recovery_sql(checksum)
        inspection = inspect_recovery_sql(sql)

        print()
        print("RECOVERY_TRANSACTION")
        print(
            json.dumps(
                inspection,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not inspection["recovery_contract_ok"]:
            raise RuntimeError(
                "Generated recovery transaction failed "
                "structural validation"
            )

        transaction_result = validate_recovery_result(
            execute_recovery_transaction(sql)
        )

        post_payload = parse_json_result(
            run_db_query(
                build_post_recovery_sql(
                    checksum,
                    preview["document_id"],
                ),
                PRODUCTION_DB_CONTAINER,
            ),
            "Post-recovery verification",
        )
        post = validate_post_recovery(post_payload)

        print()
        print(
            json.dumps(
                {
                    "transaction_result": transaction_result,
                    "post_recovery": post,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print("STATUS: PRODUCTION_RECOVERY_VERIFIED")

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION RECOVERY FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
