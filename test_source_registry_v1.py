#!/usr/bin/env python3

from pathlib import Path
from unittest.mock import patch

import detect_source_changes_v1 as monitor


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "source_registry_v1.yaml"
SCRIPT = ROOT / "detect_source_changes_v1.py"


def fake_observation(
    url,
    content_type
):
    return {
        "url": url,
        "status": 200,
        "content_type": content_type,
        "content_length": 123,
        "sha256": "a" * 64,
        "etag": None,
        "last_modified": None,
    }


def test_registry_contract():
    registry = monitor.load_registry(
        REGISTRY
    )

    assert (
        registry[
            "source_registry_version"
        ]
        == 1
    )

    lifecycle = (
        registry[
            "defaults"
        ][
            "lifecycle"
        ]
    )

    assert (
        lifecycle[
            "production_write"
        ]
        is False
    )
    assert (
        lifecycle[
            "qualification_policy"
        ]
        == "official-source-version-policy-v1"
    )
    assert (
        lifecycle[
            "exception_review"
        ]
        is True
    )
    assert (
        "require_human_review"
        not in lifecycle
    )

    source = registry[
        "sources"
    ]["BD_PNAP_APP145"]

    assert source["enabled"] is True
    assert (
        source["authority_code"]
        == "BD"
    )
    assert (
        source["source_family"]
        == "PNAP"
    )
    assert (
        source["document_code"]
        == "APP-145"
    )

    monitor.validate_source(
        "BD_PNAP_APP145",
        source
    )

    source_146 = registry[
        "sources"
    ]["BD_PNAP_APP146"]

    assert source_146["enabled"] is True
    assert (
        source_146["authority_code"]
        == "BD"
    )
    assert (
        source_146["source_family"]
        == "PNAP"
    )
    assert (
        source_146["document_code"]
        == "APP-146"
    )
    assert (
        source_146["title"]
        == "Metal Gates"
    )

    monitor.validate_source(
        "BD_PNAP_APP146",
        source_146
    )

    source_149 = registry[
        "sources"
    ]["BD_PNAP_APP149"]

    assert source_149["enabled"] is True
    assert (
        source_149["authority_code"]
        == "BD"
    )
    assert (
        source_149["source_family"]
        == "PNAP"
    )
    assert (
        source_149["document_code"]
        == "APP-149"
    )

    monitor.validate_source(
        "BD_PNAP_APP149",
        source_149
    )

    assert (
        registry["sources"]["BD_PNAP_APP146"]
        ["canonical_text_ingestion"]["enabled"]
        is False
    )

    selected = monitor.select_sources(
        registry
    )

    assert list(selected) == [
        "BD_PNAP_APP145",
        "BD_PNAP_APP146",
        "BD_PNAP_APP149",
    ]


def test_url_guard():
    allowed = ["www.bd.gov.hk"]

    monitor.validate_url(
        "https://www.bd.gov.hk/test",
        allowed
    )

    try:
        monitor.validate_url(
            "http://www.bd.gov.hk/test",
            allowed
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "HTTP URL should be rejected."
        )

    try:
        monitor.validate_url(
            "https://example.com/test",
            allowed
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Unregistered host should "
            "be rejected."
        )


def test_probe_without_network():
    registry = monitor.load_registry(
        REGISTRY
    )

    source = registry[
        "sources"
    ]["BD_PNAP_APP145"]

    defaults = registry.get(
        "defaults",
        {}
    )

    calls = []

    def fake_fetch(
        url,
        *,
        timeout_seconds,
        user_agent,
        allowed_hosts
    ):
        calls.append(url)

        if url == source["index_url"]:
            return fake_observation(
                url,
                "text/html"
            )

        if url == source[
            "canonical_url"
        ]:
            return fake_observation(
                url,
                "application/pdf"
            )

        raise AssertionError(
            f"Unexpected URL: {url}"
        )

    with patch.object(
        monitor,
        "fetch_resource",
        side_effect=fake_fetch
    ):
        result = monitor.probe_source(
            "BD_PNAP_APP145",
            source,
            defaults
        )

    assert calls == [
        source["index_url"],
        source["canonical_url"],
    ]

    assert (
        result["document_code"]
        == "APP-145"
    )

    assert (
        result["index"][
            "content_type"
        ]
        == "text/html"
    )

    assert (
        result["document"][
            "content_type"
        ]
        == "application/pdf"
    )


def test_read_only_contract():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "psycopg",
        "subprocess",
        "docker exec",
        "rclone ",
        "INSERT INTO",
        "DELETE FROM",
        "UPDATE ",
        "gdrive-out:",
    )

    for token in forbidden:
        assert token not in text, (
            "Read-only detector contains "
            f"forbidden token: {token}"
        )


def main():
    test_registry_contract()
    test_url_guard()
    test_probe_without_network()
    test_read_only_contract()

    print(
        "Source Registry v1 contract: PASS"
    )


if __name__ == "__main__":
    main()