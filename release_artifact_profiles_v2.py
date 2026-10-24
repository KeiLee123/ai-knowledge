#!/usr/bin/env python3

CANONICAL_TEXT_PROFILE = "canonical-text-v1"
MULTIMODAL_PROFILE = "multimodal-v2"

RELEASE_GATE_VERSION = "generic-production-promotion-v2"

ARTIFACT_PROFILES = {
    CANONICAL_TEXT_PROFILE: {
        "required_route":
            "legacy-v1",
        "ingestion_version":
            "canonical-text-ingestion-v1",
        "multimodal":
            False,
        "allowed_evidence_origins": {
            "native_text",
        },
        "production_write_qualified":
            True,
    },
    MULTIMODAL_PROFILE: {
        "required_route":
            "multimodal-v2",
        "ingestion_version":
            "v2",
        "multimodal":
            True,
        "allowed_evidence_origins": {
            "native_text",
            "ocr_text",
            "fused_text",
            "visual_understanding",
            "structured_table",
        },
        "production_write_qualified":
            False,
    },
}


def validate_artifact_profile(
    value,
) -> str:
    profile = str(
        value or ""
    ).strip()

    if profile not in ARTIFACT_PROFILES:
        raise RuntimeError(
            "Unknown release artifact profile: "
            f"{profile!r}"
        )

    return profile


def artifact_profile_contract(
    value,
) -> dict:
    profile = validate_artifact_profile(
        value
    )

    return {
        "artifact_profile":
            profile,
        **ARTIFACT_PROFILES[
            profile
        ],
    }


def validate_expected_evidence_counts(
    config: dict,
    *,
    expected_chunk_count: int,
) -> dict:
    profile = artifact_profile_contract(
        config.get(
            "artifact_profile"
        )
    )

    counts = config.get(
        "expected_evidence_counts"
    )

    if not isinstance(
        counts,
        dict,
    ):
        raise RuntimeError(
            "expected_evidence_counts "
            "must be a mapping"
        )

    normalized = {}

    for origin, count in counts.items():
        origin = str(
            origin or ""
        ).strip()

        if origin not in profile[
            "allowed_evidence_origins"
        ]:
            raise RuntimeError(
                "Evidence origin is not "
                "allowed for "
                f"{profile['artifact_profile']}: "
                f"{origin!r}"
            )

        if (
            not isinstance(
                count,
                int,
            )
            or isinstance(
                count,
                bool,
            )
            or count <= 0
        ):
            raise RuntimeError(
                "Evidence counts must be "
                "positive integers"
            )

        normalized[
            origin
        ] = count

    if (
        sum(
            normalized.values()
        )
        != expected_chunk_count
    ):
        raise RuntimeError(
            "expected_evidence_counts total "
            "must equal expected_chunk_count"
        )

    if (
        profile[
            "artifact_profile"
        ]
        == CANONICAL_TEXT_PROFILE
        and normalized
        != {
            "native_text":
                expected_chunk_count
        }
    ):
        raise RuntimeError(
            "canonical-text-v1 requires "
            "native_text-only evidence"
        )

    return normalized
