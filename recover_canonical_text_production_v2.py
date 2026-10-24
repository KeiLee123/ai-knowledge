#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

from canonical_text_production_v2 import (
    run_production_query,
)
from ingest_manifest_v2 import (
    sql_quote,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from production_release_contract_v2 import (
    FROZEN_INGESTION_VERSION,
    RELEASE_GATE_VERSION,
    load_release_registry,
    resolve_release_source,
)


VERSION = "canonical-text-production-recovery-v2"


def build_preview_sql(
    checksum: str,
    release_id: str,
) -> str:
    checksum = sql_quote(
        checksum
    )
    release_id = sql_quote(
        release_id
    )

    return f"""
SELECT json_build_object(
    'checksum_document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'recovery_target_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
          AND source_type = 'canonical-drive-text'
          AND metadata->>'release_gate' = '{RELEASE_GATE_VERSION}'
          AND metadata->>'release_id' = '{release_id}'
          AND metadata->>'ingestion_version' = '{FROZEN_INGESTION_VERSION}'
    ),
    'document_id', (
        SELECT MIN(id)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
          AND source_type = 'canonical-drive-text'
          AND metadata->>'release_gate' = '{RELEASE_GATE_VERSION}'
          AND metadata->>'release_id' = '{release_id}'
          AND metadata->>'ingestion_version' = '{FROZEN_INGESTION_VERSION}'
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


def validate_preview(
    payload: dict,
) -> dict:
    document_count = int(
        payload.get(
            "checksum_document_count"
        )
        or 0
    )
    target_count = int(
        payload.get(
            "recovery_target_count"
        )
        or 0
    )

    if document_count != 1:
        raise RuntimeError(
            "checksum_document_count "
            f"must be 1, got {document_count}"
        )

    if target_count != 1:
        raise RuntimeError(
            "recovery_target_count "
            f"must be 1, got {target_count}"
        )

    if (
        payload.get(
            "document_id"
        )
        is None
    ):
        raise RuntimeError(
            "document_id is missing"
        )

    return {
        "document_id":
            int(
                payload[
                    "document_id"
                ]
            ),
        "chunk_count":
            int(
                payload.get(
                    "chunk_count"
                )
                or 0
            ),
        "embedding_count":
            int(
                payload.get(
                    "embedding_count"
                )
                or 0
            ),
        "recovery_target_ok":
            True,
    }


def build_recovery_sql(
    checksum: str,
    release_id: str,
) -> str:
    checksum = sql_quote(
        checksum
    )
    release_id = sql_quote(
        release_id
    )

    return f"""
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE recovery_target_ids ON COMMIT DROP AS
SELECT d.id AS document_id
FROM documents d
WHERE d.checksum_sha256 = '{checksum}'
  AND d.source_type = 'canonical-drive-text'
  AND d.metadata->>'release_gate' = '{RELEASE_GATE_VERSION}'
  AND d.metadata->>'release_id' = '{release_id}'
  AND d.metadata->>'ingestion_version' = '{FROZEN_INGESTION_VERSION}'
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
  AND d.checksum_sha256 = '{checksum}'
  AND d.metadata->>'release_gate' = '{RELEASE_GATE_VERSION}'
  AND d.metadata->>'release_id' = '{release_id}'
  AND d.metadata->>'ingestion_version' = '{FROZEN_INGESTION_VERSION}';

SELECT json_build_object(
    'remaining_documents', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'recovery_ok', true
)::text;

COMMIT;
""".strip() + "\n"


def inspect_recovery_sql(
    sql: str,
) -> dict:
    normalized = sql.lower()

    required = {
        "begin":
            normalized.count(
                "begin;"
            )
            == 1,
        "commit":
            normalized.count(
                "commit;"
            )
            == 1,
        "on_error_stop":
            "\\set on_error_stop on"
            in normalized,
        "delete_embeddings":
            "delete from embeddings"
            in normalized,
        "delete_chunks":
            "delete from chunks"
            in normalized,
        "delete_documents":
            "delete from documents"
            in normalized,
        "release_gate_lock":
            RELEASE_GATE_VERSION.lower()
            in normalized,
        "ingestion_version_lock":
            FROZEN_INGESTION_VERSION.lower()
            in normalized,
        "release_id_lock":
            "metadata->>'release_id'"
            in normalized,
        "staging_db_absent":
            STAGING_DB_CONTAINER.lower()
            not in normalized,
    }

    order = [
        normalized.find(
            "delete from embeddings"
        ),
        normalized.find(
            "delete from chunks"
        ),
        normalized.find(
            "delete from documents"
        ),
    ]

    required[
        "delete_order_ok"
    ] = (
        all(
            index >= 0
            for index in order
        )
        and order
        == sorted(order)
    )

    return {
        **required,
        "recovery_contract_ok":
            all(
                required.values()
            ),
    }


def execute_recovery(
    sql: str,
) -> dict:
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
            or "Production v2 recovery failed"
        )

    lines = [
        line.strip()
        for line
        in result.stdout.splitlines()
        if line.strip().startswith(
            "{"
        )
    ]

    if len(lines) != 1:
        raise RuntimeError(
            "Recovery did not return exactly "
            "one JSON verification object"
        )

    return json.loads(
        lines[0]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Break-glass Production recovery "
            "for Generic Production Promotion v2."
        )
    )

    parser.add_argument(
        "source_id"
    )

    mode = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--preview",
        action="store_true",
    )

    mode.add_argument(
        "--recover",
        action="store_true",
    )

    parser.add_argument(
        "--confirm-production-recovery",
        action="store_true",
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

    if (
        args.confirm_production_recovery
        and not args.recover
    ):
        raise SystemExit(
            "--confirm-production-recovery "
            "requires --recover"
        )

    if (
        args.recover
        and not args.confirm_production_recovery
    ):
        raise SystemExit(
            "--recover requires "
            "--confirm-production-recovery"
        )

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    try:
        guard = verify_runtime(
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
            )
        )

        checksum = config[
            "expected_sha256"
        ]
        release_id = config[
            "release_id"
        ]

        preview = validate_preview(
            json.loads(
                run_production_query(
                    build_preview_sql(
                        checksum,
                        release_id,
                    )
                ).strip()
            )
        )

        if args.preview:
            print(
                json.dumps(
                    {
                        "version":
                            VERSION,
                        "guard_ok":
                            guard[
                                "guard_ok"
                            ],
                        "read_only":
                            True,
                        "source_id":
                            args.source_id,
                        "release_id":
                            release_id,
                        "preview":
                            preview,
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
                "PRODUCTION_V2_RECOVERY_PREVIEW_READY"
            )
            return

        sql = build_recovery_sql(
            checksum,
            release_id,
        )

        inspection = (
            inspect_recovery_sql(
                sql
            )
        )

        if not inspection[
            "recovery_contract_ok"
        ]:
            raise RuntimeError(
                "Recovery transaction "
                "contract failed"
            )

        result = execute_recovery(
            sql
        )

        if (
            int(
                result.get(
                    "remaining_documents"
                )
                or 0
            )
            != 0
        ):
            raise RuntimeError(
                "Recovery left Production "
                "document rows"
            )

        print(
            json.dumps(
                {
                    "version":
                        VERSION,
                    "source_id":
                        args.source_id,
                    "release_id":
                        release_id,
                    "preview":
                        preview,
                    "transaction":
                        inspection,
                    "result":
                        result,
                    "database_write_performed":
                        True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "PRODUCTION_V2_RECOVERY_COMPLETE"
        )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION V2 RECOVERY "
            "FAILED: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


if __name__ == "__main__":
    main()
