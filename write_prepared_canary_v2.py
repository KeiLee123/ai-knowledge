#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    run_checked,
    verify_runtime,
)


PREPARED_WRITE_VERSION = "canary-prepared-write-v1"
SUPPORTED_SCHEMA = "retrieval-chunks-v2"


def load_prepared_chunks(
    path: Path,
) -> dict:
    if not path.is_file():
        raise RuntimeError(
            f"Prepared chunks file not found: {path}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if data.get("schema_version") != SUPPORTED_SCHEMA:
        raise RuntimeError(
            "Unsupported prepared chunks schema: "
            f"{data.get('schema_version')!r}"
        )

    chunks = data.get("chunks")

    if not isinstance(chunks, list) or not chunks:
        raise RuntimeError(
            "Prepared chunks payload must contain chunks"
        )

    source_manifest = (
        data.get("source_manifest")
        or {}
    )

    checksum = source_manifest.get(
        "document_sha256"
    )

    if not checksum:
        raise RuntimeError(
            "Prepared chunks payload is missing document_sha256"
        )

    return data


def build_prepared_write_command(
    repo_root: Path,
    python: str,
    chunks_path: Path,
    title: str,
    domain: str,
    topic: str,
    document_type: str,
    authority: str,
    jurisdiction: str,
    language: str,
    source_url: str,
) -> list[str]:
    ingester = (
        repo_root
        / "ingest_manifest_v2.py"
    )

    if not ingester.is_file():
        raise RuntimeError(
            f"Missing ingester: {ingester}"
        )

    command = [
        python,
        str(ingester),
        str(chunks_path),
        "--title",
        title,
        "--domain",
        domain,
        "--topic",
        topic,
        "--document-type",
        document_type,
        "--authority",
        authority,
        "--jurisdiction",
        jurisdiction,
        "--language",
        language,
        "--db-container",
        STAGING_DB_CONTAINER,
        "--check-db",
        "--write",
        "--confirm-live-write",
    ]

    if source_url:
        command.extend([
            "--source-url",
            source_url,
        ])

    return command


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Write an already-prepared Multimodal v2 artifact "
            "to the isolated Jason OS staging DB without "
            "re-running OCR or Vision."
        )
    )

    parser.add_argument(
        "chunks",
        help=(
            "retrieval-chunks-v2-with-source-pages.json "
            "from a completed canary prepare run"
        ),
    )

    parser.add_argument(
        "--title",
        required=True,
    )

    parser.add_argument(
        "--domain",
        required=True,
    )

    parser.add_argument(
        "--topic",
        required=True,
    )

    parser.add_argument(
        "--document-type",
        required=True,
    )

    parser.add_argument(
        "--authority",
        default="",
    )

    parser.add_argument(
        "--jurisdiction",
        default="HK",
    )

    parser.add_argument(
        "--language",
        default="en",
    )

    parser.add_argument(
        "--source-url",
        default="",
    )

    parser.add_argument(
        "--confirm-staging-write",
        action="store_true",
        help=(
            "Required explicit confirmation before "
            "the prepared artifact is written"
        ),
    )

    args = parser.parse_args()

    if not args.confirm_staging_write:
        raise SystemExit(
            "Prepared canary write requires "
            "--confirm-staging-write"
        )

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    try:
        guard = verify_runtime(
            repo_root
        )
    except Exception as exc:
        raise SystemExit(
            "CANARY GUARD FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    chunks_path = (
        Path(args.chunks)
        .expanduser()
        .resolve()
    )

    try:
        payload = load_prepared_chunks(
            chunks_path
        )
    except Exception as exc:
        raise SystemExit(
            "PREPARED ARTIFACT CHECK FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if STAGING_DB_CONTAINER == PRODUCTION_DB_CONTAINER:
        raise SystemExit(
            "Refusing to run: staging DB equals production DB"
        )

    source_manifest = (
        payload.get("source_manifest")
        or {}
    )

    print(
        json.dumps(
            {
                "prepared_write_version":
                    PREPARED_WRITE_VERSION,
                "guard_ok":
                    guard["guard_ok"],
                "branch":
                    guard["branch"],
                "db_container":
                    STAGING_DB_CONTAINER,
                "schema_version":
                    payload.get(
                        "schema_version"
                    ),
                "document_name":
                    source_manifest.get(
                        "document_name"
                    ),
                "document_sha256":
                    source_manifest.get(
                        "document_sha256"
                    ),
                "chunk_count":
                    len(
                        payload.get("chunks")
                        or []
                    ),
                "ocr_rerun":
                    False,
                "vision_rerun":
                    False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        "PREPARED CANARY WRITE: ARMED"
    )
    print(
        "LOCKED DB:",
        STAGING_DB_CONTAINER,
    )
    print(
        "OCR / Vision rerun: False"
    )
    print()

    command = build_prepared_write_command(
        repo_root=repo_root,
        python=sys.executable,
        chunks_path=chunks_path,
        title=args.title,
        domain=args.domain,
        topic=args.topic,
        document_type=args.document_type,
        authority=args.authority,
        jurisdiction=args.jurisdiction,
        language=args.language,
        source_url=args.source_url,
    )

    run_checked(
        command
    )


if __name__ == "__main__":
    main()
