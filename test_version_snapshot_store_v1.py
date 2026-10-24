#!/usr/bin/env python3

import json
import tempfile

from copy import deepcopy
from pathlib import Path

from version_snapshot_store_v1 import (
    advance_reference,
    compare_reference,
    current_snapshot_path,
    history_snapshot_path,
    initialize_reference,
    load_record,
    validate_state_root,
)


SOURCE_ID = "BD_PNAP_APP149"


def snapshot(
    *,
    issue_date,
    revision_date,
    document_sha,
    metadata_sha,
    content_sha,
):
    return {
        "version_signals_version": 1,
        "extractor_version":
            "version-signal-snapshot-v1",
        "source_family": "PNAP",
        "authority_code": "BD",
        "document_code": "APP-149",
        "canonical_host":
            "www.bd.gov.hk",
        "issue_date": issue_date,
        "first_issue_date":
            "2010-12",
        "last_revision_date":
            None,
        "revision_date":
            revision_date,
        "revision_date_source":
            "test",
        "edition": None,
        "page_count": 5,
        "metadata_fingerprint":
            metadata_sha,
        "normalized_content_fingerprint":
            content_sha,
        "normalized_content_chars":
            100,
        "document_sha256":
            document_sha,
        "material_metadata": {},
    }


def proposal(
    *,
    snap,
    release_id,
):
    qualification = {
        "method": "policy",
        "policy_version":
            "official-source-version-policy-v1",
        "mode": "initial_release",
        "status": "qualified",
        "decision": "AUTO_QUALIFIED",
        "reasons": [
            "test"
        ],
        "signals": {
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
        },
    }

    return {
        "version":
            "production-release-proposal-v2",
        "source_id":
            SOURCE_ID,
        "canonical_sha256":
            snap[
                "document_sha256"
            ],
        "version_signals":
            snap,
        "production_access":
            False,
        "production_write":
            False,
        "contract_proposal": {
            "release_v2": {
                "release_id":
                    release_id,
                "artifact_profile":
                    "canonical-text-v1",
                "version_signals":
                    snap,
                "qualification":
                    qualification,
                "write_authorized":
                    False,
            }
        },
    }


def test_initialize_and_no_change():
    old = snapshot(
        issue_date="2010-12",
        revision_date="2010-12",
        document_sha="a" * 64,
        metadata_sha="b" * 64,
        content_sha="c" * 64,
    )

    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()

        result = initialize_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=old,
                release_id="release-a",
            ),
            accepted_at="2026-10-24T00:00:00+00:00",
        )

        assert (
            result["status"]
            == "REFERENCE_INITIALIZED"
        )

        compared = compare_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=old,
                release_id="release-a",
            ),
        )

        assert (
            compared[
                "qualification"
            ]["decision"]
            == "NO_CHANGE"
        )


def test_qualified_advance_archives_old():
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

    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()

        initialize_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=old,
                release_id="release-a",
            ),
            accepted_at="2026-10-24T00:00:00+00:00",
        )

        compared = compare_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=new,
                release_id="release-b",
            ),
        )

        assert (
            compared[
                "qualification"
            ]["decision"]
            == "AUTO_QUALIFIED"
        )

        advanced = advance_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=new,
                release_id="release-b",
            ),
            accepted_at="2026-10-25T00:00:00+00:00",
        )

        assert (
            advanced["status"]
            == "REFERENCE_ADVANCED"
        )

        current = load_record(
            current_snapshot_path(
                root,
                SOURCE_ID,
            )
        )

        assert (
            current[
                "snapshot"
            ][
                "document_sha256"
            ]
            == "d" * 64
        )

        history = (
            history_snapshot_path(
                root,
                SOURCE_ID,
                "a" * 64,
            )
        )

        assert history.exists()

        archived = load_record(
            history
        )

        assert (
            archived[
                "snapshot"
            ][
                "document_sha256"
            ]
            == "a" * 64
        )


def test_ambiguous_change_cannot_advance():
    old = snapshot(
        issue_date="2010-12",
        revision_date="2010-12",
        document_sha="a" * 64,
        metadata_sha="b" * 64,
        content_sha="c" * 64,
    )

    packaging_only = deepcopy(
        old
    )
    packaging_only[
        "document_sha256"
    ] = "d" * 64

    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()

        initialize_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=old,
                release_id="release-a",
            ),
        )

        compared = compare_reference(
            state_root=root,
            source_id=SOURCE_ID,
            proposal=proposal(
                snap=packaging_only,
                release_id="release-b",
            ),
        )

        assert (
            compared[
                "qualification"
            ]["decision"]
            == "REVIEW_REQUIRED"
        )

        try:
            advance_reference(
                state_root=root,
                source_id=SOURCE_ID,
                proposal=proposal(
                    snap=packaging_only,
                    release_id="release-b",
                ),
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Ambiguous update advanced reference"
            )

        current = load_record(
            current_snapshot_path(
                root,
                SOURCE_ID,
            )
        )

        assert (
            current[
                "snapshot"
            ][
                "document_sha256"
            ]
            == "a" * 64
        )


def test_production_state_root_forbidden():
    try:
        validate_state_root(
            "/var/lib/jason-os/"
            "source-monitor-production"
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Production state root accepted"
        )


def main():
    test_initialize_and_no_change()
    test_qualified_advance_archives_old()
    test_ambiguous_change_cannot_advance()
    test_production_state_root_forbidden()

    print(
        "Version Snapshot Store v1: PASS"
    )
    print(
        "Initial reference persistence: PASS"
    )
    print(
        "NO_CHANGE comparison: PASS"
    )
    print(
        "AUTO_QUALIFIED advance + history: PASS"
    )
    print(
        "Ambiguous advance blocking: PASS"
    )
    print(
        "Production state root exclusion: PASS"
    )


if __name__ == "__main__":
    main()
