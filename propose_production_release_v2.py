#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from build_multimodal_chunks_v2 import (
    build_output,
)
from canonical_text_production_v2 import (
    sha256_file,
    write_json,
)
from extract_document_v2 import (
    build_manifest,
)
from ingest_canonical_staging_v1 import (
    download_canonical,
    load_expected_baseline,
    load_registry,
)
from ingest_manifest_v2 import (
    load_chunks,
    read_existing_document,
)
from ingest_canonical_text_staging_v1 import (
    resolve_text_source,
    validate_legacy_route,
)
from route_document_v2 import (
    assess_manifest,
)
from run_multimodal_canary_v2 import (
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from release_artifact_profiles_v2 import (
    CANONICAL_TEXT_PROFILE,
)
from version_qualification_policy_v1 import (
    evaluate_initial_release,
)


VERSION = "production-release-proposal-v2"


def run_validator(
    *,
    repo_root: Path,
    source_id: str,
    state_root: Path,
    validation: dict,
) -> None:
    command = [
        sys.executable,
        str(
            repo_root
            / "validate_canonical_text_staging_milestone_v1.py"
        ),
        source_id,
        "--state-root",
        str(state_root),
        "--query",
        validation["query"],
    ]

    for term in validation[
        "expect_terms"
    ]:
        command.extend(
            [
                "--expect-term",
                term,
            ]
        )

    result = subprocess.run(
        command,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Staging milestone validation failed"
        )


def validation_profile(
    source: dict,
) -> dict:
    config = source.get(
        "staging_validation"
    )

    if not isinstance(
        config,
        dict,
    ):
        raise RuntimeError(
            "staging_validation config missing"
        )

    query = str(
        config.get("query")
        or ""
    ).strip()

    terms = config.get(
        "expect_terms"
    )

    if (
        not query
        or not isinstance(
            terms,
            list,
        )
        or not terms
    ):
        raise RuntimeError(
            "staging_validation is incomplete"
        )

    return {
        "query": query,
        "expect_terms": [
            str(term).strip()
            for term in terms
            if str(term).strip()
        ],
    }


def build_contract_proposal(
    *,
    source_id: str,
    source: dict,
    text_config: dict,
    defaults: dict,
    checksum: str,
    chunks_sha256: str,
    chunk_count: int,
    staging_document_id: str,
    semantic: dict,
    qualification: dict,
) -> dict:
    return {
        "enabled": True,
        "authority_code":
            source.get(
                "authority_code"
            ),
        "publisher":
            source.get(
                "publisher"
            ),
        "source_type":
            source.get(
                "source_type"
            ),
        "document_code":
            source.get(
                "document_code"
            ),
        "title":
            source.get(
                "title"
            ),
        "canonical_url":
            source.get(
                "canonical_url"
            ),
        "domain":
            source.get(
                "domain"
            ),
        "topic":
            source.get(
                "topic"
            ),
        "release_v2": {
            "enabled": True,
            "artifact_profile":
                CANONICAL_TEXT_PROFILE,
            "release_id":
                f"{source_id.lower()}-{checksum[:12]}",
            "controller_environment":
                "production",
            "remote":
                text_config["remote"],
            "source":
                text_config["source"],
            "db_container":
                "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr",
            "required_route":
                "legacy-v1",
            "frozen_ingestion_version":
                "canonical-text-ingestion-v1",
            "expected_sha256":
                checksum,
            "expected_chunks_sha256":
                chunks_sha256,
            "expected_chunk_count":
                chunk_count,
            "expected_embedding_count":
                chunk_count,
            "expected_evidence_counts": {
                "native_text":
                    chunk_count,
            },
            "document_type":
                text_config.get(
                    "document_type"
                )
                or source.get(
                    "source_type"
                )
                or "official-document",
            "language":
                text_config.get(
                    "language"
                )
                or "en",
            "staging_document_id":
                int(staging_document_id),
            "staging_validation_status":
                "VERIFIED",
            "semantic_validation": {
                "checks": [
                    {
                        "label":
                            "staging_qualified_query",
                        "query":
                            semantic["query"],
                        "expect_terms":
                            semantic[
                                "expect_terms"
                            ],
                    }
                ]
            },
            "qualification":
                qualification,
            "write_authorized":
                False,
            "require_confirmation":
                True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only generator for a "
            "Generic Production Release v2 "
            "contract proposal. No Production "
            "access or writes."
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
            / "source_registry_v1.yaml"
        ),
    )

    parser.add_argument(
        "--state-root",
        default=(
            "/var/lib/jason-os/"
            "source-monitor-staging"
        ),
    )

    parser.add_argument(
        "--workdir",
        default="",
    )

    args = parser.parse_args()

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    state_root = (
        Path(args.state_root)
        .expanduser()
        .resolve()
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
                    "jason-os-release-v2-"
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

        registry = load_registry(
            Path(args.registry)
            .expanduser()
            .resolve()
        )

        source, text_config, defaults = (
            resolve_text_source(
                registry,
                args.source_id,
            )
        )

        baseline = (
            load_expected_baseline(
                state_root,
                args.source_id,
            )
        )

        semantic = validation_profile(
            source
        )

        run_validator(
            repo_root=repo_root,
            source_id=args.source_id,
            state_root=state_root,
            validation=semantic,
        )

        staging_document_id = (
            read_existing_document(
                baseline["sha256"],
                STAGING_DB_CONTAINER,
            )
        )

        if not staging_document_id:
            raise RuntimeError(
                "Qualified source is missing "
                "from the Staging DB"
            )

        source_file = (
            workdir
            / Path(
                text_config["source"]
            ).name
        )

        phase_a = (
            workdir
            / "phase-a.json"
        )

        chunks_path = (
            workdir
            / "retrieval-chunks-release-v2.json"
        )

        download_canonical(
            text_config,
            source_file,
        )

        actual_sha = sha256_file(
            source_file
        )

        if (
            actual_sha
            != baseline["sha256"]
        ):
            raise RuntimeError(
                "Canonical Drive checksum "
                "does not match approved baseline"
            )

        if (
            baseline.get(
                "content_length"
            )
            is not None
            and source_file.stat().st_size
            != baseline[
                "content_length"
            ]
        ):
            raise RuntimeError(
                "Canonical Drive size "
                "does not match approved baseline"
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

        validate_legacy_route(
            route
        )

        chunks = build_output(
            manifest_path=phase_a,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

        deterministic_check = build_output(
            manifest_path=phase_a,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

        if (
            json.dumps(
                chunks,
                sort_keys=True,
                separators=(",", ":"),
            )
            != json.dumps(
                deterministic_check,
                sort_keys=True,
                separators=(",", ":"),
            )
        ):
            raise RuntimeError(
                "Release artifact is not deterministic"
            )

        write_json(
            chunks_path,
            chunks,
        )

        chunks = load_chunks(
            chunks_path
        )

        chunk_count = len(
            chunks.get("chunks")
            or []
        )

        if chunk_count <= 0:
            raise RuntimeError(
                "Release proposal has no chunks"
            )

        counts = (
            chunks.get("summary")
            or {}
        ).get(
            "counts_by_origin"
        ) or {}

        if (
            counts.get(
                "native_text"
            )
            != chunk_count
        ):
            raise RuntimeError(
                "Release proposal contains "
                "non-native-text chunks"
            )

        qualification = (
            evaluate_initial_release(
                {
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
                }
            )
        )

        if (
            qualification[
                "status"
            ]
            != "qualified"
        ):
            raise RuntimeError(
                "Initial release failed "
                "policy qualification"
            )

        proposal = (
            build_contract_proposal(
                source_id=
                    args.source_id,
                source=source,
                text_config=
                    text_config,
                defaults=defaults,
                checksum=
                    baseline["sha256"],
                chunks_sha256=
                    sha256_file(
                        chunks_path
                    ),
                chunk_count=
                    chunk_count,
                staging_document_id=
                    staging_document_id,
                semantic=
                    semantic,
                qualification=
                    qualification,
            )
        )

        print(
            json.dumps(
                {
                    "version": VERSION,
                    "guard_ok":
                        guard["guard_ok"],
                    "branch":
                        guard["branch"],
                    "source_id":
                        args.source_id,
                    "staging_document_id":
                        int(
                            staging_document_id
                        ),
                    "canonical_sha256":
                        baseline["sha256"],
                    "chunks_sha256":
                        sha256_file(
                            chunks_path
                        ),
                    "chunk_count":
                        chunk_count,
                    "production_access":
                        False,
                    "production_write":
                        False,
                    "contract_proposal":
                        proposal,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "PRODUCTION_RELEASE_V2_PROPOSAL_READY"
        )

        if args.workdir:
            print(
                "Artifacts retained at:",
                workdir,
            )

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION RELEASE V2 PROPOSAL "
            "FAILED: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()