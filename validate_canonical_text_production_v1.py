#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path

from production_release_source_v1 import (
    load_release_registry,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from promote_canonical_text_production_v1 import (
    FROZEN_INGESTION_VERSION,
    REQUIRED_ROUTE,
    VERSION as RELEASE_GATE_VERSION,
    resolve_promotion_source,
)
from production_read_only_retrieval_v1 import (
    DEFAULT_EMBED_URL,
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    assert_read_only_sql,
    build_retrieval_sql,
    embed_query,
    parse_rows,
)


VALIDATOR_VERSION = "canonical-text-production-validator-v1"


def run_production_query(sql):
    if PRODUCTION_DB_CONTAINER == STAGING_DB_CONTAINER:
        raise RuntimeError(
            "Production DB equals Staging DB"
        )

    assert_read_only_sql(sql)

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
            "-F",
            "\t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Production read-only query failed"
        )

    return result.stdout


def build_integrity_sql(checksum):
    return f"""
SELECT json_build_object(
    'document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'document_id', (
        SELECT MIN(id)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'source_type', (
        SELECT MIN(source_type)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'ingestion_version', (
        SELECT MIN(metadata->>'ingestion_version')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'release_gate', (
        SELECT MIN(metadata->>'release_gate')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'canonical_sha256', (
        SELECT MIN(metadata->>'canonical_sha256')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'multimodal', (
        SELECT MIN(metadata->>'multimodal')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'routing_profile', (
        SELECT MIN(metadata->>'routing_profile')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'canonical_source', (
        SELECT MIN(metadata->>'canonical_source')
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
          AND e.provider = 'local'
          AND e.model = '{EMBED_MODEL}'
    ),
    'bad_embedding_dimensions', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
          ON c.id = e.chunk_id
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND e.provider = 'local'
          AND e.model = '{EMBED_MODEL}'
          AND COALESCE(e.dimensions, -1) <> {EXPECTED_DIMENSIONS}
    ),
    'native_text_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND c.metadata->>'evidence_origin' = 'native_text'
    ),
    'text_primary_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND c.metadata->>'retrieval_role' = 'text-primary'
    ),
    'non_primary_tier_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'evidence_tier', '') <> 'primary'
    ),
    'wrong_release_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'release_gate', '') <> '{RELEASE_GATE_VERSION}'
    ),
    'wrong_ingestion_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'ingestion_version', '') <> '{FROZEN_INGESTION_VERSION}'
    ),
    'multimodal_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'multimodal', '') <> 'false'
    )
)::text;
""".strip()


def parse_integrity_payload(text):
    payload = json.loads(text.strip())

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Production integrity query did not return a JSON object"
        )

    return payload


def validate_integrity(
    payload,
    *,
    checksum,
    expected_source,
    expected_chunks,
    expected_embeddings,
):
    errors = []

    document_count = int(payload.get("document_count") or 0)
    chunk_count = int(payload.get("chunk_count") or 0)
    embedding_count = int(payload.get("embedding_count") or 0)
    native_text_chunks = int(payload.get("native_text_chunks") or 0)
    text_primary_chunks = int(payload.get("text_primary_chunks") or 0)
    non_primary = int(payload.get("non_primary_tier_chunks") or 0)
    bad_dimensions = int(payload.get("bad_embedding_dimensions") or 0)
    wrong_release_chunks = int(payload.get("wrong_release_chunks") or 0)
    wrong_ingestion_chunks = int(payload.get("wrong_ingestion_chunks") or 0)
    multimodal_chunks = int(payload.get("multimodal_chunks") or 0)

    if document_count != 1:
        errors.append(
            f"document_count must be 1, got {document_count}"
        )

    if chunk_count != expected_chunks:
        errors.append(
            f"chunk_count {chunk_count} != expected {expected_chunks}"
        )

    if embedding_count != expected_embeddings:
        errors.append(
            "embedding_count "
            f"{embedding_count} != expected {expected_embeddings}"
        )

    if embedding_count != chunk_count:
        errors.append(
            f"embedding_count {embedding_count} != chunk_count {chunk_count}"
        )

    if native_text_chunks != expected_chunks:
        errors.append(
            "native_text_chunks "
            f"{native_text_chunks} != expected {expected_chunks}"
        )

    if text_primary_chunks != expected_chunks:
        errors.append(
            "text_primary_chunks "
            f"{text_primary_chunks} != expected {expected_chunks}"
        )

    if non_primary != 0:
        errors.append(
            f"non_primary_tier_chunks must be 0, got {non_primary}"
        )

    if bad_dimensions != 0:
        errors.append(
            f"bad_embedding_dimensions must be 0, got {bad_dimensions}"
        )

    if wrong_release_chunks != 0:
        errors.append(
            f"wrong_release_chunks must be 0, got {wrong_release_chunks}"
        )

    if wrong_ingestion_chunks != 0:
        errors.append(
            "wrong_ingestion_chunks must be 0, "
            f"got {wrong_ingestion_chunks}"
        )

    if multimodal_chunks != 0:
        errors.append(
            f"multimodal_chunks must be 0, got {multimodal_chunks}"
        )

    if payload.get("source_type") != "canonical-drive-text":
        errors.append(
            "source_type must be canonical-drive-text"
        )

    if payload.get("ingestion_version") != FROZEN_INGESTION_VERSION:
        errors.append(
            "ingestion_version must be "
            f"{FROZEN_INGESTION_VERSION}"
        )

    if payload.get("release_gate") != RELEASE_GATE_VERSION:
        errors.append(
            f"release_gate must be {RELEASE_GATE_VERSION}"
        )

    if payload.get("canonical_sha256") != checksum:
        errors.append(
            "canonical_sha256 does not match the Git-controlled checksum"
        )

    if payload.get("multimodal") != "false":
        errors.append(
            "multimodal metadata must be false"
        )

    if payload.get("routing_profile") != REQUIRED_ROUTE:
        errors.append(
            f"routing_profile must be {REQUIRED_ROUTE}"
        )

    if payload.get("canonical_source") != expected_source:
        errors.append(
            "canonical_source mismatch: "
            f"{payload.get('canonical_source')!r} != {expected_source!r}"
        )

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "document_id": payload.get("document_id"),
        "document_count": document_count,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "native_text_chunks": native_text_chunks,
        "text_primary_chunks": text_primary_chunks,
        "embedding_dimensions": EXPECTED_DIMENSIONS,
        "integrity_ok": True,
    }


def validate_semantic_rows(
    rows,
    *,
    expected_terms,
    label,
):
    if not rows:
        raise RuntimeError(
            f"{label} semantic retrieval returned no rows"
        )

    for row in rows:
        if row.get("evidence_origin") != "native_text":
            raise RuntimeError(
                f"{label} contains non-native_text evidence"
            )

        if row.get("evidence_tier") != "primary":
            raise RuntimeError(
                f"{label} contains non-primary evidence"
            )

        if row.get("retrieval_role") != "text-primary":
            raise RuntimeError(
                f"{label} contains non-text-primary role"
            )

    joined = "\n".join(
        row.get("content") or ""
        for row in rows
    ).lower()

    missing_terms = [
        term
        for term in expected_terms
        if term.lower() not in joined
    ]

    if missing_terms:
        raise RuntimeError(
            f"{label} missing expected term(s): "
            + ", ".join(missing_terms)
        )

    return {
        "label": label,
        "result_count": len(rows),
        "expected_terms": expected_terms,
        "semantic_ok": True,
    }


def run_semantic_check(
    *,
    checksum,
    query,
    expected_terms,
    limit,
    embed_url,
    label,
):
    vector = embed_query(
        query,
        embed_url,
    )

    sql = build_retrieval_sql(
        checksum=checksum,
        vector=vector,
        limit=limit,
    )

    rows = parse_rows(
        run_production_query(sql)
    )

    return validate_semantic_rows(
        rows,
        expected_terms=expected_terms,
        label=label,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Production post-write validator for "
            "Canonical Text Production Promotion v1."
        )
    )

    parser.add_argument("source_id")

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "production_release_registry_v1.yaml"
        ),
    )

    parser.add_argument(
        "--query-a",
        default=(
            "What is APP-145 about and what fire safety "
            "requirements does it address?"
        ),
    )

    parser.add_argument(
        "--query-b",
        default=(
            "What fire safety improvement works or requirements "
            "are described for buildings?"
        ),
    )

    parser.add_argument(
        "--expect-a",
        action="append",
        default=[],
        help=(
            "Require this term somewhere in semantic query A results. "
            "May be repeated."
        ),
    )

    parser.add_argument(
        "--expect-b",
        action="append",
        default=[],
        help=(
            "Require this term somewhere in semantic query B results. "
            "May be repeated."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--embed-url",
        default=DEFAULT_EMBED_URL,
    )

    args = parser.parse_args()

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

        integrity = validate_integrity(
            parse_integrity_payload(
                run_production_query(
                    build_integrity_sql(checksum)
                )
            ),
            checksum=checksum,
            expected_source=config["source"],
            expected_chunks=config["expected_chunk_count"],
            expected_embeddings=config["expected_embedding_count"],
        )

        semantic_a = run_semantic_check(
            checksum=checksum,
            query=args.query_a,
            expected_terms=args.expect_a or ["fire", "safety"],
            limit=args.limit,
            embed_url=args.embed_url,
            label="query_a",
        )

        semantic_b = run_semantic_check(
            checksum=checksum,
            query=args.query_b,
            expected_terms=args.expect_b or ["fire", "safety"],
            limit=args.limit,
            embed_url=args.embed_url,
            label="query_b",
        )

        print(
            json.dumps(
                {
                    "validator_version": VALIDATOR_VERSION,
                    "guard_ok": guard["guard_ok"],
                    "branch": guard["branch"],
                    "db_container": PRODUCTION_DB_CONTAINER,
                    "read_only": True,
                    "source_id": args.source_id,
                    "checksum": checksum,
                    "integrity": integrity,
                    "semantic_checks": [
                        semantic_a,
                        semantic_b,
                    ],
                    "production_write": False,
                    "production_validation_status": "VERIFIED",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: CANONICAL_TEXT_PRODUCTION_VALIDATED"
        )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION VALIDATION FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
