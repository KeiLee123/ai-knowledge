#!/usr/bin/env python3

import argparse
import json
import tempfile
from pathlib import Path

from build_multimodal_chunks_v2 import (
    build_output,
)
from canonical_text_production_v2 import (
    CHUNKS_FILENAME,
    build_transaction_sql,
    download_canonical,
    validate_chunk_contract,
    validate_chunks_file,
    verify_canonical_download,
    write_json,
)
from canonical_text_release_contract_v1 import (
    validate_legacy_route,
)
from extract_document_v2 import (
    build_manifest,
)
from ingest_manifest_v2 import (
    DEFAULT_EMBED_URL,
    check_database_contract,
    inspect_transaction_sql,
    load_chunks,
    precompute_embeddings,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    verify_runtime,
)
from production_release_contract_v2 import (
    load_release_registry,
    resolve_release_source,
)
from route_document_v2 import (
    assess_manifest,
)


VERSION = "canonical-text-production-prepare-v2"


def prepare_candidate(
    *,
    source_id: str,
    registry_path: Path,
    workdir: Path,
    guard: dict,
) -> dict:
    registry = load_release_registry(
        registry_path
    )

    source, config, defaults = (
        resolve_release_source(
            registry,
            source_id,
        )
    )

    source_file = (
        workdir
        / Path(
            config["source"]
        ).name
    )

    phase_a = (
        workdir
        / "phase-a.json"
    )

    chunks_path = (
        workdir
        / CHUNKS_FILENAME
    )

    download_canonical(
        config,
        source_file,
    )

    verified = (
        verify_canonical_download(
            source_file,
            config,
        )
    )

    manifest = build_manifest(
        source_file
    )

    write_json(
        phase_a,
        manifest,
    )

    route = assess_manifest(
        manifest,
        allow_partial=False,
    )

    decision = validate_legacy_route(
        route
    )

    chunks_payload = build_output(
        manifest_path=phase_a,
        manifest=manifest,
        target_chars=1800,
        overlap_chars=250,
    )

    write_json(
        chunks_path,
        chunks_payload,
    )

    chunks_payload = load_chunks(
        chunks_path
    )

    frozen = validate_chunk_contract(
        chunks_payload,
        config,
    )

    chunks_sha256 = (
        validate_chunks_file(
            chunks_path,
            config,
        )
    )

    checksum = config[
        "expected_sha256"
    ]

    db_contract = check_database_contract(
        checksum,
        PRODUCTION_DB_CONTAINER,
    )

    if not db_contract[
        "contract_ok"
    ]:
        raise RuntimeError(
            "Production database contract check failed"
        )

    if (
        db_contract.get(
            "duplicate_checksum"
        )
        is not None
    ):
        raise RuntimeError(
            "Document checksum already exists "
            "in Production"
        )

    return {
        "source":
            source,
        "config":
            config,
        "defaults":
            defaults,
        "source_file":
            source_file,
        "chunks_path":
            chunks_path,
        "chunks_payload":
            chunks_payload,
        "verified":
            verified,
        "route_decision":
            decision,
        "chunk_contract":
            frozen,
        "chunks_sha256":
            chunks_sha256,
        "db_contract":
            db_contract,
        "guard":
            guard,
    }


def summary(
    *,
    source_id: str,
    mode: str,
    candidate: dict,
) -> dict:
    config = candidate[
        "config"
    ]

    return {
        "version":
            VERSION,
        "source_id":
            source_id,
        "mode":
            mode,
        "guard_ok":
            candidate[
                "guard"
            ]["guard_ok"],
        "branch":
            candidate[
                "guard"
            ]["branch"],
        "db_container":
            PRODUCTION_DB_CONTAINER,
        "release_id":
            config[
                "release_id"
            ],
        "release_reviewed":
            config[
                "release_reviewed"
            ],
        "write_authorized":
            config[
                "write_authorized"
            ],
        "canonical_source":
            config[
                "source"
            ],
        "sha256":
            candidate[
                "verified"
            ]["sha256"],
        "size_bytes":
            candidate[
                "verified"
            ]["size_bytes"],
        "required_route":
            config[
                "required_route"
            ],
        "observed_route":
            candidate[
                "route_decision"
            ].get(
                "recommended_pipeline"
            ),
        "expected_chunk_count":
            config[
                "expected_chunk_count"
            ],
        "chunk_count":
            candidate[
                "chunk_contract"
            ]["chunk_count"],
        "chunks_sha256":
            candidate[
                "chunks_sha256"
            ],
        "expected_embedding_count":
            config[
                "expected_embedding_count"
            ],
        "database_contract_ok":
            candidate[
                "db_contract"
            ]["contract_ok"],
        "duplicate_checksum":
            candidate[
                "db_contract"
            ].get(
                "duplicate_checksum"
            ),
        "production_write":
            False,
        "database_write_requested":
            False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generic Production Promotion v2 "
            "verify/prepare gate. Read-only "
            "against Production."
        )
    )

    parser.add_argument(
        "source_id"
    )

    mode = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--verify",
        action="store_true",
    )

    mode.add_argument(
        "--prepare",
        action="store_true",
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
        "--workdir",
        default="",
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

    temp_context = None

    if args.workdir:
        workdir = (
            Path(args.workdir)
            .expanduser()
            .resolve()
        )
        workdir.mkdir(
            parents=True,
            exist_ok=True,
        )
    else:
        temp_context = (
            tempfile.TemporaryDirectory(
                prefix=(
                    "jason-os-production-v2-"
                )
            )
        )
        workdir = Path(
            temp_context.name
        )

    try:
        guard = verify_runtime(
            repo_root
        )

        candidate = prepare_candidate(
            source_id=args.source_id,
            registry_path=(
                Path(args.registry)
                .expanduser()
                .resolve()
            ),
            workdir=workdir,
            guard=guard,
        )

        print(
            json.dumps(
                summary(
                    source_id=
                        args.source_id,
                    mode=(
                        "prepare"
                        if args.prepare
                        else "verify"
                    ),
                    candidate=
                        candidate,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        if args.verify:
            print()
            print(
                "STATUS: "
                "PRODUCTION_RELEASE_V2_VERIFIED"
            )
            print(
                "Database writes performed: False"
            )
            return

        vectors = precompute_embeddings(
            candidate[
                "chunks_payload"
            ],
            args.embed_url,
        )

        sql = build_transaction_sql(
            payload=
                candidate[
                    "chunks_payload"
                ],
            vectors=vectors,
            chunks_path=
                candidate[
                    "chunks_path"
                ],
            source=
                candidate[
                    "source"
                ],
            config=
                candidate[
                    "config"
                ],
            defaults=
                candidate[
                    "defaults"
                ],
        )

        inspection = (
            inspect_transaction_sql(
                sql,
                candidate[
                    "config"
                ][
                    "expected_chunk_count"
                ],
            )
        )

        if not inspection[
            "transaction_contract_ok"
        ]:
            raise RuntimeError(
                "Generated Production v2 "
                "transaction failed "
                "structural validation"
            )

        print()
        print(
            "PRODUCTION_V2_TRANSACTION"
        )
        print(
            json.dumps(
                inspection,
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "READY_FOR_PRODUCTION_V2_WRITE_REVIEW"
        )
        print(
            "Transaction SQL was not executed."
        )
        print(
            "Database writes performed: False"
        )

        if args.workdir:
            print(
                "Artifacts retained at:",
                workdir,
            )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION RELEASE V2 "
            "VERIFY/PREPARE FAILED: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
