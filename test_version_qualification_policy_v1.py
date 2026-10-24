#!/usr/bin/env python3

from version_qualification_policy_v1 import (
    AUTO_QUALIFIED,
    BLOCKED,
    CANDIDATE_NEW_VERSION,
    NO_CHANGE,
    QUALIFIED,
    REVIEW_REQUIRED,
    evaluate_initial_release,
    evaluate_version_candidate,
    evaluate_version_update,
    validate_qualification_record,
)


def test_initial_release():
    signals = {
        "official_source_identity": True,
        "staging_validation_verified": True,
        "deterministic_release": True,
        "canonical_checksum_locked": True,
        "chunks_checksum_locked": True,
    }

    result = evaluate_initial_release(
        signals
    )

    assert result["status"] == QUALIFIED
    assert (
        result["decision"]
        == AUTO_QUALIFIED
    )

    validate_qualification_record(
        result
    )


def test_initial_release_fail_closed():
    result = evaluate_initial_release(
        {
            "official_source_identity": True,
            "staging_validation_verified": True,
            "deterministic_release": False,
            "canonical_checksum_locked": True,
            "chunks_checksum_locked": True,
        }
    )

    assert result["status"] == BLOCKED


def update_signals():
    return {
        "authority_match": True,
        "document_code_match": True,
        "official_host_match": True,
        "staging_validation_verified": True,
        "deterministic_release": True,
        "checksum_changed": True,
        "normalized_content_changed": True,
        "metadata_changed": True,
        "previous_issue_date": "2025-03",
        "current_issue_date": "2026-08",
        "previous_revision_date": "",
        "current_revision_date": "",
        "edition_changed": False,
    }


def test_newer_issue_date_auto_qualifies():
    result = evaluate_version_update(
        update_signals()
    )

    assert result["status"] == QUALIFIED
    assert (
        result["decision"]
        == AUTO_QUALIFIED
    )
    assert (
        result["signals"][
            "issue_date_comparison"
        ]
        == "newer"
    )

    validate_qualification_record(
        result
    )


def test_newer_revision_auto_qualifies():
    signals = update_signals()
    signals[
        "previous_issue_date"
    ] = "2026-08"
    signals[
        "current_issue_date"
    ] = "2026-08"
    signals[
        "previous_revision_date"
    ] = "2026-08-01"
    signals[
        "current_revision_date"
    ] = "2026-09-15"

    result = evaluate_version_update(
        signals
    )

    assert result["status"] == QUALIFIED


def test_date_regression_blocks():
    signals = update_signals()
    signals[
        "previous_issue_date"
    ] = "2026-08"
    signals[
        "current_issue_date"
    ] = "2025-03"

    result = evaluate_version_update(
        signals
    )

    assert result["status"] == BLOCKED


def test_identity_mismatch_blocks():
    signals = update_signals()
    signals[
        "document_code_match"
    ] = False

    result = evaluate_version_update(
        signals
    )

    assert result["status"] == BLOCKED


def test_packaging_only_change_requires_review():
    signals = update_signals()
    signals[
        "normalized_content_changed"
    ] = False

    result = evaluate_version_update(
        signals
    )

    assert (
        result["status"]
        == REVIEW_REQUIRED
    )


def test_unchanged_is_not_release():
    signals = update_signals()
    signals[
        "checksum_changed"
    ] = False
    signals[
        "normalized_content_changed"
    ] = False
    signals[
        "metadata_changed"
    ] = False
    signals[
        "previous_issue_date"
    ] = "2026-08"
    signals[
        "current_issue_date"
    ] = "2026-08"

    result = evaluate_version_update(
        signals
    )

    assert result["status"] == NO_CHANGE


def test_ambiguous_dates_require_review():
    signals = update_signals()
    signals[
        "previous_issue_date"
    ] = ""
    signals[
        "current_issue_date"
    ] = ""
    signals[
        "edition_changed"
    ] = False

    result = evaluate_version_update(
        signals
    )

    assert (
        result["status"]
        == REVIEW_REQUIRED
    )



def test_monitor_candidate_new_version():
    signals = update_signals()
    signals[
        "staging_validation_verified"
    ] = False
    signals[
        "deterministic_release"
    ] = False

    result = evaluate_version_candidate(
        signals
    )

    assert (
        result["decision"]
        == CANDIDATE_NEW_VERSION
    )
    assert (
        result["mode"]
        == "version_candidate"
    )


def test_monitor_candidate_packaging_only_review():
    signals = update_signals()
    signals[
        "normalized_content_changed"
    ] = False

    result = evaluate_version_candidate(
        signals
    )

    assert (
        result["status"]
        == REVIEW_REQUIRED
    )


def test_monitor_candidate_date_regression_blocks():
    signals = update_signals()
    signals[
        "previous_issue_date"
    ] = "2026-08"
    signals[
        "current_issue_date"
    ] = "2025-03"

    result = evaluate_version_candidate(
        signals
    )

    assert result["status"] == BLOCKED

def main():
    test_initial_release()
    test_initial_release_fail_closed()
    test_newer_issue_date_auto_qualifies()
    test_newer_revision_auto_qualifies()
    test_date_regression_blocks()
    test_identity_mismatch_blocks()
    test_packaging_only_change_requires_review()
    test_unchanged_is_not_release()
    test_ambiguous_dates_require_review()
    test_monitor_candidate_new_version()
    test_monitor_candidate_packaging_only_review()
    test_monitor_candidate_date_regression_blocks()

    print(
        "Version Qualification Policy v1: PASS"
    )
    print(
        "Initial release auto-qualification: PASS"
    )
    print(
        "Newer issue/revision policy: PASS"
    )
    print(
        "Ambiguous update exception review: PASS"
    )
    print(
        "Identity/date regression blocking: PASS"
    )
    print(
        "Monitor candidate pre-gate: PASS"
    )


if __name__ == "__main__":
    main()