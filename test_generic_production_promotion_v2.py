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
from release_artifact_profiles_v2 import (
    CANONICAL_TEXT_PROFILE,
    MULTIMODAL_PROFILE,
    artifact_profile_contract,
)
from version_qualification_policy_v1 import (
    evaluate_initial_release,
)


ROOT = Path(__file__).resolve().parent


def fixture(
    *,
    authorized: bool,
    artifact_profile:
        str = CANONICAL_TEXT_PROFILE,
) -> dict:
    profile = artifact_profile_contract(
        artifact_profile
    )

    if (
        artifact_profile
        == CANONICAL_TEXT_PROFILE
    ):
        count = 1
        evidence = {
            "native_text": 1,
        }
    else:
        count = 2
        evidence = {
            "native_text": 1,
            "structured_table": 1,
        }

    return {
        "production_release_registry_version": 2,
        "defaults": {
            "jurisdiction": "HK",
        },
        "sources": {
            "TEST_SOURCE": {
                "enabled": True,
                "authority_code": "BD",
                "publisher":
                    "Buildings Department",
                "source_type":
                    "official-document",
                "document_code": "APP-X",
                "title": "Test source",
                "canonical_url":
                    "https://example.com/test.pdf",
                "domain":
                    "building-control",
                "topic":
                    "test",
                "release_v2": {
                    "enabled": True,
                    "artifact_profile":
                        artifact_profile,
                    "release_id":
                        "test-source-0123456789ab",
                    "controller_environment":
                        "production",
                    "remote":
                        "gdrive-bd-write:",
                    "source":
                        "Current/APP/APPX.pdf",
                    "db_container":
                        "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr",
                    "required_route":
                        profile[
                            "required_route"
                        ],
                    "frozen_ingestion_version":
                        profile[
                            "ingestion_version"
                        ],
                    "expected_sha256":
                        "a" * 64,
                    "expected_chunks_sha256":
                        "b" * 64,
                    "expected_chunk_count":
                        count,
                    "expected_embedding_count":
                        count,
                    "expected_evidence_counts":
                        evidence,
                    "document_type":
                        "official-regulatory",
                    "language":
                        "en",
                    "staging_validation_status":
                        "VERIFIED",
                    "semantic_validation": {
                        "checks": [
                            {
                                "label":
                                    "test_query",
                                "query":
                                    "What is this?",
                                "expect_terms":
                                    ["test"],
                            }
                        ]
                    },
                    "qualification":
                        evaluate_initial_release(
                            {
                                "official_source_identity":
                                    True,
                                "staging_validation_verified":
                                    True,
                                "deterministic_release":
                                    True,
                                "canonical_checksum_locked":
                                    True,
                                "chunks_checksum_locked":
                                    True,
                            }
                        ),
                    "write_authorized":
                        authorized,
                    "require_confirmation":
                        True,
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
    "artifact_profile"
] == CANONICAL_TEXT_PROFILE

assert config[
    "required_route"
] == REQUIRED_ROUTE

assert config[
    "frozen_ingestion_version"
] == FROZEN_INGESTION_VERSION

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

assert checks[0][
    "expect_terms"
] == ["test"]

multimodal_registry = fixture(
    authorized=False,
    artifact_profile=
        MULTIMODAL_PROFILE,
)

(
    _mm_source,
    mm_config,
    _mm_defaults,
) = resolve_release_source(
    multimodal_registry,
    "TEST_SOURCE",
)

assert mm_config[
    "required_route"
] == "multimodal-v2"

assert mm_config[
    "frozen_ingestion_version"
] == "v2"

mm_profile = artifact_profile_contract(
    MULTIMODAL_PROFILE
)

assert mm_profile[
    "production_write_qualified"
] is False

unsafe_mm = fixture(
    authorized=True,
    artifact_profile=
        MULTIMODAL_PROFILE,
)

try:
    resolve_release_source(
        unsafe_mm,
        "TEST_SOURCE",
        require_write_authorized=True,
    )
except RuntimeError as exc:
    assert (
        "not Production-write qualified"
        in str(exc)
    )
else:
    raise AssertionError(
        "Multimodal Production authorization "
        "was accepted"
    )

payload = {
    "schema_version":
        "retrieval-chunks-v2",
    "source_manifest": {
        "document_sha256":
            "a" * 64,
        "document_name":
            "APPX.pdf",
        "sha256":
            "a" * 64,
    },
    "summary": {
        "chunk_count": 1,
        "counts_by_origin": {
            "native_text": 1,
        },
    },
    "chunks": [
        {
            "content":
                "test content",
            "page_start": 1,
            "page_end": 1,
            "metadata": {
                "evidence_origin":
                    "native_text",
                "evidence_tier":
                    "primary",
            },
        }
    ],
}

sql = build_transaction_sql(
    payload=payload,
    vectors=[
        [0.0] * 384
    ],
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
    config[
        "expected_sha256"
    ],
    config[
        "release_id"
    ],
)

recovery = inspect_recovery_sql(
    recovery_sql
)

assert recovery[
    "recovery_contract_ok"
] is True

assert config[
    "release_id"
] in recovery_sql

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
    '"release_v2": {'
    in proposal_source
)

assert (
    "CANONICAL_TEXT_PROFILE"
    in proposal_source
)

assert (
    '"expected_evidence_counts": {'
    in proposal_source
)

assert (
    '"qualification":'
    in proposal_source
)

assert (
    "evaluate_initial_release"
    in proposal_source
)

assert (
    '"release_reviewed"'
    not in proposal_source
)

assert (
    '"write_authorized":\n                False'
    in proposal_source
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

validate_release_config(
    config,
    require_write_authorized=True,
)

bad_qualification = dict(
    config
)
bad_qualification[
    "qualification"
] = {
    **config[
        "qualification"
    ],
    "status": "review_required",
    "decision": "REVIEW_REQUIRED",
}

try:
    validate_release_config(
        bad_qualification,
        require_write_authorized=True,
    )
except RuntimeError as exc:
    assert (
        "not policy-qualified"
        in str(exc)
        or "does not match"
        in str(exc)
    )
else:
    raise AssertionError(
        "Unqualified release was accepted"
    )

bad_route = dict(
    config
)
bad_route[
    "required_route"
] = "multimodal-v2"

try:
    validate_release_config(
        bad_route,
        require_write_authorized=True,
    )
except RuntimeError as exc:
    assert (
        "required_route must match"
        in str(exc)
    )
else:
    raise AssertionError(
        "Profile/route drift was accepted"
    )

print(
    "Generic Production Promotion v2 "
    "artifact-profile contract test PASS"
)
print(
    "Canonical text profile: PASS"
)
print(
    "Policy qualification gate: PASS"
)
print(
    "Multimodal profile: PASS"
)
print(
    "Profile/route drift guard: PASS"
)
print(
    "Multimodal Production authorization: "
    "BLOCKED"
)
print(
    "APP-145 v1 frozen writer: "
    "UNCHANGED CONTRACT"
)