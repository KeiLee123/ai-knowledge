#!/usr/bin/env python3

from pathlib import Path

from ingest_canonical_text_staging_v1 import (
    REQUIRED_ROUTE,
    build_text_transaction_sql,
    resolve_text_source,
    validate_legacy_route,
    validate_text_ingestion_config,
)
from ingest_manifest_v2 import inspect_transaction_sql
from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)


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
                "source_family": "PNAP",
                "source_type": "official-document",
                "document_code": "APP-145",
                "title": (
                    "Fire Safety (Buildings) "
                    "Ordinance Cap. 572"
                ),
                "canonical_url": (
                    "https://www.bd.gov.hk/"
                    "doc/en/resources/example.pdf"
                ),
                "domain": "building-control",
                "topic": "fire-safety-buildings",
                "canonical_text_ingestion": {
                    "enabled": True,
                    "controller_environment": "staging",
                    "remote": "gdrive-bd-write:",
                    "source": "Current/APP/APP145.pdf",
                    "db_container": STAGING_DB_CONTAINER,
                    "required_route": REQUIRED_ROUTE,
                    "document_type": "official-regulatory",
                    "language": "en",
                    "allow_production_write": False,
                },
            },
        },
    }


def test_registry_contract():
    source, config, defaults = resolve_text_source(
        registry_fixture(),
        "BD_PNAP_APP145",
    )

    assert source["document_code"] == "APP-145"
    assert config["source"] == "Current/APP/APP145.pdf"
    assert config["db_container"] == STAGING_DB_CONTAINER
    assert config["required_route"] == "legacy-v1"
    assert defaults["jurisdiction"] == "HK"


def assert_config_rejected(key, value):
    registry = registry_fixture()
    config = (
        registry["sources"]
        ["BD_PNAP_APP145"]
        ["canonical_text_ingestion"]
    )
    config[key] = value

    try:
        validate_text_ingestion_config(config)
    except RuntimeError:
        return

    raise AssertionError(
        f"Unsafe text ingestion config accepted: {key}={value!r}"
    )


def test_safety_contract():
    assert_config_rejected(
        "controller_environment",
        "production",
    )
    assert_config_rejected(
        "remote",
        "gdrive:",
    )
    assert_config_rejected(
        "source",
        "_Staging_Incoming/APP/APP145.pdf",
    )
    assert_config_rejected(
        "db_container",
        PRODUCTION_DB_CONTAINER,
    )
    assert_config_rejected(
        "required_route",
        "multimodal-v2",
    )
    assert_config_rejected(
        "allow_production_write",
        True,
    )


def test_route_contract():
    decision = validate_legacy_route(
        {
            "decision": {
                "production_decision_valid": True,
                "eligible_for_v2": False,
                "recommended_pipeline": "legacy-v1",
            }
        }
    )

    assert decision["recommended_pipeline"] == "legacy-v1"

    try:
        validate_legacy_route(
            {
                "decision": {
                    "production_decision_valid": True,
                    "eligible_for_v2": True,
                    "recommended_pipeline": "multimodal-v2",
                }
            }
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Multimodal document was accepted by text-only gate"
        )


def chunks_fixture():
    checksum = "a" * 64

    return {
        "schema_version": "retrieval-chunks-v2",
        "source_manifest": {
            "document_name": "APP145.pdf",
            "document_sha256": checksum,
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
                "content": "First text chunk",
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
                "content": "Second text chunk",
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


def test_transaction_contract():
    payload = chunks_fixture()
    vectors = [
        [0.0] * 384,
        [0.0] * 384,
    ]

    sql = build_text_transaction_sql(
        payload=payload,
        vectors=vectors,
        chunks_path=Path("/tmp/retrieval-chunks-text-v1.json"),
        title="APP-145",
        domain="building-control",
        topic="fire-safety-buildings",
        document_type="official-regulatory",
        authority="BD",
        jurisdiction="HK",
        language="en",
        source_url="https://www.bd.gov.hk/example.pdf",
        canonical_source="Current/APP/APP145.pdf",
    )

    inspection = inspect_transaction_sql(
        sql,
        expected_chunks=2,
    )

    assert inspection["transaction_contract_ok"] is True
    assert "'canonical-drive-text'" in sql
    assert "canonical-text-ingestion-v1" in sql
    assert '"multimodal":false' in sql
    assert '"retrieval_role":"text-primary"' in sql
    assert "Current/APP/APP145.pdf" in sql
    assert PRODUCTION_DB_CONTAINER not in sql


def main():
    test_registry_contract()
    test_safety_contract()
    test_route_contract()
    test_transaction_contract()

    print(
        "Canonical text ingestion v1 contract test PASS"
    )
    print("Legacy route gate: PASS")
    print("Staging DB lock: PASS")
    print("Production DB rejection: PASS")
    print("Text metadata contract: PASS")
    print("Transaction structure: PASS")


if __name__ == "__main__":
    main()
