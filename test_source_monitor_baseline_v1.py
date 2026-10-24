#!/usr/bin/env python3

import json
import tempfile

from pathlib import Path
from unittest.mock import patch

import source_monitor_baseline_v1 as baseline


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "source_registry_v1.yaml"
SCRIPT = ROOT / "source_monitor_baseline_v1.py"


def observation(
    *,
    checked_at,
    index_hash,
    document_hash
):
    return {
        "source_id": "BD_PNAP_APP145",
        "checked_at": checked_at,
        "authority_code": "BD",
        "publisher": "Buildings Department",
        "source_family": "PNAP",
        "document_code": "APP-145",
        "index": {
            "url": (
                "https://www.bd.gov.hk/"
                "index_pnap.html"
            ),
            "status": 200,
            "content_type": "text/html",
            "content_length": 100,
            "sha256": index_hash,
            "etag": None,
            "last_modified": "A",
        },
        "document": {
            "url": (
                "https://www.bd.gov.hk/"
                "APP145.pdf"
            ),
            "status": 200,
            "content_type":
                "application/pdf",
            "content_length": 50,
            "sha256": document_hash,
            "etag": None,
            "last_modified": "B",
        },
    }


def fake_registry():
    return {
        "source_registry_version": 1
    }


def test_initialize_and_unchanged():
    first = observation(
        checked_at="2026-10-20T18:18:09+00:00",
        index_hash="a" * 64,
        document_hash="b" * 64,
    )

    second = observation(
        checked_at="2026-10-20T18:18:53+00:00",
        index_hash="a" * 64,
        document_hash="b" * 64,
    )

    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()

        with patch.object(
            baseline,
            "probe",
            return_value=(
                fake_registry(),
                first,
            ),
        ):
            created = (
                baseline.initialize_baseline(
                    registry_path=REGISTRY,
                    source_id="BD_PNAP_APP145",
                    state_root=root,
                )
            )

        assert (
            created["status"]
            == "BASELINE_CREATED"
        )

        path = baseline.baseline_path(
            root,
            "BD_PNAP_APP145"
        )

        assert path.exists()

        stored = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        assert (
            stored["observation"][
                "document"
            ]["sha256"]
            == "b" * 64
        )

        with patch.object(
            baseline,
            "probe",
            return_value=(
                fake_registry(),
                second,
            ),
        ):
            checked = (
                baseline.check_against_baseline(
                    registry_path=REGISTRY,
                    source_id="BD_PNAP_APP145",
                    state_root=root,
                )
            )

        assert (
            checked["status"]
            == "UNCHANGED"
        )

        assert (
            checked["changes"][
                "index"
            ]["changed"]
            is False
        )

        assert (
            checked["changes"][
                "document"
            ]["changed"]
            is False
        )


def test_document_change_priority():
    first = observation(
        checked_at="A",
        index_hash="a" * 64,
        document_hash="b" * 64,
    )

    second = observation(
        checked_at="B",
        index_hash="c" * 64,
        document_hash="d" * 64,
    )

    status, changes = (
        baseline.compare_observations(
            first,
            second,
        )
    )

    assert status == "DOCUMENT_CHANGED"
    assert (
        changes["index"]["changed"]
        is True
    )
    assert (
        changes["document"]["changed"]
        is True
    )


def test_index_only_change():
    first = observation(
        checked_at="A",
        index_hash="a" * 64,
        document_hash="b" * 64,
    )

    second = observation(
        checked_at="B",
        index_hash="c" * 64,
        document_hash="b" * 64,
    )

    status, changes = (
        baseline.compare_observations(
            first,
            second,
        )
    )

    assert status == "INDEX_CHANGED"
    assert (
        changes["index"]["changed"]
        is True
    )
    assert (
        changes["document"]["changed"]
        is False
    )


def test_refuse_overwrite():
    first = observation(
        checked_at="A",
        index_hash="a" * 64,
        document_hash="b" * 64,
    )

    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()

        with patch.object(
            baseline,
            "probe",
            return_value=(
                fake_registry(),
                first,
            ),
        ):
            baseline.initialize_baseline(
                registry_path=REGISTRY,
                source_id="BD_PNAP_APP145",
                state_root=root,
            )

            try:
                baseline.initialize_baseline(
                    registry_path=REGISTRY,
                    source_id="BD_PNAP_APP145",
                    state_root=root,
                )
            except FileExistsError:
                pass
            else:
                raise AssertionError(
                    "Existing baseline "
                    "must not be overwritten."
                )


def test_state_root_guard():
    try:
        baseline.validate_state_root(
            "relative/path"
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Relative state-root "
            "should be rejected."
        )


def test_no_external_writers():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "psycopg",
        "docker exec",
        "rclone ",
        "gdrive-out:",
        "INSERT INTO",
        "DELETE FROM",
        "UPDATE ",
    )

    for token in forbidden:
        assert token not in text, (
            "Baseline layer contains "
            f"forbidden token: {token}"
        )


def main():
    test_initialize_and_unchanged()
    test_document_change_priority()
    test_index_only_change()
    test_refuse_overwrite()
    test_state_root_guard()
    test_no_external_writers()

    print(
        "Source Monitor baseline v1: PASS"
    )


if __name__ == "__main__":
    main()
