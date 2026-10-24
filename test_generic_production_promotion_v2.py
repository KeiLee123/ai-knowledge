#!/usr/bin/env python3

from pathlib import Path

from canonical_text_production_v2 import (
    build_transaction_sql,
)
from ingest_manifest_v2 import (
    inspect_transaction_sql,
)
from production_release_contract_v2 import (
    FROZEN_INGESTION_VERSION,
    RELEASE_GATE_VERSION,
    REQUIRED_ROUTE,
    resolve_release_source,
    validate_release_config,
    validate_semantic_validation,
)
from recover_canonical_text_production_v2 import (
    build_recovery_sql,
    inspect_recovery_sql,
)


ROOT = Path(__file__).resolve().parent


def fixture(
    *,
    authorized: bool,
) -> dict:
    return {
        "production_release_registry_version": 2,
        "defaults": {
            "jurisdiction": "HK",
        },
        "sources": {
            "TEST_SOURCE": {
                "enabled": True,
                "authority_code": "BD",
                "publisher": "Buildings Department",
                "source_type": "official-document",
                "document_code": "APP-X",
                "title": "Test source",
                "canonical_url": "https://example.com/test.pdf",
                "domain": "building-control",
                "topic": "test",
                "canonical_text_release_v2": {
                    "enabled": True,
                    "release_id": "test-source-0123456789ab",
                    "controller_environment": "production",
                    "remote": "gdrive-bd-write:",
                    "source": "Current/APP/APPX.pdf",
                    "db_container": "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr",
                    "required_route": REQUIRED_ROUTE,
                    "frozen_ingestion_version":
                        FROZEN_INGESTION_VERSION,
                    "expected_sha256": "a" * 64,
                    "expected_chunks_sha256": "b" * 64,
                    "expected_chunk_count": 1,
                    "expected_embedding_count": 1,
                    "document_type": "official-regulatory",
                    "language": "en",
                    "semantic_validation": {
                        "checks": [
                            {
                                "label": "test_query",
                                "query": "What is this?",
                                "expect_terms": ["test"],
                            }
                        ]
                    },
                    "release_reviewed": True,
                    "write_authorized": authorized,
                    "require_confirmation": True,
                },
            }
        },
    }


registry = fixture(
    authorized=False
)

source, config, defaults = (
    resolve_release_source(
        registry,
        "TEST_SOURCE",
    )
)

assert config[
    "write_authorized"
] is False

try:
    resolve_release_source(
        registry,
        "TEST_SOURCE",
        require_write_authorized=True,
    )
except RuntimeError as exc:
    assert "write_authorized" in str(exc)
else:
    raise AssertionError(
        "Unauthorized release was accepted"
    )

authorized_registry = fixture(
    authorized=True
)

(
    source,
    config,
    defaults,
) = resolve_release_source(
    authorized_registry,
    "TEST_SOURCE",
    require_write_authorized=True,
)

checks = validate_semantic_validation(
    config
)

assert checks == [
    {
        "label": "test_query",
        "query": "What is this?",
        "expect_terms": ["test"],
    }
]

payload = {
    "schema_version": "retrieval-chunks-v2",
    "source_manifest": {
        "document_sha256": "a" * 64,
        "document_name": "APPX.pdf",
        "sha256": "a" * 64,
    },
    "summary": {
        "chunk_count": 1,
        "counts_by_origin": {
            "native_text": 1,
        },
    },
    "chunks": [
        {
            "content": "test content",
            "page_start": 1,
            "page_end": 1,
            "metadata": {
                "evidence_origin": "native_text",
                "evidence_tier": "primary",
            },
        }
    ],
}

sql = build_transaction_sql(
    payload=payload,
    vectors=[[0.0] * 384],
    chunks_path=Path(
        "retrieval-chunks-production-v2.json"
    ),
    source=source,
    config=config,
    defaults=defaults,
)

inspection = inspect_transaction_sql(
    sql,
    1,
)

assert inspection[
    "transaction_contract_ok"
] is True
assert RELEASE_GATE_VERSION in sql
assert config["release_id"] in sql
assert "BD_PNAP_APP145" not in sql

recovery_sql = build_recovery_sql(
    config["expected_sha256"],
    config["release_id"],
)

recovery = inspect_recovery_sql(
    recovery_sql
)

assert recovery[
    "recovery_contract_ok"
] is True
assert config["release_id"] in recovery_sql
assert RELEASE_GATE_VERSION in recovery_sql

proposal_source = (
    ROOT
    / "propose_production_release_v2.py"
).read_text(
    encoding="utf-8"
)

for forbidden in (
    "run_production_query",
    "execute_transaction",
    "--confirm-production-write",
):
    assert forbidden not in proposal_source

assert (
    '"release_reviewed":\n                False'
    in proposal_source
)
assert (
    '"write_authorized":\n                False'
    in proposal_source
)

readiness_source = (
    ROOT
    / "validate_production_write_readiness_v2.py"
).read_text(
    encoding="utf-8"
)

assert (
    "require_write_authorized=\n                    True"
    in readiness_source
)
assert (
    "database_write_performed"
    in readiness_source
)

writer_source = (
    ROOT
    / "write_canonical_text_production_v2.py"
).read_text(
    encoding="utf-8"
)

assert (
    writer_source.count(
        "check_zero_state("
    )
    >= 3
)
assert (
    "require_write_authorized=\n                True"
    in writer_source
)
assert (
    "--confirm-production-write"
    in writer_source
)
assert (
    "run_post_write_validator"
    in writer_source
)
assert (
    "execute_recovery"
    not in writer_source
)

validator_source = (
    ROOT
    / "validate_canonical_text_production_v2.py"
).read_text(
    encoding="utf-8"
)

for forbidden in (
    "execute_transaction",
    "DELETE FROM",
    "INSERT INTO",
    "--write",
    "--recover",
):
    assert forbidden not in validator_source

v1_writer = (
    ROOT
    / "write_canonical_text_production_v1.py"
).read_text(
    encoding="utf-8"
)

assert (
    'VERSION = "canonical-text-production-write-v1"'
    in v1_writer
)
assert (
    "BD_PNAP_APP145"
    not in writer_source
)

validate_release_config(
    config,
    require_write_authorized=True,
)

print(
    "Generic Production Promotion v2 contract test PASS"
)
print(
    "Git-controlled release contract: PASS"
)
print(
    "Generic source-independent writer: PASS"
)
print(
    "Double zero-state gate: PASS"
)
print(
    "Mandatory post-write validator: PASS"
)
print(
    "Break-glass recovery isolation: PASS"
)
print(
    "APP-145 v1 frozen writer: UNCHANGED CONTRACT"
)
