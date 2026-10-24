#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from canonical_text_production_v2 import (
    run_production_query,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    verify_runtime,
)
from production_read_only_retrieval_v1 import (
    DEFAULT_EMBED_URL,
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    build_retrieval_sql,
    embed_query,
    parse_rows,
)
from production_release_contract_v2 import (
    FROZEN_INGESTION_VERSION,
    RELEASE_GATE_VERSION,
    REQUIRED_ROUTE,
    load_release_registry,
    resolve_release_source,
    validate_semantic_validation,
)


VALIDATOR_VERSION = "canonical-text-production-validator-v2"


def build_integrity_sql(
    checksum: str,
) -> str:
    return f"""
SELECT json_build_object(
    'document_count', (
        SELECT COUNT(*)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'document_id', (
        SELECT MIN(id)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'source_type', (
        SELECT MIN(source_type)
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'ingestion_version', (
        SELECT MIN(metadata->>'ingestion_version')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'release_gate', (
        SELECT MIN(metadata->>'release_gate')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'release_id', (
        SELECT MIN(metadata->>'release_id')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'canonical_sha256', (
        SELECT MIN(metadata->>'canonical_sha256')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'multimodal', (
        SELECT MIN(metadata->>'multimodal')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'routing_profile', (
        SELECT MIN(metadata->>'routing_profile')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'canonical_source', (
        SELECT MIN(metadata->>'canonical_source')
        FROM documents
        WHERE checksum_sha256 = '{checksum}'
    ),
    'chunk_count', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
    ),
    'embedding_count', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
          ON c.id = e.chunk_id
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND e.provider = 'local'
          AND e.model = '{EMBED_MODEL}'
    ),
    'bad_embedding_dimensions', (
        SELECT COUNT(*)
        FROM embeddings e
        JOIN chunks c
          ON c.id = e.chunk_id
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND e.provider = 'local'
          AND e.model = '{EMBED_MODEL}'
          AND COALESCE(e.dimensions, -1) <> {EXPECTED_DIMENSIONS}
    ),
    'native_text_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND c.metadata->>'evidence_origin' = 'native_text'
    ),
    'text_primary_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND c.metadata->>'retrieval_role' = 'text-primary'
    ),
    'wrong_release_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'release_gate', '') <> '{RELEASE_GATE_VERSION}'
    ),
    'wrong_release_id_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'release_id', '') <> (
              SELECT MIN(metadata->>'release_id')
              FROM documents
              WHERE checksum_sha256 = '{checksum}'
          )
    ),
    'wrong_ingestion_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'ingestion_version', '') <> '{FROZEN_INGESTION_VERSION}'
    ),
    'multimodal_chunks', (
        SELECT COUNT(*)
        FROM chunks c
        JOIN documents d
          ON d.id = c.document_id
        WHERE d.checksum_sha256 = '{checksum}'
          AND COALESCE(c.metadata->>'multimodal', '') <> 'false'
    )
)::text;
""".strip()


def validate_integrity(
    payload: dict,
    *,
    config: dict,
) -> dict:
    expected = int(
        config[
            "expected_chunk_count"
        ]
    )

    values = {
        "document_count":
            int(
                payload.get(
                    "document_count"
                )
                or 0
            ),
        "chunk_count":
            int(
                payload.get(
                    "chunk_count"
                )
                or 0
            ),
        "embedding_count":
            int(
                payload.get(
                    "embedding_count"
                )
                or 0
            ),
        "native_text_chunks":
            int(
                payload.get(
                    "native_text_chunks"
                )
                or 0
            ),
        "text_primary_chunks":
            int(
                payload.get(
                    "text_primary_chunks"
                )
                or 0
            ),
        "bad_embedding_dimensions":
            int(
                payload.get(
                    "bad_embedding_dimensions"
                )
                or 0
            ),
        "wrong_release_chunks":
            int(
                payload.get(
                    "wrong_release_chunks"
                )
                or 0
            ),
        "wrong_release_id_chunks":
            int(
                payload.get(
                    "wrong_release_id_chunks"
                )
                or 0
            ),
        "wrong_ingestion_chunks":
            int(
                payload.get(
                    "wrong_ingestion_chunks"
                )
                or 0
            ),
        "multimodal_chunks":
            int(
                payload.get(
                    "multimodal_chunks"
                )
                or 0
            ),
    }

    errors = []

    if values[
        "document_count"
    ] != 1:
        errors.append(
            "document_count must be 1"
        )

    for key in (
        "chunk_count",
        "embedding_count",
        "native_text_chunks",
        "text_primary_chunks",
    ):
        if values[key] != expected:
            errors.append(
                f"{key} must be {expected}, "
                f"got {values[key]}"
            )

    for key in (
        "bad_embedding_dimensions",
        "wrong_release_chunks",
        "wrong_release_id_chunks",
        "wrong_ingestion_chunks",
        "multimodal_chunks",
    ):
        if values[key] != 0:
            errors.append(
                f"{key} must be 0, "
                f"got {values[key]}"
            )

    if (
        payload.get("source_type")
        != "canonical-drive-text"
    ):
        errors.append(
            "source_type mismatch"
        )

    if (
        payload.get(
            "ingestion_version"
        )
        != FROZEN_INGESTION_VERSION
    ):
        errors.append(
            "ingestion_version mismatch"
        )

    if (
        payload.get(
            "release_gate"
        )
        != RELEASE_GATE_VERSION
    ):
        errors.append(
            "release_gate mismatch"
        )

    if (
        payload.get(
            "release_id"
        )
        != config[
            "release_id"
        ]
    ):
        errors.append(
            "release_id mismatch"
        )

    if (
        payload.get(
            "canonical_sha256"
        )
        != config[
            "expected_sha256"
        ]
    ):
        errors.append(
            "canonical_sha256 mismatch"
        )

    if (
        payload.get(
            "multimodal"
        )
        != "false"
    ):
        errors.append(
            "multimodal must be false"
        )

    if (
        payload.get(
            "routing_profile"
        )
        != REQUIRED_ROUTE
    ):
        errors.append(
            "routing_profile mismatch"
        )

    if (
        payload.get(
            "canonical_source"
        )
        != config[
            "source"
        ]
    ):
        errors.append(
            "canonical_source mismatch"
        )

    if errors:
        raise RuntimeError(
            "; ".join(errors)
        )

    return {
        "document_id":
            payload.get(
                "document_id"
            ),
        "document_count":
            values[
                "document_count"
            ],
        "chunk_count":
            values[
                "chunk_count"
            ],
        "embedding_count":
            values[
                "embedding_count"
            ],
        "native_text_chunks":
            values[
                "native_text_chunks"
            ],
        "text_primary_chunks":
            values[
                "text_primary_chunks"
            ],
        "embedding_dimensions":
            EXPECTED_DIMENSIONS,
        "integrity_ok":
            True,
    }


def semantic_check(
    *,
    checksum: str,
    check: dict,
    limit: int,
    embed_url: str,
) -> dict:
    vector = embed_query(
        check["query"],
        embed_url,
    )

    rows = parse_rows(
        run_production_query(
            build_retrieval_sql(
                checksum=checksum,
                vector=vector,
                limit=limit,
            )
        )
    )

    if not rows:
        raise RuntimeError(
            f"{check['label']} returned no rows"
        )

    for row in rows:
        if (
            row.get(
                "evidence_origin"
            )
            != "native_text"
        ):
            raise RuntimeError(
                f"{check['label']} contains "
                "non-native_text evidence"
            )

        if (
            row.get(
                "evidence_tier"
            )
            != "primary"
        ):
            raise RuntimeError(
                f"{check['label']} contains "
                "non-primary evidence"
            )

        if (
            row.get(
                "retrieval_role"
            )
            != "text-primary"
        ):
            raise RuntimeError(
                f"{check['label']} contains "
                "non-text-primary evidence"
            )

    joined = "\n".join(
        row.get("content")
        or ""
        for row in rows
    ).lower()

    missing = [
        term
        for term in check[
            "expect_terms"
        ]
        if term.lower()
        not in joined
    ]

    if missing:
        raise RuntimeError(
            f"{check['label']} missing "
            "expected term(s): "
            + ", ".join(missing)
        )

    return {
        "label":
            check["label"],
        "result_count":
            len(rows),
        "expected_terms":
            check[
                "expect_terms"
            ],
        "semantic_ok":
            True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only generic Production "
            "post-write validator v2."
        )
    )

    parser.add_argument(
        "source_id"
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__)
            .resolve()
            .parent
            / "production_release_registry_v2.yaml"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--embed-url",
        default=DEFAULT_EMBED_URL,
    )

    args = parser.parse_args()

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    try:
        guard = verify_runtime(
            repo_root
        )

        registry = load_release_registry(
            Path(args.registry)
            .expanduser()
            .resolve()
        )

        _, config, _ = (
            resolve_release_source(
                registry,
                args.source_id,
            )
        )

        checksum = config[
            "expected_sha256"
        ]

        payload = json.loads(
            run_production_query(
                build_integrity_sql(
                    checksum
                )
            ).strip()
        )

        integrity = (
            validate_integrity(
                payload,
                config=config,
            )
        )

        semantic = [
            semantic_check(
                checksum=checksum,
                check=check,
                limit=args.limit,
                embed_url=
                    args.embed_url,
            )
            for check
            in validate_semantic_validation(
                config
            )
        ]

        print(
            json.dumps(
                {
                    "validator_version":
                        VALIDATOR_VERSION,
                    "guard_ok":
                        guard[
                            "guard_ok"
                        ],
                    "branch":
                        guard[
                            "branch"
                        ],
                    "db_container":
                        PRODUCTION_DB_CONTAINER,
                    "read_only":
                        True,
                    "source_id":
                        args.source_id,
                    "release_id":
                        config[
                            "release_id"
                        ],
                    "checksum":
                        checksum,
                    "integrity":
                        integrity,
                    "semantic_checks":
                        semantic,
                    "production_write":
                        False,
                    "production_validation_status":
                        "VERIFIED",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "CANONICAL_TEXT_PRODUCTION_V2_VALIDATED"
        )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION V2 VALIDATION "
            "FAILED: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


if __name__ == "__main__":
    main()
