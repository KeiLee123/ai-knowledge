#!/usr/bin/env python3

import re
from pathlib import Path

import yaml

from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)


REGISTRY_VERSION = 2
VERSION = "production-release-contract-v2"
ALLOWED_REMOTE = "gdrive-bd-write:"
REQUIRED_ROUTE = "legacy-v1"
FROZEN_INGESTION_VERSION = "canonical-text-ingestion-v1"
RELEASE_GATE_VERSION = "canonical-text-production-promotion-v2"
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_release_registry(path: Path) -> dict:
    payload = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Production release v2 registry must be a mapping"
        )

    if (
        payload.get("production_release_registry_version")
        != REGISTRY_VERSION
    ):
        raise RuntimeError(
            "Unsupported Production release v2 registry version"
        )

    sources = payload.get("sources")

    if not isinstance(sources, dict):
        raise RuntimeError(
            "Production release v2 registry sources must be a mapping"
        )

    return payload


def validate_source_id(source_id: str) -> str:
    if not SAFE_SOURCE_ID.fullmatch(source_id):
        raise RuntimeError(
            "Unsafe Production release v2 source id"
        )

    return source_id


def validate_sha256(value, label: str) -> str:
    value = str(value or "").lower()

    if not SHA256_RE.fullmatch(value):
        raise RuntimeError(
            f"{label} must be lowercase SHA-256"
        )

    return value


def validate_semantic_validation(config: dict) -> list[dict]:
    semantic = config.get("semantic_validation")

    if not isinstance(semantic, dict):
        raise RuntimeError(
            "semantic_validation config missing"
        )

    checks = semantic.get("checks")

    if not isinstance(checks, list) or not checks:
        raise RuntimeError(
            "semantic_validation.checks must be a non-empty list"
        )

    normalized = []

    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise RuntimeError(
                f"semantic check {index} must be a mapping"
            )

        label = str(
            check.get("label")
            or f"query_{index + 1}"
        ).strip()

        query = str(
            check.get("query")
            or ""
        ).strip()

        terms = check.get("expect_terms")

        if not query:
            raise RuntimeError(
                f"semantic check {label} query is required"
            )

        if (
            not isinstance(terms, list)
            or not terms
            or not all(
                isinstance(term, str)
                and term.strip()
                for term in terms
            )
        ):
            raise RuntimeError(
                f"semantic check {label} expect_terms "
                "must be a non-empty string list"
            )

        normalized.append(
            {
                "label": label,
                "query": query,
                "expect_terms": [
                    term.strip()
                    for term in terms
                ],
            }
        )

    return normalized


def validate_release_config(
    config: dict,
    *,
    require_write_authorized: bool = False,
) -> dict:
    errors = []

    if config.get("enabled") is not True:
        errors.append(
            "canonical_text_release_v2 must be enabled"
        )

    release_id = str(
        config.get("release_id")
        or ""
    ).strip()

    if not release_id:
        errors.append(
            "release_id is required"
        )

    if (
        config.get("controller_environment")
        != "production"
    ):
        errors.append(
            "controller_environment must be production"
        )

    if config.get("remote") != ALLOWED_REMOTE:
        errors.append(
            "remote must be the isolated BD writer"
        )

    source = config.get("source")

    if (
        not isinstance(source, str)
        or source.startswith("/")
        or not source.startswith("Current/")
        or not source.lower().endswith(".pdf")
        or ".." in Path(source).parts
    ):
        errors.append(
            "source must be a PDF under Current/"
        )

    if (
        config.get("db_container")
        != PRODUCTION_DB_CONTAINER
    ):
        errors.append(
            "db_container must be the fixed Production DB"
        )

    if (
        config.get("db_container")
        == STAGING_DB_CONTAINER
    ):
        errors.append(
            "Staging DB container is forbidden"
        )

    if (
        config.get("required_route")
        != REQUIRED_ROUTE
    ):
        errors.append(
            "required_route must be legacy-v1"
        )

    if (
        config.get("frozen_ingestion_version")
        != FROZEN_INGESTION_VERSION
    ):
        errors.append(
            "frozen_ingestion_version must match "
            + FROZEN_INGESTION_VERSION
        )

    for field in (
        "expected_sha256",
        "expected_chunks_sha256",
    ):
        try:
            validate_sha256(
                config.get(field),
                field,
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    chunk_count = config.get(
        "expected_chunk_count"
    )
    embedding_count = config.get(
        "expected_embedding_count"
    )

    if (
        not isinstance(chunk_count, int)
        or chunk_count <= 0
    ):
        errors.append(
            "expected_chunk_count must be positive"
        )

    if (
        not isinstance(embedding_count, int)
        or embedding_count <= 0
    ):
        errors.append(
            "expected_embedding_count must be positive"
        )

    if (
        isinstance(chunk_count, int)
        and isinstance(embedding_count, int)
        and chunk_count != embedding_count
    ):
        errors.append(
            "expected_embedding_count must equal "
            "expected_chunk_count"
        )

    if config.get("release_reviewed") is not True:
        errors.append(
            "release_reviewed must be true"
        )

    if (
        not isinstance(
            config.get("write_authorized"),
            bool,
        )
    ):
        errors.append(
            "write_authorized must be boolean"
        )

    if config.get("require_confirmation") is not True:
        errors.append(
            "require_confirmation must be true"
        )

    if (
        require_write_authorized
        and config.get("write_authorized")
        is not True
    ):
        errors.append(
            "write_authorized must be true"
        )

    try:
        validate_semantic_validation(
            config
        )
    except RuntimeError as exc:
        errors.append(str(exc))

    if errors:
        raise RuntimeError(
            "; ".join(errors)
        )

    return config


def resolve_release_source(
    registry: dict,
    source_id: str,
    *,
    require_write_authorized: bool = False,
):
    validate_source_id(
        source_id
    )

    source = (
        registry.get("sources")
        or {}
    ).get(source_id)

    if not isinstance(source, dict):
        raise RuntimeError(
            f"Unknown Production release v2 source: {source_id}"
        )

    if source.get("enabled") is not True:
        raise RuntimeError(
            "Production release v2 source is disabled"
        )

    config = source.get(
        "canonical_text_release_v2"
    )

    if not isinstance(config, dict):
        raise RuntimeError(
            "canonical_text_release_v2 config missing"
        )

    validate_release_config(
        config,
        require_write_authorized=
            require_write_authorized,
    )

    return (
        source,
        config,
        registry.get("defaults")
        or {},
    )


def canonical_remote_path(
    config: dict,
) -> str:
    return (
        str(config["remote"])
        + str(config["source"])
    )
