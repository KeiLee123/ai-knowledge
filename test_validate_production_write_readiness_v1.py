#!/usr/bin/env python3

import json
import tempfile
from pathlib import Path

from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
)
from validate_production_write_readiness_v1 import (
    REQUIRED_RELEASE_BASE_COMMIT,
    build_zero_state_sql,
    parse_json_payload,
    validate_prepared_artifacts,
    validate_recovery_readiness,
    validate_validator_readiness,
    validate_zero_state,
)
from production_release_source_v1 import (
    load_release_registry,
)


REPO_ROOT = Path(__file__).resolve().parent
CHECKSUM = (
    "dc3262cc55c5fd79d29f337fd811cdd8"
    "71543f59d795972d9f30f558e313127c"
)


def config_fixture():
    registry = load_release_registry(
        REPO_ROOT / "production_release_registry_v1.yaml"
    )

    return (
        registry["sources"]["BD_PNAP_APP145"]
        ["canonical_text_production_promotion"]
    )


def test_zero_state_sql_is_read_only():
    sql = build_zero_state_sql(CHECKSUM)
    lowered = sql.lower()

    assert "select" in lowered
    assert "delete " not in lowered
    assert "insert " not in lowered
    assert "update " not in lowered
    assert CHECKSUM in sql


def test_zero_state_contract():
    payload = parse_json_payload(
        json.dumps(
            {
                "document_count": 0,
                "chunk_count": 0,
                "embedding_count": 0,
            }
        ),
        "test",
    )

    result = validate_zero_state(payload)

    assert result["zero_state_ok"] is True

    try:
        validate_zero_state(
            {
                "document_count": 1,
                "chunk_count": 8,
                "embedding_count": 8,
            }
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Readiness accepted non-zero Production candidate state"
        )


def test_prepared_artifact_contract():
    config = config_fixture()

    with tempfile.TemporaryDirectory() as temp_dir:
        workdir = Path(temp_dir)
        pdf = workdir / "APP145.pdf"
        chunks = (
            workdir / "retrieval-chunks-production-v1.json"
        )

        pdf.write_bytes(b"candidate")

        import hashlib

        checksum = hashlib.sha256(
            b"candidate"
        ).hexdigest()

        config = dict(config)
        config["expected_sha256"] = checksum
        config["expected_chunk_count"] = 2
        config["expected_embedding_count"] = 2

        chunks.write_text(
            json.dumps(
                {
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
                            "content": "Fire safety",
                            "page_start": 1,
                            "page_end": 1,
                            "metadata": {
                                "evidence_origin": "native_text",
                                "evidence_tier": "primary",
                            },
                        },
                        {
                            "chunk_index": 1,
                            "content": "Means of escape",
                            "page_start": 2,
                            "page_end": 2,
                            "metadata": {
                                "evidence_origin": "native_text",
                                "evidence_tier": "primary",
                            },
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = validate_prepared_artifacts(
            workdir=workdir,
            config=config,
        )

        assert result["prepared_artifacts_ok"] is True
        assert result["chunk_count"] == 2
        assert result["canonical_sha256"] == checksum


def test_recovery_readiness():
    result = validate_recovery_readiness(
        CHECKSUM
    )

    assert result["recovery_contract_ok"] is True
    assert result["delete_order_ok"] is True
    assert result["release_gate_lock"] is True
    assert result["ingestion_version_lock"] is True


def test_validator_readiness():
    result = validate_validator_readiness(
        REPO_ROOT
    )

    assert result["validator_ready"] is True
    assert result["validator_read_only"] is True
    assert result["post_write_semantic_checks"] == 2


def test_release_baseline_is_fixed():
    assert (
        REQUIRED_RELEASE_BASE_COMMIT
        == "be5de81fdf2fd8e7ac37a1a76ca4619faa55bfc2"
    )


def test_no_write_executor():
    source = (
        REPO_ROOT
        / "validate_production_write_readiness_v1.py"
    ).read_text(encoding="utf-8")

    assert "execute_transaction(" not in source
    assert "from ingest_manifest_v2 import execute_transaction" not in source
    assert 'parser.add_argument("--write"' not in source
    assert "--confirm-production-write" not in source
    assert "Database writes performed: False" in source
    assert "PRODUCTION_DB_CONTAINER" in source
    assert "from production_promotion_guard_v1 import (" in source


def main():
    test_zero_state_sql_is_read_only()
    test_zero_state_contract()
    test_prepared_artifact_contract()
    test_recovery_readiness()
    test_validator_readiness()
    test_release_baseline_is_fixed()
    test_no_write_executor()

    print("Production write readiness v1 contract test PASS")
    print("Production zero-state gate: PASS")
    print("P7 prepared artifact binding: PASS")
    print("Recovery readiness: PASS")
    print("Post-write validator readiness: PASS")
    print("Reviewed main baseline lock: PASS")
    print("Write executor absent: PASS")
    print("Database writes performed: False")


if __name__ == "__main__":
    main()
