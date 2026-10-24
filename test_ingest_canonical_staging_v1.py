#!/usr/bin/env python3

from pathlib import Path

from ingest_canonical_staging_v1 import (
    ALLOWED_REMOTE,
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    build_canary_command,
    canonical_remote_path,
    classify_pipeline_result,
    resolve_source,
    validate_ingestion_config,
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
                "canonical_ingestion": {
                    "enabled": True,
                    "controller_environment": "staging",
                    "remote": ALLOWED_REMOTE,
                    "source": "Current/APP/APP145.pdf",
                    "db_container": STAGING_DB_CONTAINER,
                    "pipeline": "multimodal-v2",
                    "document_type": "official-regulatory",
                    "language": "en",
                    "allow_production_write": False,
                },
            },
        },
    }


def test_registry_contract():
    source, ingestion, defaults = resolve_source(
        registry_fixture(),
        "BD_PNAP_APP145",
    )

    assert source["document_code"] == "APP-145"
    assert ingestion["db_container"] == STAGING_DB_CONTAINER
    assert ingestion["source"] == "Current/APP/APP145.pdf"
    assert defaults["jurisdiction"] == "HK"

    assert canonical_remote_path(ingestion) == (
        "gdrive-bd-write:"
        "Current/APP/APP145.pdf"
    )


def assert_rejected(key, value):
    registry = registry_fixture()

    ingestion = (
        registry["sources"]
        ["BD_PNAP_APP145"]
        ["canonical_ingestion"]
    )

    ingestion[key] = value

    try:
        validate_ingestion_config(ingestion)
    except RuntimeError:
        return

    raise AssertionError(
        f"Unsafe config accepted: {key}={value!r}"
    )


def test_safety_contract():
    assert_rejected(
        "controller_environment",
        "production",
    )
    assert_rejected(
        "remote",
        "gdrive:",
    )
    assert_rejected(
        "source",
        "_Staging_Incoming/APP/APP145.pdf",
    )
    assert_rejected(
        "source",
        "/Current/APP/APP145.pdf",
    )
    assert_rejected(
        "db_container",
        PRODUCTION_DB_CONTAINER,
    )
    assert_rejected(
        "pipeline",
        "legacy-v1",
    )
    assert_rejected(
        "allow_production_write",
        True,
    )


def test_prepare_command_contract():
    registry = registry_fixture()
    source, ingestion, defaults = resolve_source(
        registry,
        "BD_PNAP_APP145",
    )

    command = build_canary_command(
        repo_root=Path(
            "/opt/ai-knowledge-staging"
        ),
        python="/venv/bin/python",
        source_file=Path(
            "/tmp/APP145.pdf"
        ),
        source=source,
        ingestion=ingestion,
        defaults=defaults,
        workdir=Path("/tmp/app145-work"),
        write=False,
    )

    assert command[1].endswith(
        "run_multimodal_canary_v2.py"
    )
    assert "--write" not in command
    assert "--confirm-staging-write" not in command
    assert PRODUCTION_DB_CONTAINER not in command
    assert source["canonical_url"] in command
    assert "--workdir" in command
    assert "/tmp/app145-work" in command


def test_write_command_contract():
    registry = registry_fixture()
    source, ingestion, defaults = resolve_source(
        registry,
        "BD_PNAP_APP145",
    )

    command = build_canary_command(
        repo_root=Path(
            "/opt/ai-knowledge-staging"
        ),
        python="/venv/bin/python",
        source_file=Path(
            "/tmp/APP145.pdf"
        ),
        source=source,
        ingestion=ingestion,
        defaults=defaults,
        workdir=Path("/tmp/app145-work"),
        write=True,
    )

    assert "--write" in command
    assert "--confirm-staging-write" in command
    assert PRODUCTION_DB_CONTAINER not in command


def test_multimodal_prepare_result():
    result = classify_pipeline_result(
        {
            "route": {
                "recommended_pipeline": "multimodal-v2",
                "eligible_for_v2": True,
            },
            "database_write_performed": False,
        },
        write=False,
    )

    assert result["status"] == "PREPARED_FOR_STAGING"
    assert result["database_write_performed"] is False


def test_legacy_prepare_result():
    result = classify_pipeline_result(
        {
            "route": {
                "recommended_pipeline": "legacy-v1",
                "eligible_for_v2": False,
            },
            "database_write_performed": False,
        },
        write=False,
    )

    assert result["status"] == "ROUTED_TO_LEGACY_V1_NO_WRITE"
    assert result["pipeline"] == "legacy-v1"


def test_legacy_write_rejected():
    try:
        classify_pipeline_result(
            {
                "route": {
                    "recommended_pipeline": "legacy-v1",
                    "eligible_for_v2": False,
                },
                "database_write_performed": False,
            },
            write=True,
        )
    except RuntimeError:
        return

    raise AssertionError(
        "legacy-v1 route must not be reported as a Staging DB write"
    )


def main():
    test_registry_contract()
    test_safety_contract()
    test_prepare_command_contract()
    test_write_command_contract()
    test_multimodal_prepare_result()
    test_legacy_prepare_result()
    test_legacy_write_rejected()

    print(
        "Canonical ingestion v1 contract test PASS"
    )
    print("Current-path gate: PASS")
    print("Staging DB lock: PASS")
    print("Production DB rejection: PASS")
    print("Explicit write confirmation: PASS")
    print("Route-result reporting: PASS")


if __name__ == "__main__":
    main()
