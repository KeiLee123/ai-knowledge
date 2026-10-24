#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path

from version_qualification_policy_v1 import (
    AUTO_QUALIFIED,
    QUALIFIED,
    REVIEW_REQUIRED,
    evaluate_version_update,
)
from version_signal_extractor_v1 import (
    build_version_signal_snapshot,
    compare_version_snapshots,
)


SOURCE = {
    "authority_code": "BD",
    "source_family": "PNAP",
    "document_code": "APP-149",
    "title": "Test PNAP",
    "canonical_url": (
        "https://www.bd.gov.hk/"
        "doc/en/test/APP149.pdf"
    ),
}


def manifest(
    *,
    text: str,
    sha: str,
):
    return {
        "source": {
            "filename": "APP149.pdf",
            "sha256": sha,
        },
        "document": {
            "kind": "pdf",
            "page_count": 3,
        },
        "units": [
            {
                "unit_index": 0,
                "text": text,
            }
        ],
    }


def test_pnap_version_dates():
    snap = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text=(
                "This PNAP is previously known "
                "as PNAP 999\n"
                "First issue January 2020\n"
                "Last revision May 2024\n"
                "This revision September 2025 "
                "(AD/NB2)"
            ),
            sha="a" * 64,
        ),
        source=SOURCE,
        pdf_metadata={
            "title": "Test PNAP",
            "author": "Buildings Department",
            "producer": "volatile-producer",
        },
    )

    assert (
        snap["first_issue_date"]
        == "2020-01"
    )
    assert (
        snap["last_revision_date"]
        == "2024-05"
    )
    assert (
        snap["revision_date"]
        == "2025-09"
    )
    assert (
        snap["issue_date"]
        == "2025-09"
    )
    assert (
        snap[
            "revision_date_source"
        ]
        == "explicit_this_revision"
    )


def test_footer_revision_fallback():
    snap = build_version_signal_snapshot(
        source_file=Path(
            "APP146.pdf"
        ),
        manifest=manifest(
            text=(
                "Illustrative Diagram "
                "(3/2025)"
            ),
            sha="b" * 64,
        ),
        source={
            **SOURCE,
            "document_code":
                "APP-146",
        },
        pdf_metadata={},
    )

    assert (
        snap["revision_date"]
        == "2025-03"
    )
    assert (
        snap[
            "revision_date_source"
        ]
        == "pnap_footer_month_year"
    )


def test_content_fingerprint_is_whitespace_stable():
    a = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text="Alpha   Beta\nGamma",
            sha="a" * 64,
        ),
        source=SOURCE,
        pdf_metadata={},
    )

    b = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text="Alpha Beta Gamma",
            sha="a" * 64,
        ),
        source=SOURCE,
        pdf_metadata={},
    )

    assert (
        a[
            "normalized_content_fingerprint"
        ]
        == b[
            "normalized_content_fingerprint"
        ]
    )


def test_packaging_metadata_is_ignored():
    base = manifest(
        text=(
            "First issue January 2020 "
            "This revision September 2025"
        ),
        sha="a" * 64,
    )

    a = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=base,
        source=SOURCE,
        pdf_metadata={
            "title": "Stable title",
            "producer": "Producer A",
            "creationDate": "A",
        },
    )

    b = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=base,
        source=SOURCE,
        pdf_metadata={
            "title": "Stable title",
            "producer": "Producer B",
            "creationDate": "B",
        },
    )

    assert (
        a["metadata_fingerprint"]
        == b["metadata_fingerprint"]
    )


def test_material_metadata_change_detected():
    base = manifest(
        text=(
            "First issue January 2020 "
            "This revision September 2025"
        ),
        sha="a" * 64,
    )

    a = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=base,
        source=SOURCE,
        pdf_metadata={
            "title": "Title A",
        },
    )

    b = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=base,
        source=SOURCE,
        pdf_metadata={
            "title": "Title B",
        },
    )

    assert (
        a["metadata_fingerprint"]
        != b["metadata_fingerprint"]
    )


def test_snapshot_compare_drives_policy():
    previous = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text=(
                "First issue January 2020 "
                "This revision May 2024 "
                "old content"
            ),
            sha="a" * 64,
        ),
        source=SOURCE,
        pdf_metadata={
            "title": "Revision 2024",
        },
    )

    current = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text=(
                "First issue January 2020 "
                "Last revision May 2024 "
                "This revision September 2025 "
                "new content"
            ),
            sha="b" * 64,
        ),
        source=SOURCE,
        pdf_metadata={
            "title": "Revision 2025",
        },
    )

    signals = compare_version_snapshots(
        previous,
        current,
        staging_validation_verified=True,
        deterministic_release=True,
    )

    result = evaluate_version_update(
        signals
    )

    assert result["status"] == QUALIFIED
    assert (
        result["decision"]
        == AUTO_QUALIFIED
    )


def test_packaging_only_change_requires_review():
    previous = build_version_signal_snapshot(
        source_file=Path(
            "APP149.pdf"
        ),
        manifest=manifest(
            text=(
                "First issue January 2020 "
                "This revision May 2024 "
                "same content"
            ),
            sha="a" * 64,
        ),
        source=SOURCE,
        pdf_metadata={
            "title": "Stable",
        },
    )

    current = deepcopy(
        previous
    )
    current[
        "document_sha256"
    ] = "b" * 64

    signals = compare_version_snapshots(
        previous,
        current,
        staging_validation_verified=True,
        deterministic_release=True,
    )

    result = evaluate_version_update(
        signals
    )

    assert (
        result["status"]
        == REVIEW_REQUIRED
    )


def main():
    test_pnap_version_dates()
    test_footer_revision_fallback()
    test_content_fingerprint_is_whitespace_stable()
    test_packaging_metadata_is_ignored()
    test_material_metadata_change_detected()
    test_snapshot_compare_drives_policy()
    test_packaging_only_change_requires_review()

    print(
        "Version Signal Extractor v1: PASS"
    )
    print(
        "PNAP issue/revision extraction: PASS"
    )
    print(
        "Material metadata fingerprint: PASS"
    )
    print(
        "Normalized content fingerprint: PASS"
    )
    print(
        "Policy-ready snapshot comparison: PASS"
    )


if __name__ == "__main__":
    main()
