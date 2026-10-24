#!/usr/bin/env python3

import json
import tempfile
from pathlib import Path

from ingest_manifest_v2 import inspect_transaction_sql
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)
from promote_canonical_text_production_v1 import (
    FROZEN_INGESTION_VERSION,
    REQUIRED_ROUTE,
    VERSION,
    build_production_transaction_sql,
    production_document_metadata,
    resolve_promotion_source,
    validate_frozen_chunk_contract,
    validate_promotion_config,
    verify_canonical_download,
)


CHECKSUM = (
    "dc3262cc55c5fd79d29f337fd811cdd8"
    "71543f59d795972d9f30f558e313127c"
)


def config_fixture():
    return {
        "enabled": True,
        "controller_environment": "production",
        "remote": "gdrive-bd-write:",
        "source": "Current/APP/APP145.pdf",
        "db_container": PRODUCTION_DB_CONTAINER,
        "required_route": REQUIRED_ROUTE,
        "frozen_ingestion_version": FROZEN_INGESTION_VERSION,
        "expected_sha256": CHECKSUM,
        "expected_chunk_count": 2,
        "expected_embedding_count": 2,
        "document_type": "official-regulatory",
        "language": "en",
        "allow_production_write": False,
    }


def registry_fixture():
    return {
        "source_registry_version": 1,
        "defaults": {
            "jurisdiction": "HK",
        },
        "sources": {
            "BD_PNAP_APP145": {
                "enabled": True,
                "authority_code": "BD",
                "source_type": "official-document",
                "document_code": "APP-145",
                "title": "Fire Safety (Buildings) Ordinance Cap. 572",
                "canonical_url": "https://www.bd.gov.hk/example.pdf",
                "domain": "building-control",
                "topic": "fire-safety-buildings",
                "canonical_text_production_promotion": config_fixture(),
            },
        },
    }


def chunks_fixture():
    return {
        "schema_version": "retrieval-chunks-v2",
        "source_manifest": {
            "document_name": "APP145.pdf",
            "document_sha256": CHECKSUM,
            "sha256": "b" * 64,
        },
        "summary": {
            "chunk_count": 2,
            "counts_by_origin": {
                "native_text": 2,
            },
        },
        "chunks": [
            {
                "chunk_index": 0,
                "content": "Fire safety requirements for buildings.",
                "page_start": 1,
                "page_end": 1,
                "metadata": {
                    "evidence_origin": "native_text",
                    "evidence_tier": "primary",
                    "modality": "text",
                    "derived": False,
                },
            },
            {
                "chunk_index": 1,
                "content": "Means of escape and fire resisting construction.",
                "page_start": 2,
                "page_end": 2,
                "metadata": {
                    "evidence_origin": "native_text",
                    "evidence_tier": "primary",
                    "modality": "text",
                    "derived": False,
                },
            },
        ],
    }


def test_registry_contract():
    source, config, defaults = resolve_promotion_source(
        registry_fixture(),
        "BD_PNAP_APP145",
    )

    assert source["document_code"] == "APP-145"
    assert config["db_container"] == PRODUCTION_DB_CONTAINER
    assert config["source"] == "Current/APP/APP145.pdf"
    assert config["required_route"] == "legacy-v1"
    assert config["expected_sha256"] == CHECKSUM
    assert config["expected_chunk_count"] == 2
    assert defaults["jurisdiction"] == "HK"


def assert_config_rejected(key, value):
    config = config_fixture()
    config[key] = value

    try:
        validate_promotion_config(config)
    except RuntimeError:
        return

    raise AssertionError(
        f"Unsafe Production promotion config accepted: {key}={value!r}"
    )


def test_config_safety_contract():
    assert_config_rejected(
        "controller_environment",
        "staging",
    )
    assert_config_rejected(
        "db_container",
        STAGING_DB_CONTAINER,
    )
    assert_config_rejected(
        "db_container",
        "arbitrary-db",
    )
    assert_config_rejected(
        "source",
        "_Staging_Incoming/APP/APP145.pdf",
    )
    assert_config_rejected(
        "required_route",
        "multimodal-v2",
    )
    assert_config_rejected(
        "frozen_ingestion_version",
        "v2",
    )
    assert_config_rejected(
        "expected_sha256",
        "not-a-checksum",
    )
    assert_config_rejected(
        "expected_chunk_count",
        0,
    )
    assert_config_rejected(
        "expected_embedding_count",
        3,
    )
    assert_config_rejected(
        "allow_production_write",
        True,
    )


def test_canonical_checksum_contract():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "candidate.pdf"
        path.write_bytes(b"release candidate")

        import hashlib

        checksum = hashlib.sha256(
            b"release candidate"
        ).hexdigest()

        config = config_fixture()
        config["expected_sha256"] = checksum

        result = verify_canonical_download(
            path,
            config,
        )

        assert result["verified"] is True
        assert result["sha256"] == checksum

        config["expected_sha256"] = "0" * 64

        try:
            verify_canonical_download(
                path,
                config,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "Checksum mismatch was accepted"
            )


def test_frozen_chunk_contract():
    result = validate_frozen_chunk_contract(
        chunks_fixture(),
        config_fixture(),
    )

    assert result["frozen_chunk_contract_ok"] is True
    assert result["chunk_count"] == 2

    payload = chunks_fixture()
    payload["chunks"].pop()
    payload["summary"]["chunk_count"] = 1
    payload["summary"]["counts_by_origin"]["native_text"] = 1

    try:
        validate_frozen_chunk_contract(
            payload,
            config_fixture(),
        )
    except RuntimeError:
        return

    raise AssertionError(
        "Frozen chunk count drift was accepted"
    )


def test_production_metadata_contract():
    payload = chunks_fixture()

    metadata = production_document_metadata(
        payload,
        Path("/tmp/retrieval-chunks-production-v1.json"),
        "Current/APP/APP145.pdf",
        CHECKSUM,
    )

    assert metadata["ingestion_version"] == FROZEN_INGESTION_VERSION
    assert metadata["release_gate"] == VERSION
    assert metadata["multimodal"] is False
    assert metadata["routing_profile"] == "legacy-v1"
    assert metadata["canonical_sha256"] == CHECKSUM


def test_transaction_contract():
    payload = chunks_fixture()
    vectors = [
        [0.0] * 384,
        [0.0] * 384,
    ]

    sql = build_production_transaction_sql(
        payload=payload,
        vectors=vectors,
        chunks_path=Path("/tmp/retrieval-chunks-production-v1.json"),
        title="APP-145",
        domain="building-control",
        topic="fire-safety-buildings",
        document_type="official-regulatory",
        authority="BD",
        jurisdiction="HK",
        language="en",
        source_url="https://www.bd.gov.hk/example.pdf",
        canonical_source="Current/APP/APP145.pdf",
        canonical_sha256=CHECKSUM,
    )

    inspection = inspect_transaction_sql(
        sql,
        expected_chunks=2,
    )

    assert inspection["transaction_contract_ok"] is True
    assert "'canonical-drive-text'" in sql
    assert VERSION in sql
    assert FROZEN_INGESTION_VERSION in sql
    assert '"multimodal":false' in sql
    assert '"retrieval_role":"text-primary"' in sql
    assert CHECKSUM in sql
    assert STAGING_DB_CONTAINER not in sql


def test_p2_has_no_write_executor():
    source = (
        Path(__file__).resolve().parent
        / "promote_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert "execute_transaction" not in source
    assert "--confirm-production-write" not in source
    assert "INGESTED_TEXT_TO_PRODUCTION" not in source


def main():
    test_registry_contract()
    test_config_safety_contract()
    test_canonical_checksum_contract()
    test_frozen_chunk_contract()
    test_production_metadata_contract()
    test_transaction_contract()
    test_p2_has_no_write_executor()

    print("Production promotion P2 contract test PASS")
    print("Git-controlled checksum lock: PASS")
    print("Frozen chunk-count lock: PASS")
    print("Production DB target lock: PASS")
    print("Staging DB rejection: PASS")
    print("Production release metadata: PASS")
    print("Transaction structure: PASS")
    print("Write executor absent: PASS")
    print("Database writes performed: False")


if __name__ == "__main__":
    main()
