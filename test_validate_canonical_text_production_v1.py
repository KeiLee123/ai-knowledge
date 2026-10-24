#!/usr/bin/env python3

from validate_canonical_text_production_v1 import (
    FROZEN_INGESTION_VERSION,
    RELEASE_GATE_VERSION,
    build_integrity_sql,
    parse_integrity_payload,
    validate_integrity,
    validate_semantic_rows,
)
from validate_staging_retrieval_v2 import assert_read_only_sql


CHECKSUM = (
    "dc3262cc55c5fd79d29f337fd811cdd8"
    "71543f59d795972d9f30f558e313127c"
)
CANONICAL_SOURCE = "Current/APP/APP145.pdf"


def integrity_fixture():
    return {
        "document_count": 1,
        "document_id": 77,
        "source_type": "canonical-drive-text",
        "ingestion_version": FROZEN_INGESTION_VERSION,
        "release_gate": RELEASE_GATE_VERSION,
        "canonical_sha256": CHECKSUM,
        "multimodal": "false",
        "routing_profile": "legacy-v1",
        "canonical_source": CANONICAL_SOURCE,
        "chunk_count": 8,
        "embedding_count": 8,
        "bad_embedding_dimensions": 0,
        "native_text_chunks": 8,
        "text_primary_chunks": 8,
        "non_primary_tier_chunks": 0,
        "wrong_release_chunks": 0,
        "wrong_ingestion_chunks": 0,
        "multimodal_chunks": 0,
    }


def test_integrity_sql_read_only():
    sql = build_integrity_sql(CHECKSUM)

    assert CHECKSUM in sql
    assert RELEASE_GATE_VERSION in sql
    assert FROZEN_INGESTION_VERSION in sql
    assert_read_only_sql(sql)


def test_integrity_contract():
    import json

    payload = parse_integrity_payload(
        json.dumps(integrity_fixture())
    )

    result = validate_integrity(
        payload,
        checksum=CHECKSUM,
        expected_source=CANONICAL_SOURCE,
        expected_chunks=8,
        expected_embeddings=8,
    )

    assert result["integrity_ok"] is True
    assert result["document_count"] == 1
    assert result["chunk_count"] == 8
    assert result["embedding_count"] == 8
    assert result["native_text_chunks"] == 8
    assert result["text_primary_chunks"] == 8
    assert result["embedding_dimensions"] == 384


def assert_integrity_rejected(key, value):
    payload = integrity_fixture()
    payload[key] = value

    try:
        validate_integrity(
            payload,
            checksum=CHECKSUM,
            expected_source=CANONICAL_SOURCE,
            expected_chunks=8,
            expected_embeddings=8,
        )
    except RuntimeError:
        return

    raise AssertionError(
        f"Invalid Production integrity payload accepted: {key}={value!r}"
    )


def test_integrity_rejections():
    assert_integrity_rejected(
        "document_count",
        2,
    )
    assert_integrity_rejected(
        "chunk_count",
        7,
    )
    assert_integrity_rejected(
        "embedding_count",
        7,
    )
    assert_integrity_rejected(
        "bad_embedding_dimensions",
        1,
    )
    assert_integrity_rejected(
        "release_gate",
        "wrong-release",
    )
    assert_integrity_rejected(
        "ingestion_version",
        "wrong-ingestion",
    )
    assert_integrity_rejected(
        "canonical_sha256",
        "0" * 64,
    )
    assert_integrity_rejected(
        "routing_profile",
        "multimodal-v2",
    )
    assert_integrity_rejected(
        "multimodal",
        "true",
    )
    assert_integrity_rejected(
        "canonical_source",
        "Current/APP/OTHER.pdf",
    )
    assert_integrity_rejected(
        "wrong_release_chunks",
        1,
    )
    assert_integrity_rejected(
        "wrong_ingestion_chunks",
        1,
    )
    assert_integrity_rejected(
        "multimodal_chunks",
        1,
    )


def semantic_rows():
    return [
        {
            "evidence_origin": "native_text",
            "evidence_tier": "primary",
            "retrieval_role": "text-primary",
            "content": (
                "Fire safety measures apply to target buildings."
            ),
        },
        {
            "evidence_origin": "native_text",
            "evidence_tier": "primary",
            "retrieval_role": "text-primary",
            "content": (
                "Building owners may need fire safety improvement works."
            ),
        },
    ]


def test_semantic_contract_for_two_queries():
    first = validate_semantic_rows(
        semantic_rows(),
        expected_terms=["fire", "safety"],
        label="query_a",
    )

    second = validate_semantic_rows(
        semantic_rows(),
        expected_terms=["building", "fire"],
        label="query_b",
    )

    assert first["semantic_ok"] is True
    assert second["semantic_ok"] is True
    assert first["label"] == "query_a"
    assert second["label"] == "query_b"


def test_semantic_rejections():
    rows = semantic_rows()
    rows[0]["retrieval_role"] = "multimodal-primary"

    try:
        validate_semantic_rows(
            rows,
            expected_terms=["fire"],
            label="query_a",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Production semantic validator accepted wrong retrieval role"
        )

    try:
        validate_semantic_rows(
            semantic_rows(),
            expected_terms=["nonexistent-term"],
            label="query_b",
        )
    except RuntimeError:
        return

    raise AssertionError(
        "Production semantic validator accepted missing expected term"
    )


def test_validator_has_no_write_path():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent
        / "validate_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert "execute_transaction" not in source
    assert "DELETE FROM" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "--write" not in source
    assert "--recover" not in source


def main():
    test_integrity_sql_read_only()
    test_integrity_contract()
    test_integrity_rejections()
    test_semantic_contract_for_two_queries()
    test_semantic_rejections()
    test_validator_has_no_write_path()

    print("Production post-write validator P4 contract test PASS")
    print("Read-only integrity SQL: PASS")
    print("Release metadata lock: PASS")
    print("8/8 chunk embedding contract: PASS")
    print("384-dimension embedding contract: PASS")
    print("Two semantic query contract: PASS")
    print("Write path absent: PASS")


if __name__ == "__main__":
    main()
