#!/usr/bin/env python3

import argparse
import hashlib
import json
import urllib.request

from pathlib import Path

import detect_source_changes_v1 as detector
import source_monitor_baseline_v1 as baseline

from extract_document_v2 import build_manifest
from version_qualification_policy_v1 import (
    CANDIDATE_NEW_VERSION,
    EXCEPTION_REVIEW,
    POLICY_BLOCKED,
    UNCHANGED,
    evaluate_version_candidate,
)
from version_signal_extractor_v1 import (
    build_version_signal_snapshot,
    compare_version_snapshots,
)
from version_snapshot_store_v1 import (
    current_snapshot_path,
    load_record,
    validate_state_root,
)


VERSION = "official-source-monitor-v1"
DEFAULT_STATE_ROOT = Path(
    "/var/lib/jason-os/source-monitor-staging"
)


def load_source(
    registry_path: Path,
    source_id: str,
) -> tuple[dict, dict, dict]:
    registry = detector.load_registry(
        registry_path
    )

    selected = detector.select_sources(
        registry,
        source_id=source_id,
    )

    source = selected[source_id]

    detector.validate_source(
        source_id,
        source,
    )

    return (
        registry,
        source,
        registry.get(
            "defaults"
        )
        or {},
    )


def download_candidate(
    *,
    source: dict,
    defaults: dict,
    destination: Path,
) -> dict:
    url = source[
        "canonical_url"
    ]

    allowed_hosts = source[
        "allowed_hosts"
    ]

    detector.validate_url(
        url,
        allowed_hosts,
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": str(
                defaults.get(
                    "user_agent",
                    "Jason-OS-Source-Monitor/1.0",
                )
            ),
            "Accept": "application/pdf",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=int(
            defaults.get(
                "timeout_seconds",
                60,
            )
        ),
    ) as response:
        body = response.read()
        final_url = response.geturl()

        detector.validate_url(
            final_url,
            allowed_hosts,
        )

        headers = response.headers

        if hasattr(
            headers,
            "get_content_type",
        ):
            content_type = (
                headers.get_content_type()
            )
        else:
            content_type = (
                headers.get(
                    "Content-Type",
                    "",
                )
                .split(";", 1)[0]
                .strip()
                .lower()
            )

    expected = (
        source[
            "expected_content_types"
        ][
            "document"
        ]
    )

    if content_type != expected:
        raise RuntimeError(
            "Candidate content type mismatch: "
            f"{content_type!r}; expected "
            f"{expected!r}"
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_bytes(
        body
    )

    return {
        "url": final_url,
        "content_type":
            content_type,
        "size_bytes":
            len(body),
        "sha256":
            hashlib.sha256(
                body
            ).hexdigest(),
    }


def load_reference(
    *,
    state_root: Path,
    source_id: str,
) -> tuple[Path, dict]:
    path = current_snapshot_path(
        state_root,
        source_id,
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Version reference not found: {path}"
        )

    record = load_record(
        path
    )

    if (
        record.get(
            "source_id"
        )
        != source_id
    ):
        raise RuntimeError(
            "Stored version reference "
            "source_id mismatch"
        )

    return path, record


def evaluate_candidate_snapshot(
    *,
    previous_snapshot: dict,
    current_snapshot: dict,
) -> tuple[dict, dict]:
    signals = (
        compare_version_snapshots(
            previous_snapshot,
            current_snapshot,
            staging_validation_verified=False,
            deterministic_release=False,
        )
    )

    qualification = (
        evaluate_version_candidate(
            signals
        )
    )

    return (
        signals,
        qualification,
    )


def decision_action(
    decision: str,
) -> str:
    if (
        decision
        == CANDIDATE_NEW_VERSION
    ):
        return (
            "STAGING_VALIDATION_REQUIRED"
        )

    if (
        decision
        == EXCEPTION_REVIEW
    ):
        return "EXCEPTION_REVIEW"

    if (
        decision
        == POLICY_BLOCKED
    ):
        return "STOP"

    if decision == UNCHANGED:
        return "NONE"

    raise RuntimeError(
        "Unsupported monitor decision: "
        f"{decision}"
    )


def monitor_source(
    *,
    registry_path: Path,
    source_id: str,
    state_root: Path,
    workdir: Path,
) -> dict:
    state_root = validate_state_root(
        state_root
    )

    (
        _registry,
        source,
        defaults,
    ) = load_source(
        registry_path,
        source_id,
    )

    check = (
        baseline.check_against_baseline(
            registry_path=registry_path,
            source_id=source_id,
            state_root=state_root,
        )
    )

    baseline_status = check[
        "status"
    ]

    if baseline_status in (
        "UNCHANGED",
        "INDEX_CHANGED",
    ):
        return {
            "version": VERSION,
            "source_id": source_id,
            "baseline_status":
                baseline_status,
            "decision": UNCHANGED,
            "action": "NONE",
            "candidate_downloaded":
                False,
            "production_access":
                False,
            "production_write":
                False,
        }

    if (
        baseline_status
        != "DOCUMENT_CHANGED"
    ):
        raise RuntimeError(
            "Unsupported baseline status: "
            f"{baseline_status}"
        )

    try:
        (
            reference_path,
            reference_record,
        ) = load_reference(
            state_root=state_root,
            source_id=source_id,
        )
    except FileNotFoundError:
        return {
            "version": VERSION,
            "source_id": source_id,
            "baseline_status":
                baseline_status,
            "decision":
                EXCEPTION_REVIEW,
            "action":
                "EXCEPTION_REVIEW",
            "reason":
                "missing_version_reference",
            "candidate_downloaded":
                False,
            "production_access":
                False,
            "production_write":
                False,
        }

    workdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    suffix = Path(
        urllib.request.url2pathname(
            source[
                "canonical_url"
            ]
        )
    ).suffix or ".pdf"

    candidate_path = (
        workdir
        / (
            source[
                "document_code"
            ]
            + "-candidate"
            + suffix
        )
    )

    download = download_candidate(
        source=source,
        defaults=defaults,
        destination=candidate_path,
    )

    expected_sha = (
        check[
            "changes"
        ][
            "document"
        ][
            "current_sha256"
        ]
    )

    if (
        download[
            "sha256"
        ]
        != expected_sha
    ):
        return {
            "version": VERSION,
            "source_id": source_id,
            "baseline_status":
                baseline_status,
            "decision":
                POLICY_BLOCKED,
            "action": "STOP",
            "reason":
                "source_changed_during_monitor_run",
            "candidate_downloaded":
                True,
            "candidate_sha256":
                download[
                    "sha256"
                ],
            "probed_sha256":
                expected_sha,
            "production_access":
                False,
            "production_write":
                False,
        }

    manifest = build_manifest(
        candidate_path
    )

    if (
        manifest[
            "source"
        ][
            "sha256"
        ]
        != expected_sha
    ):
        raise RuntimeError(
            "Candidate manifest SHA mismatch"
        )

    current_snapshot = (
        build_version_signal_snapshot(
            source_file=candidate_path,
            manifest=manifest,
            source=source,
        )
    )

    (
        signals,
        qualification,
    ) = evaluate_candidate_snapshot(
        previous_snapshot=(
            reference_record[
                "snapshot"
            ]
        ),
        current_snapshot=(
            current_snapshot
        ),
    )

    decision = qualification[
        "decision"
    ]

    return {
        "version": VERSION,
        "source_id": source_id,
        "baseline_status":
            baseline_status,
        "reference_path":
            str(reference_path),
        "candidate_path":
            str(candidate_path),
        "candidate_downloaded":
            True,
        "candidate_sha256":
            expected_sha,
        "signals":
            signals,
        "qualification":
            qualification,
        "decision":
            decision,
        "action":
            decision_action(
                decision
            ),
        "production_access":
            False,
        "production_write":
            False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Automatic Staging-only official "
            "source monitor integration. "
            "No Production access or write."
        )
    )

    parser.add_argument(
        "--registry",
        default=str(
            detector.DEFAULT_REGISTRY
        ),
    )

    parser.add_argument(
        "--source",
        required=True,
    )

    parser.add_argument(
        "--state-root",
        default=str(
            DEFAULT_STATE_ROOT
        ),
    )

    parser.add_argument(
        "--workdir",
        required=True,
    )

    args = parser.parse_args()

    result = monitor_source(
        registry_path=Path(
            args.registry
        ).resolve(),
        source_id=args.source,
        state_root=Path(
            args.state_root
        ),
        workdir=Path(
            args.workdir
        ).resolve(),
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    print()
    print(
        "STATUS: OFFICIAL_SOURCE_MONITOR "
        + result[
            "decision"
        ]
    )


if __name__ == "__main__":
    main()
