#!/usr/bin/env python3

from validate_canonical_text_staging_milestone_v1 import (
    build_integrity_sql,
    parse_integrity_payload,
    validate_integrity,
    validate_semantic_rows,
)
from validate_staging_retrieval_v2 import (
    assert_read_only_sql,
)


CHECKSUM = "a" * 64
CANONICAL_SOURCE = "Current/APP/APP145.pdf"


def valid_integrity_payload():
    return {
        "document_count": 1,
        "document_id": 2,
        "source_type": "canonical-drive-text",
        "ingestion_version": "canonical-text-ingestion-v1",
        "multimodal": "false",
        "routing_profile": "legacy-v1",
        "canonical_source": CANONICAL_SOURCE,
        "chunk_count": 8,
        "embedding_count": 8,
        "bad_embedding_dimensions": 0,
        "native_text_chunks": 8,
        "text_primary_chunks": 8,
        "non_primary_tier_chunks": 0,
    }


def test_integrity_sql_read_only():
    sql = build_integrity_sql(CHECKSUM)

    assert CHECKSUM in sql
    assert "SELECT" in sql
    assert_read_only_sql(sql)


def test_integrity_parser_and_validator():
    import json

    payload = parse_integrity_payload(
        json.dumps(valid_integrity_payload())
    )

    result = validate_integrity(
        payload,
        CANONICAL_SOURCE,
    )

    assert result["integrity_ok"] is True
    assert result["document_count"] == 1
    assert result["chunk_count"] == 8
    assert result["embedding_count"] == 8


def test_integrity_rejects_bad_counts():
    payload = valid_integrity_payload()
    payload["embedding_count"] = 7

    try:
        validate_integrity(
            payload,
            CANONICAL_SOURCE,
        )
    except RuntimeError:
        return

    raise AssertionError(
        "Integrity validator accepted missing embedding"
    )


def test_semantic_contract():
    rows = [
        {
            "evidence_origin": "native_text",
            "evidence_tier": "primary",
            "retrieval_role": "text-primary",
            "content": (
                "Fire safety measures apply to target buildings."
            ),
        }
    ]

    result = validate_semantic_rows(
        rows,
        ["fire", "safety"],
    )

    assert result["semantic_ok"] is True
    assert result["result_count"] == 1


def test_semantic_rejects_wrong_role():
    rows = [
        {
            "evidence_origin": "native_text",
            "evidence_tier": "primary",
            "retrieval_role": "multimodal-primary",
            "content": "Fire safety",
        }
    ]

    try:
        validate_semantic_rows(
            rows,
            ["fire"],
        )
    except RuntimeError:
        return

    raise AssertionError(
        "Semantic validator accepted wrong retrieval role"
    )


def main():
    test_integrity_sql_read_only()
    test_integrity_parser_and_validator()
    test_integrity_rejects_bad_counts()
    test_semantic_contract()
    test_semantic_rejects_wrong_role()

    print(
        "Canonical text staging milestone validator test PASS"
    )
    print("Read-only integrity SQL: PASS")
    print("Document/chunk/embedding integrity: PASS")
    print("Text metadata contract: PASS")
    print("Semantic retrieval contract: PASS")


if __name__ == "__main__":
    main()
