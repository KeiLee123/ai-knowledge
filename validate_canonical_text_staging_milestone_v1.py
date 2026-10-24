#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from ingest_canonical_staging_v1 import (
    load_expected_baseline,
    load_registry,
)
from ingest_canonical_text_staging_v1 import (
    REQUIRED_ROUTE,
    VERSION as TEXT_INGESTION_VERSION,
    resolve_text_source,
)
from run_multimodal_canary_v2 import (
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from validate_staging_retrieval_v2 import (
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    build_retrieval_sql,
    embed_query,
    parse_rows,
    run_staging_query,
)


VALIDATOR_VERSION = "canonical-text-staging-milestone-v1"


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
    )
)::text;
""".strip()


def parse_integrity_payload(text):
    payload = json.loads(text.strip())

    if not isinstance(payload, dict):
        raise RuntimeError("Integrity query did not return a JSON object")

    return payload


def validate_integrity(payload, expected_source):
    errors = []

    document_count = int(payload.get("document_count") or 0)
    chunk_count = int(payload.get("chunk_count") or 0)
    embedding_count = int(payload.get("embedding_count") or 0)
    native_text_chunks = int(payload.get("native_text_chunks") or 0)
    text_primary_chunks = int(payload.get("text_primary_chunks") or 0)
    non_primary = int(payload.get("non_primary_tier_chunks") or 0)
    bad_dimensions = int(payload.get("bad_embedding_dimensions") or 0)

    if document_count != 1:
        errors.append(f"document_count must be 1, got {document_count}")

    if chunk_count <= 0:
        errors.append("chunk_count must be > 0")

    if embedding_count != chunk_count:
        errors.append(
            f"embedding_count {embedding_count} != chunk_count {chunk_count}"
        )

    if native_text_chunks != chunk_count:
        errors.append(
            f"native_text_chunks {native_text_chunks} != chunk_count {chunk_count}"
        )

    if text_primary_chunks != chunk_count:
        errors.append(
            f"text_primary_chunks {text_primary_chunks} != chunk_count {chunk_count}"
        )

    if non_primary != 0:
        errors.append(f"non_primary_tier_chunks must be 0, got {non_primary}")

    if bad_dimensions != 0:
        errors.append(f"bad_embedding_dimensions must be 0, got {bad_dimensions}")

    if payload.get("source_type") != "canonical-drive-text":
        errors.append("source_type must be canonical-drive-text")

    if payload.get("ingestion_version") != TEXT_INGESTION_VERSION:
        errors.append(
            "ingestion_version must be "
            f"{TEXT_INGESTION_VERSION}"
        )

    if payload.get("multimodal") != "false":
        errors.append("multimodal metadata must be false")

    if payload.get("routing_profile") != REQUIRED_ROUTE:
        errors.append(f"routing_profile must be {REQUIRED_ROUTE}")

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


def validate_semantic_rows(rows, expected_terms):
    if not rows:
        raise RuntimeError("Semantic retrieval returned no rows")

    for row in rows:
        if row.get("evidence_origin") != "native_text":
            raise RuntimeError("Semantic result contains non-native_text evidence")

        if row.get("evidence_tier") != "primary":
            raise RuntimeError("Semantic result contains non-primary evidence")

        if row.get("retrieval_role") != "text-primary":
            raise RuntimeError("Semantic result contains non-text-primary role")

    joined = "\n".join(row.get("content") or "" for row in rows).lower()

    missing_terms = [
        term
        for term in expected_terms
        if term.lower() not in joined
    ]

    if missing_terms:
        raise RuntimeError(
            "Semantic retrieval missing expected term(s): "
            + ", ".join(missing_terms)
        )

    return {
        "result_count": len(rows),
        "expected_terms": expected_terms,
        "semantic_ok": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only final Staging milestone validator for "
            "canonical text ingestion."
        )
    )

    parser.add_argument("source_id")
    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--state-root",
        default="/var/lib/jason-os/source-monitor-staging",
    )
    parser.add_argument(
        "--query",
        default=(
            "What fire safety measures and requirements "
            "apply to target buildings?"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--expect-term",
        action="append",
        default=[],
        help="Require this term somewhere in the returned retrieval rows.",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    guard = verify_runtime(repo_root)

    registry = load_registry(Path(args.registry).expanduser().resolve())
    _, config, _ = resolve_text_source(registry, args.source_id)

    baseline = load_expected_baseline(
        Path(args.state_root).expanduser().resolve(),
        args.source_id,
    )
    checksum = baseline["sha256"]

    integrity_sql = build_integrity_sql(checksum)
    integrity_payload = parse_integrity_payload(
        run_staging_query(integrity_sql)
    )
    integrity = validate_integrity(
        integrity_payload,
        config["source"],
    )

    vector = embed_query(args.query, "http://127.0.0.1:8088/embed")
    retrieval_sql = build_retrieval_sql(
        checksum=checksum,
        vector=vector,
        limit=args.limit,
    )
    rows = parse_rows(run_staging_query(retrieval_sql))

    expected_terms = args.expect_term or ["fire", "safety"]
    semantic = validate_semantic_rows(rows, expected_terms)

    print(
        json.dumps(
            {
                "validator_version": VALIDATOR_VERSION,
                "guard_ok": guard["guard_ok"],
                "branch": guard["branch"],
                "db_container": STAGING_DB_CONTAINER,
                "read_only": True,
                "source_id": args.source_id,
                "checksum": checksum,
                "integrity": integrity,
                "semantic": semantic,
                "production_write": False,
                "milestone_status": "VERIFIED",
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print("STATUS: CANONICAL_TEXT_STAGING_MILESTONE_VERIFIED")


if __name__ == "__main__":
    main()
