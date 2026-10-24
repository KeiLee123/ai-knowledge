#!/usr/bin/env python3

import re


POLICY_VERSION = (
    "official-source-version-policy-v1"
)

QUALIFIED = "qualified"
REVIEW_REQUIRED = "review_required"
BLOCKED = "blocked"
NO_CHANGE = "no_change"

AUTO_QUALIFIED = "AUTO_QUALIFIED"
EXCEPTION_REVIEW = "REVIEW_REQUIRED"
POLICY_BLOCKED = "BLOCKED"
UNCHANGED = "NO_CHANGE"

DATE_RE = re.compile(
    r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$"
)


def parse_version_date(value):
    value = str(
        value or ""
    ).strip()

    if not value:
        return None

    match = DATE_RE.fullmatch(
        value
    )

    if not match:
        return None

    year = int(
        match.group(1)
    )
    month = int(
        match.group(2)
        or 0
    )
    day = int(
        match.group(3)
        or 0
    )

    if (
        month < 0
        or month > 12
        or day < 0
        or day > 31
    ):
        return None

    return year, month, day


def compare_version_date(
    previous,
    current,
) -> str:
    previous_value = (
        parse_version_date(
            previous
        )
    )
    current_value = (
        parse_version_date(
            current
        )
    )

    if (
        previous_value is None
        or current_value is None
    ):
        return "unknown"

    if current_value > previous_value:
        return "newer"

    if current_value < previous_value:
        return "older"

    return "same"


def result(
    *,
    mode: str,
    status: str,
    decision: str,
    reasons: list[str],
    signals: dict,
) -> dict:
    return {
        "method": "policy",
        "policy_version":
            POLICY_VERSION,
        "mode":
            mode,
        "status":
            status,
        "decision":
            decision,
        "reasons":
            reasons,
        "signals":
            signals,
    }


def evaluate_initial_release(
    signals: dict,
) -> dict:
    required = (
        "official_source_identity",
        "staging_validation_verified",
        "deterministic_release",
        "canonical_checksum_locked",
        "chunks_checksum_locked",
    )

    missing = [
        key
        for key in required
        if key not in signals
    ]

    if missing:
        return result(
            mode="initial_release",
            status=REVIEW_REQUIRED,
            decision=EXCEPTION_REVIEW,
            reasons=[
                "missing_signals:"
                + ",".join(
                    sorted(missing)
                )
            ],
            signals=signals,
        )

    failed = [
        key
        for key in required
        if signals.get(key)
        is not True
    ]

    if failed:
        return result(
            mode="initial_release",
            status=BLOCKED,
            decision=POLICY_BLOCKED,
            reasons=[
                "failed_safety_signals:"
                + ",".join(
                    sorted(failed)
                )
            ],
            signals=signals,
        )

    return result(
        mode="initial_release",
        status=QUALIFIED,
        decision=AUTO_QUALIFIED,
        reasons=[
            "official_identity_verified",
            "staging_validation_verified",
            "deterministic_release_verified",
            "artifact_hashes_locked",
        ],
        signals=signals,
    )


def evaluate_version_update(
    signals: dict,
) -> dict:
    identity_keys = (
        "authority_match",
        "document_code_match",
        "official_host_match",
    )

    hard_keys = (
        "staging_validation_verified",
        "deterministic_release",
    )

    required_change_keys = (
        "checksum_changed",
        "normalized_content_changed",
        "metadata_changed",
    )

    missing = [
        key
        for key in (
            *identity_keys,
            *hard_keys,
            *required_change_keys,
        )
        if key not in signals
    ]

    if missing:
        return result(
            mode="version_update",
            status=REVIEW_REQUIRED,
            decision=EXCEPTION_REVIEW,
            reasons=[
                "missing_signals:"
                + ",".join(
                    sorted(missing)
                )
            ],
            signals=signals,
        )

    failed_identity = [
        key
        for key in identity_keys
        if signals.get(key)
        is not True
    ]

    if failed_identity:
        return result(
            mode="version_update",
            status=BLOCKED,
            decision=POLICY_BLOCKED,
            reasons=[
                "source_identity_mismatch:"
                + ",".join(
                    sorted(
                        failed_identity
                    )
                )
            ],
            signals=signals,
        )

    failed_hard = [
        key
        for key in hard_keys
        if signals.get(key)
        is not True
    ]

    if failed_hard:
        return result(
            mode="version_update",
            status=BLOCKED,
            decision=POLICY_BLOCKED,
            reasons=[
                "failed_safety_signals:"
                + ",".join(
                    sorted(failed_hard)
                )
            ],
            signals=signals,
        )

    issue_cmp = (
        compare_version_date(
            signals.get(
                "previous_issue_date"
            ),
            signals.get(
                "current_issue_date"
            ),
        )
    )

    revision_cmp = (
        compare_version_date(
            signals.get(
                "previous_revision_date"
            ),
            signals.get(
                "current_revision_date"
            ),
        )
    )

    normalized_signals = dict(
        signals
    )
    normalized_signals[
        "issue_date_comparison"
    ] = issue_cmp
    normalized_signals[
        "revision_date_comparison"
    ] = revision_cmp

    if (
        issue_cmp == "older"
        or revision_cmp == "older"
    ):
        return result(
            mode="version_update",
            status=BLOCKED,
            decision=POLICY_BLOCKED,
            reasons=[
                "version_date_regression"
            ],
            signals=normalized_signals,
        )

    if (
        signals.get(
            "checksum_changed"
        )
        is False
        and signals.get(
            "normalized_content_changed"
        )
        is False
        and signals.get(
            "metadata_changed"
        )
        is False
    ):
        return result(
            mode="version_update",
            status=NO_CHANGE,
            decision=UNCHANGED,
            reasons=[
                "no_material_change"
            ],
            signals=normalized_signals,
        )

    forward_version = (
        issue_cmp == "newer"
        or revision_cmp == "newer"
        or signals.get(
            "edition_changed"
        )
        is True
    )

    material_change = (
        signals.get(
            "checksum_changed"
        )
        is True
        and signals.get(
            "normalized_content_changed"
        )
        is True
        and signals.get(
            "metadata_changed"
        )
        is True
    )

    if (
        forward_version
        and material_change
    ):
        return result(
            mode="version_update",
            status=QUALIFIED,
            decision=AUTO_QUALIFIED,
            reasons=[
                "forward_version_signal",
                "material_metadata_change",
                "normalized_content_change",
                "checksum_change",
                "staging_validation_verified",
                "deterministic_release_verified",
            ],
            signals=normalized_signals,
        )

    return result(
        mode="version_update",
        status=REVIEW_REQUIRED,
        decision=EXCEPTION_REVIEW,
        reasons=[
            "ambiguous_version_change"
        ],
        signals=normalized_signals,
    )


def evaluate_qualification(
    *,
    mode: str,
    signals: dict,
) -> dict:
    if mode == "initial_release":
        return evaluate_initial_release(
            signals
        )

    if mode == "version_update":
        return evaluate_version_update(
            signals
        )

    raise RuntimeError(
        "Unsupported qualification mode: "
        f"{mode!r}"
    )


def validate_qualification_record(
    record: dict,
) -> dict:
    if not isinstance(
        record,
        dict,
    ):
        raise RuntimeError(
            "qualification must be a mapping"
        )

    if (
        record.get("method")
        != "policy"
    ):
        raise RuntimeError(
            "qualification.method must be policy"
        )

    if (
        record.get(
            "policy_version"
        )
        != POLICY_VERSION
    ):
        raise RuntimeError(
            "Unsupported qualification policy"
        )

    mode = record.get(
        "mode"
    )
    signals = record.get(
        "signals"
    )

    if not isinstance(
        signals,
        dict,
    ):
        raise RuntimeError(
            "qualification.signals "
            "must be a mapping"
        )

    expected = (
        evaluate_qualification(
            mode=mode,
            signals=signals,
        )
    )

    if (
        record.get(
            "status"
        )
        != expected[
            "status"
        ]
        or record.get(
            "decision"
        )
        != expected[
            "decision"
        ]
    ):
        raise RuntimeError(
            "qualification result does not "
            "match policy evaluation"
        )

    if (
        expected[
            "status"
        ]
        != QUALIFIED
        or expected[
            "decision"
        ]
        != AUTO_QUALIFIED
    ):
        raise RuntimeError(
            "release is not policy-qualified"
        )

    return expected
