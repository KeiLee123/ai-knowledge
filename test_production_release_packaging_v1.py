#!/usr/bin/env python3

from pathlib import Path

from production_release_source_v1 import (
    load_release_registry,
)
from promote_canonical_text_production_v1 import (
    resolve_promotion_source,
)


REPO_ROOT = Path(__file__).resolve().parent

PRODUCTION_RELEASE_FILES = [
    "production_promotion_guard_v1.py",
    "canonical_text_release_contract_v1.py",
    "production_release_source_v1.py",
    "production_read_only_retrieval_v1.py",
    "promote_canonical_text_production_v1.py",
    "recover_canonical_text_production_v1.py",
    "validate_canonical_text_production_v1.py",
    "validate_production_write_readiness_v1.py",
    "write_canonical_text_production_v1.py",
]

FORBIDDEN_DEPENDENCIES = [
    "ingest_canonical_staging_v1",
    "ingest_canonical_text_staging_v1",
    "validate_staging_retrieval_v2",
    "source_registry_v1.yaml",
]


def test_no_staging_module_dependencies():
    for relative in PRODUCTION_RELEASE_FILES:
        source = (
            REPO_ROOT / relative
        ).read_text(encoding="utf-8")

        for forbidden in FORBIDDEN_DEPENDENCIES:
            assert forbidden not in source, (
                f"{relative} still depends on {forbidden}"
            )


def test_production_registry_contract():
    registry = load_release_registry(
        REPO_ROOT / "production_release_registry_v1.yaml"
    )

    source, config, defaults = resolve_promotion_source(
        registry,
        "BD_PNAP_APP145",
    )

    assert source["document_code"] == "APP-145"
    assert defaults["jurisdiction"] == "HK"
    assert config["controller_environment"] == "production"
    assert (
        config["db_container"]
        == "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
    )
    assert config["required_route"] == "legacy-v1"
    assert (
        config["frozen_ingestion_version"]
        == "canonical-text-ingestion-v1"
    )
    assert config["expected_chunk_count"] == 8
    assert config["expected_embedding_count"] == 8
    assert config["allow_production_write"] is False


def test_release_registry_is_minimal():
    registry = load_release_registry(
        REPO_ROOT / "production_release_registry_v1.yaml"
    )

    assert set(registry.keys()) == {
        "production_release_registry_version",
        "defaults",
        "sources",
    }

    assert set(registry["sources"].keys()) == {
        "BD_PNAP_APP145",
    }


def main():
    test_no_staging_module_dependencies()
    test_production_registry_contract()
    test_release_registry_is_minimal()

    print("Production release packaging contract test PASS")
    print("Staging module dependency scan: PASS")
    print("Production-only registry: PASS")
    print("APP-145 release profile lock: PASS")
    print("Minimal release registry: PASS")


if __name__ == "__main__":
    main()
