#!/usr/bin/env python3

from pathlib import Path

from monitor_official_source_v1 import (
    decision_action,
    evaluate_candidate_snapshot,
)
from version_qualification_policy_v1 import (
    CANDIDATE_NEW_VERSION,
    EXCEPTION_REVIEW,
    POLICY_BLOCKED,
    UNCHANGED,
)


def snapshot(
    *,
    issue_date,
    revision_date,
    document_sha,
    metadata_sha,
    content_sha,
):
    return {
        "authority_code": "BD",
        "document_code": "APP-149",
        "canonical_host":
            "www.bd.gov.hk",
        "issue_date":
            issue_date,
        "revision_date":
            revision_date,
        "edition":
            None,
        "metadata_fingerprint":
            metadata_sha,
        "normalized_content_fingerprint":
            content_sha,
        "document_sha256":
            document_sha,
    }


def test_newer_candidate_routes_to_staging():
    old = snapshot(
        issue_date="2010-12",
        revision_date="2010-12",
        document_sha="a" * 64,
        metadata_sha="b" * 64,
        content_sha="c" * 64,
    )

    new = snapshot(
        issue_date="2026-08",
        revision_date="2026-08",
        document_sha="d" * 64,
        metadata_sha="e" * 64,
        content_sha="f" * 64,
    )

    signals, result = (
        evaluate_candidate_snapshot(
            previous_snapshot=old,
            current_snapshot=new,
        )
    )

    assert (
        result["decision"]
        == CANDIDATE_NEW_VERSION
    )
    assert (
        signals[
            "staging_validation_verified"
        ]
        is False
    )
    assert (
        signals[
            "deterministic_release"
        ]
        is False
    )
    assert (
        decision_action(
            result[
                "decision"
            ]
        )
        == "STAGING_VALIDATION_REQUIRED"
    )


def test_packaging_only_routes_to_review():
    old = snapshot(
        issue_date="2010-12",
        revision_date="2010-12",
        document_sha="a" * 64,
        metadata_sha="b" * 64,
        content_sha="c" * 64,
    )

    changed = dict(
        old
    )
    changed[
        "document_sha256"
    ] = "d" * 64

    _signals, result = (
        evaluate_candidate_snapshot(
            previous_snapshot=old,
            current_snapshot=changed,
        )
    )

    assert (
        result["decision"]
        == EXCEPTION_REVIEW
    )


def test_date_regression_blocks():
    old = snapshot(
        issue_date="2026-08",
        revision_date="2026-08",
        document_sha="a" * 64,
        metadata_sha="b" * 64,
        content_sha="c" * 64,
    )

    changed = snapshot(
        issue_date="2025-03",
        revision_date="2025-03",
        document_sha="d" * 64,
        metadata_sha="e" * 64,
        content_sha="f" * 64,
    )

    _signals, result = (
        evaluate_candidate_snapshot(
            previous_snapshot=old,
            current_snapshot=changed,
        )
    )

    assert (
        result["decision"]
        == POLICY_BLOCKED
    )


def test_action_map():
    assert (
        decision_action(
            UNCHANGED
        )
        == "NONE"
    )
    assert (
        decision_action(
            EXCEPTION_REVIEW
        )
        == "EXCEPTION_REVIEW"
    )
    assert (
        decision_action(
            POLICY_BLOCKED
        )
        == "STOP"
    )


def test_no_production_writer_surface():
    text = (
        Path(
            "monitor_official_source_v1.py"
        )
        .read_text(
            encoding="utf-8"
        )
    )

    forbidden = (
        "write_canonical_text_production",
        "--confirm-production-write",
        "production_release_registry",
        "psycopg",
        "INSERT INTO",
        "DELETE FROM",
    )

    for token in forbidden:
        assert token not in text


def main():
    test_newer_candidate_routes_to_staging()
    test_packaging_only_routes_to_review()
    test_date_regression_blocks()
    test_action_map()
    test_no_production_writer_surface()

    print(
        "Official Source Monitor Integration v1: PASS"
    )
    print(
        "Newer candidate routing: PASS"
    )
    print(
        "Packaging-only review routing: PASS"
    )
    print(
        "Date regression blocking: PASS"
    )
    print(
        "Production write surface: ABSENT"
    )


if __name__ == "__main__":
    main()
