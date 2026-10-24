#!/usr/bin/env python3

from pathlib import Path

from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)
from promote_canonical_text_production_v1 import (
    FROZEN_INGESTION_VERSION,
    VERSION as RELEASE_GATE_VERSION,
)
from recover_canonical_text_production_v1 import (
    build_post_recovery_sql,
    build_preview_sql,
    build_recovery_sql,
    inspect_recovery_sql,
    validate_post_recovery,
    validate_preview,
    validate_recovery_result,
)


CHECKSUM = (
    "dc3262cc55c5fd79d29f337fd811cdd8"
    "71543f59d795972d9f30f558e313127c"
)


def preview_fixture():
    return {
        "checksum_document_count": 1,
        "recovery_target_count": 1,
        "document_id": 42,
        "source_type": "canonical-drive-text",
        "release_gate": RELEASE_GATE_VERSION,
        "ingestion_version": FROZEN_INGESTION_VERSION,
        "chunk_count": 8,
        "embedding_count": 8,
    }


def test_preview_sql_is_read_only_and_locked():
    sql = build_preview_sql(CHECKSUM)
    lowered = sql.lower()

    assert CHECKSUM in sql
    assert RELEASE_GATE_VERSION in sql
    assert FROZEN_INGESTION_VERSION in sql
    assert "select" in lowered
    assert "delete " not in lowered
    assert "insert " not in lowered
    assert "update " not in lowered
    assert STAGING_DB_CONTAINER not in sql


def test_preview_contract():
    result = validate_preview(
        preview_fixture(),
        CHECKSUM,
    )

    assert result["recovery_target_ok"] is True
    assert result["document_id"] == 42
    assert result["chunk_count"] == 8
    assert result["embedding_count"] == 8


def assert_preview_rejected(key, value):
    payload = preview_fixture()
    payload[key] = value

    try:
        validate_preview(payload, CHECKSUM)
    except RuntimeError:
        return

    raise AssertionError(
        f"Unsafe recovery preview accepted: {key}={value!r}"
    )


def test_preview_rejections():
    assert_preview_rejected(
        "checksum_document_count",
        2,
    )
    assert_preview_rejected(
        "recovery_target_count",
        0,
    )
    assert_preview_rejected(
        "source_type",
        "manual",
    )
    assert_preview_rejected(
        "release_gate",
        "other-release",
    )
    assert_preview_rejected(
        "ingestion_version",
        "other-ingestion",
    )


def test_recovery_transaction_contract():
    sql = build_recovery_sql(CHECKSUM)
    inspection = inspect_recovery_sql(sql)

    assert inspection["recovery_contract_ok"] is True
    assert inspection["delete_embeddings"] is True
    assert inspection["delete_chunks"] is True
    assert inspection["delete_documents"] is True
    assert inspection["delete_order_ok"] is True
    assert inspection["release_gate_lock"] is True
    assert inspection["ingestion_version_lock"] is True
    assert inspection["staging_db_absent"] is True
    assert PRODUCTION_DB_CONTAINER not in sql


def test_recovery_result_contract():
    result = validate_recovery_result(
        {
            "remaining_documents": 0,
            "remaining_chunks": 0,
            "remaining_embeddings": 0,
            "recovery_ok": True,
        }
    )

    assert result["recovery_ok"] is True

    try:
        validate_recovery_result(
            {
                "remaining_documents": 0,
                "remaining_chunks": 0,
                "remaining_embeddings": 1,
                "recovery_ok": True,
            }
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Recovery accepted remaining embedding rows"
        )


def test_post_recovery_contract():
    sql = build_post_recovery_sql(
        CHECKSUM,
        42,
    )

    lowered = sql.lower()

    assert "select" in lowered
    assert "delete " not in lowered
    assert CHECKSUM in sql
    assert "42" in sql

    result = validate_post_recovery(
        {
            "checksum_document_count": 0,
            "document_id_count": 0,
            "chunk_count": 0,
        }
    )

    assert result["post_recovery_ok"] is True


def test_cli_is_source_id_locked():
    source = (
        Path(__file__).resolve().parent
        / "recover_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert 'parser.add_argument("source_id")' in source
    assert '"--checksum"' not in source
    assert "--confirm-production-recovery" in source
    assert "PRODUCTION_DB_CONTAINER" in source
    assert "STAGING_DB_CONTAINER" in source


def main():
    test_preview_sql_is_read_only_and_locked()
    test_preview_contract()
    test_preview_rejections()
    test_recovery_transaction_contract()
    test_recovery_result_contract()
    test_post_recovery_contract()
    test_cli_is_source_id_locked()

    print("Production recovery P3 contract test PASS")
    print("Read-only preview: PASS")
    print("Git-controlled checksum lock: PASS")
    print("Release-gate lock: PASS")
    print("Frozen ingestion lock: PASS")
    print("Delete order embeddings/chunks/document: PASS")
    print("Explicit recovery confirmation: PASS")
    print("Post-recovery zero-row validation: PASS")


if __name__ == "__main__":
    main()
