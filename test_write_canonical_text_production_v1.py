#!/usr/bin/env python3

from pathlib import Path

from production_release_source_v1 import (
    load_release_registry,
)
from write_canonical_text_production_v1 import (
    REQUIRED_WRITE_BASE_COMMIT,
    VERSION,
    extract_document_id,
    resolve_write_config,
)


REPO_ROOT = Path(__file__).resolve().parent

EXPECTED_CHECKSUM = (
    "dc3262cc55c5fd79d29f337fd811cdd8"
    "71543f59d795972d9f30f558e313127c"
)

EXPECTED_CHUNKS_SHA256 = (
    "9f6433b3065c4906bff32935c63fba2"
    "5ae8c9daba3760674034153f839a391d1"
)

PRODUCTION_DB = (
    "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
)


def load_contract():
    registry = load_release_registry(
        REPO_ROOT
        / "production_release_registry_v1.yaml"
    )

    return resolve_write_config(
        registry,
        "BD_PNAP_APP145",
    )


def test_write_profile():
    source, promotion, write_config, defaults = (
        load_contract()
    )

    assert VERSION == "canonical-text-production-write-v1"
    assert source["document_code"] == "APP-145"
    assert defaults["jurisdiction"] == "HK"

    assert write_config["enabled"] is True
    assert (
        write_config["controller_environment"]
        == "production"
    )
    assert (
        write_config["db_container"]
        == PRODUCTION_DB
    )
    assert (
        write_config["db_container"]
        != "jason-os-knowledge-db-staging"
    )

    assert (
        write_config["expected_sha256"]
        == EXPECTED_CHECKSUM
    )
    assert (
        promotion["expected_sha256"]
        == EXPECTED_CHECKSUM
    )
    assert (
        write_config["expected_chunks_sha256"]
        == EXPECTED_CHUNKS_SHA256
    )

    assert write_config["expected_chunk_count"] == 8
    assert write_config["expected_embedding_count"] == 8
    assert write_config["require_confirmation"] is True
    assert promotion["allow_production_write"] is False


def test_write_baseline_lock():
    assert (
        REQUIRED_WRITE_BASE_COMMIT
        == "b5aed0b7619f4bb9beec175e0d913b136d9225b4"
    )


def test_document_id_parser():
    assert (
        extract_document_id(
            "DOCUMENT_ID 42\n"
        )
        == 42
    )

    try:
        extract_document_id(
            "COMMIT\n"
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Writer accepted transaction output without DOCUMENT_ID"
        )


def test_explicit_confirmation_contract():
    source = (
        REPO_ROOT
        / "write_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    required = [
        "--write",
        "--confirm-production-write",
        "Only explicit --write mode is supported",
        "explicit_confirmation",
        "database_write_requested",
    ]

    for token in required:
        assert token in source, token


def test_double_zero_state_and_fixed_db():
    source = (
        REPO_ROOT
        / "write_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert (
        source.count("check_zero_state(")
        >= 3
    )

    assert "initial_zero_state" in source
    assert "pre_commit_zero_state" in source
    assert "PRODUCTION_DB_CONTAINER" in source
    assert "STAGING_DB_CONTAINER" in source
    assert "execute_transaction(" in source


def test_prepared_artifact_lock():
    source = (
        REPO_ROOT
        / "write_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert "expected_chunks_sha256" in source
    assert "chunks_file_sha256" in source
    assert "validate_prepared_artifacts" in source
    assert "expected_chunk_count" in source
    assert "expected_embedding_count" in source


def test_post_write_validation_is_mandatory():
    source = (
        REPO_ROOT
        / "write_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert (
        "validate_canonical_text_production_v1.py"
        in source
    )
    assert "run_post_write_validator(" in source
    assert "INGESTED_AND_VALIDATED" in source
    assert (
        "PRODUCTION WRITE POST-COMMIT FAILURE"
        in source
    )
    assert (
        "Use the dedicated Production recovery command"
        in source
    )


def test_no_automatic_recovery():
    source = (
        REPO_ROOT
        / "write_canonical_text_production_v1.py"
    ).read_text(encoding="utf-8")

    assert (
        "recover_canonical_text_production_v1.py"
        not in source
    )
    assert "--confirm-production-recovery" not in source


def main():
    test_write_profile()
    test_write_baseline_lock()
    test_document_id_parser()
    test_explicit_confirmation_contract()
    test_double_zero_state_and_fixed_db()
    test_prepared_artifact_lock()
    test_post_write_validation_is_mandatory()
    test_no_automatic_recovery()

    print("Production canonical text writer v1 contract test PASS")
    print("Explicit confirmation gate: PASS")
    print("Fixed Production DB target: PASS")
    print("Reviewed P8 baseline lock: PASS")
    print("P7 chunks SHA-256 lock: PASS")
    print("Double zero-state duplicate gate: PASS")
    print("8/8 write contract: PASS")
    print("Mandatory post-write validation: PASS")
    print("Automatic recovery: DISABLED")


if __name__ == "__main__":
    main()
