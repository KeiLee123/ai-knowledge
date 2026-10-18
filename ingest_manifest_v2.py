#!/usr/bin/env python3

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path


INGESTER_VERSION = "phase-d3-1"
SUPPORTED_SCHEMA = "retrieval-chunks-v2"

DEFAULT_DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
DEFAULT_EMBED_URL = "http://127.0.0.1:8088/embed"
EXPECTED_DIMENSIONS = 384
EMBED_MODEL = "multilingual-e5-small"


def sql_quote(value) -> str:
    return str(value).replace("'", "''")


def load_chunks(path: Path) -> dict:
    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        data.get("schema_version")
        != SUPPORTED_SCHEMA
    ):
        raise RuntimeError(
            "Unsupported chunks schema: "
            f"{data.get('schema_version')!r}"
        )

    chunks = data.get("chunks")

    if not isinstance(chunks, list):
        raise RuntimeError(
            "chunks must be a list"
        )

    source_manifest = (
        data.get("source_manifest")
        or {}
    )

    document_sha256 = (
        source_manifest.get(
            "document_sha256"
        )
    )

    if not document_sha256:
        raise RuntimeError(
            "source_manifest.document_sha256 "
            "is missing"
        )

    for index, chunk in enumerate(
        chunks
    ):
        if not isinstance(chunk, dict):
            raise RuntimeError(
                f"Chunk {index} is not an object"
            )

        content = (
            chunk.get("content")
            or ""
        ).strip()

        if not content:
            raise RuntimeError(
                f"Chunk {index} has no content"
            )

        metadata = (
            chunk.get("metadata")
            or {}
        )

        if not isinstance(
            metadata,
            dict,
        ):
            raise RuntimeError(
                f"Chunk {index} metadata "
                "is not an object"
            )

        if (
            metadata.get(
                "evidence_tier"
            )
            not in {
                "primary",
                "supplementary",
            }
        ):
            raise RuntimeError(
                f"Chunk {index} has invalid "
                "evidence_tier"
            )

        page_start = (
            chunk.get("page_start")
        )

        page_end = (
            chunk.get("page_end")
        )

        if (
            page_start is not None
            and not isinstance(
                page_start,
                int,
            )
        ):
            raise RuntimeError(
                f"Chunk {index} has invalid "
                "page_start"
            )

        if (
            page_end is not None
            and not isinstance(
                page_end,
                int,
            )
        ):
            raise RuntimeError(
                f"Chunk {index} has invalid "
                "page_end"
            )

    if not chunks:
        raise RuntimeError(
            "No retrieval chunks to ingest"
        )

    return data


def embed(
    text: str,
    embed_url: str,
) -> list[float]:
    payload = json.dumps(
        {
            "inputs":
                "passage: " + text
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        embed_url,
        data=payload,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=60,
    ) as response:
        vector = json.loads(
            response.read().decode(
                "utf-8"
            )
        )[0]

    if len(vector) != EXPECTED_DIMENSIONS:
        raise RuntimeError(
            "Unexpected vector dimension: "
            f"{len(vector)}"
        )

    return [
        float(value)
        for value in vector
    ]


def vector_literal(
    vector: list[float],
) -> str:
    return (
        "["
        + ",".join(
            str(value)
            for value in vector
        )
        + "]"
    )


def merged_chunk_metadata(
    chunk: dict,
) -> dict:
    source = dict(
        chunk.get("metadata")
        or {}
    )

    source.update({
        "synthetic": False,
        "ingestion_version": "v2",
        "ingester_version":
            INGESTER_VERSION,
        "retrieval_role": (
            "multimodal-primary"
            if source.get(
                "evidence_tier"
            )
            == "primary"
            else
            "multimodal-supplementary"
        ),
    })

    return source


def document_metadata(
    payload: dict,
    chunks_path: Path,
) -> dict:
    source_manifest = (
        payload.get(
            "source_manifest"
        )
        or {}
    )

    summary = (
        payload.get("summary")
        or {}
    )

    return {
        "synthetic": False,
        "ingestion_version": "v2",
        "ingester_version":
            INGESTER_VERSION,
        "multimodal": True,
        "source_filename":
            source_manifest.get(
                "document_name"
            ),
        "source_chunks_file":
            chunks_path.name,
        "source_chunks_schema":
            payload.get(
                "schema_version"
            ),
        "source_manifest_sha256":
            source_manifest.get(
                "sha256"
            ),
        "retrieval_chunk_count":
            summary.get(
                "chunk_count",
                len(
                    payload.get(
                        "chunks"
                    )
                    or []
                ),
            ),
        "evidence_counts":
            summary.get(
                "counts_by_origin"
            )
            or {},
    }


def validate_embedding_sample(
    payload: dict,
    embed_url: str,
    sample_count: int,
) -> list[dict]:
    if sample_count <= 0:
        return []

    chunks = payload["chunks"]

    selected = chunks[
        :min(
            sample_count,
            len(chunks),
        )
    ]

    results = []

    for chunk in selected:
        vector = embed(
            chunk["content"],
            embed_url,
        )

        results.append({
            "chunk_index":
                chunk.get(
                    "chunk_index"
                ),
            "dimensions":
                len(vector),
            "origin":
                (
                    chunk.get(
                        "metadata"
                    )
                    or {}
                ).get(
                    "evidence_origin"
                ),
        })

    return results


def precompute_embeddings(
    payload: dict,
    embed_url: str,
) -> list[list[float]]:
    vectors = []

    for index, chunk in enumerate(
        payload["chunks"]
    ):
        print(
            "Embedding "
            f"{index + 1}/"
            f"{len(payload['chunks'])} "
            f"page={chunk.get('page_start')} "
            f"origin="
            f"{(chunk.get('metadata') or {}).get('evidence_origin')}"
        )

        vectors.append(
            embed(
                chunk["content"],
                embed_url,
            )
        )

    return vectors


def read_existing_document(
    checksum: str,
    db_container: str,
) -> str:
    sql = (
        "SELECT id "
        "FROM documents "
        "WHERE checksum_sha256 = "
        f"'{sql_quote(checksum)}' "
        "LIMIT 1;"
    )

    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            db_container,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Database duplicate check failed"
        )

    return result.stdout.strip()


def build_transaction_sql(
    payload: dict,
    vectors: list[list[float]],
    args,
    chunks_path: Path,
) -> str:
    chunks = payload["chunks"]
    source_manifest = (
        payload.get(
            "source_manifest"
        )
        or {}
    )

    checksum = source_manifest[
        "document_sha256"
    ]

    doc_metadata = json.dumps(
        document_metadata(
            payload,
            chunks_path,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    source_url_sql = (
        "'"
        + sql_quote(
            args.source_url
        )
        + "'"
        if args.source_url
        else "NULL"
    )

    lines = [
        r"\set ON_ERROR_STOP on",
        "BEGIN;",
        (
            "INSERT INTO documents ("
            "title, domain, topic, "
            "document_type, authority, "
            "jurisdiction, source_type, "
            "source_url, checksum_sha256, "
            "language, metadata"
            ") VALUES ("
            f"'{sql_quote(args.title)}', "
            f"'{sql_quote(args.domain)}', "
            f"'{sql_quote(args.topic)}', "
            f"'{sql_quote(args.document_type)}', "
            f"'{sql_quote(args.authority)}', "
            f"'{sql_quote(args.jurisdiction)}', "
            "'local-file-v2', "
            f"{source_url_sql}, "
            f"'{sql_quote(checksum)}', "
            f"'{sql_quote(args.language)}', "
            f"'{sql_quote(doc_metadata)}'::jsonb"
            ") RETURNING id AS doc_id "
            r"\gset"
        ),
    ]

    for index, (
        chunk,
        vector,
    ) in enumerate(
        zip(chunks, vectors)
    ):
        metadata = json.dumps(
            merged_chunk_metadata(
                chunk
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        page_start = (
            "NULL"
            if chunk.get(
                "page_start"
            )
            is None
            else str(
                int(
                    chunk[
                        "page_start"
                    ]
                )
            )
        )

        page_end = (
            "NULL"
            if chunk.get(
                "page_end"
            )
            is None
            else str(
                int(
                    chunk[
                        "page_end"
                    ]
                )
            )
        )

        content = (
            chunk["content"]
        )

        lines.append(
            (
                "INSERT INTO chunks ("
                "document_id, chunk_index, "
                "content, page_start, "
                "page_end, metadata"
                ") VALUES ("
                ":'doc_id', "
                f"{index}, "
                f"'{sql_quote(content)}', "
                f"{page_start}, "
                f"{page_end}, "
                f"'{sql_quote(metadata)}'::jsonb"
                ") RETURNING id AS chunk_id "
                r"\gset"
            )
        )

        lines.append(
            (
                "INSERT INTO embeddings ("
                "chunk_id, provider, model, "
                "dimensions, embedding"
                ") VALUES ("
                ":'chunk_id', "
                "'local', "
                f"'{EMBED_MODEL}', "
                f"{EXPECTED_DIMENSIONS}, "
                f"'{vector_literal(vector)}'::vector"
                ");"
            )
        )

    lines.extend([
        r"\echo DOCUMENT_ID :doc_id",
        "COMMIT;",
    ])

    return "\n".join(lines) + "\n"


def execute_transaction(
    sql: str,
    db_container: str,
) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            db_container,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Database transaction failed"
        )

    return result.stdout.strip()


def build_plan(
    payload: dict,
    chunks_path: Path,
    args,
) -> dict:
    chunks = payload["chunks"]
    source_manifest = (
        payload.get(
            "source_manifest"
        )
        or {}
    )

    origins = {}
    tiers = {}

    for chunk in chunks:
        metadata = (
            chunk.get(
                "metadata"
            )
            or {}
        )

        origin = metadata.get(
            "evidence_origin",
            "unknown",
        )

        tier = metadata.get(
            "evidence_tier",
            "unknown",
        )

        origins[origin] = (
            origins.get(
                origin,
                0,
            )
            + 1
        )

        tiers[tier] = (
            tiers.get(
                tier,
                0,
            )
            + 1
        )

    return {
        "mode":
            "write"
            if args.write
            else "validation-only",
        "ingester_version":
            INGESTER_VERSION,
        "schema_version":
            payload.get(
                "schema_version"
            ),
        "source_chunks":
            str(chunks_path),
        "document_sha256":
            source_manifest.get(
                "document_sha256"
            ),
        "document_name":
            source_manifest.get(
                "document_name"
            ),
        "title":
            args.title,
        "domain":
            args.domain,
        "topic":
            args.topic,
        "document_type":
            args.document_type,
        "authority":
            args.authority,
        "jurisdiction":
            args.jurisdiction,
        "language":
            args.language,
        "chunk_count":
            len(chunks),
        "counts_by_origin":
            origins,
        "counts_by_tier":
            tiers,
        "database_write_requested":
            bool(args.write),
        "embedding_sample_requested":
            args.validate_embeddings,
        "embedding_model":
            EMBED_MODEL,
        "embedding_dimensions":
            EXPECTED_DIMENSIONS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest retrieval-chunks-v2 into the "
            "existing documents/chunks/embeddings "
            "schema. Validation-only by default; "
            "requires --write for DB mutation."
        )
    )

    parser.add_argument(
        "chunks",
        help="retrieval-chunks-v2 JSON",
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
        default="",
    )

    parser.add_argument(
        "--document-type",
        default="reference",
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
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    parser.add_argument(
        "--embed-url",
        default=
            DEFAULT_EMBED_URL,
    )

    parser.add_argument(
        "--validate-embeddings",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Validation mode: embed first N "
            "chunks without writing DB"
        ),
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Actually write the document, chunks "
            "and embeddings in one DB transaction"
        ),
    )

    args = parser.parse_args()

    chunks_path = Path(
        args.chunks
    )

    if not chunks_path.is_file():
        raise SystemExit(
            f"Chunks file not found: "
            f"{chunks_path}"
        )

    if (
        args.validate_embeddings < 0
    ):
        raise SystemExit(
            "--validate-embeddings "
            "must be >= 0"
        )

    try:
        payload = load_chunks(
            chunks_path
        )

        plan = build_plan(
            payload,
            chunks_path,
            args,
        )

        print(
            json.dumps(
                plan,
                ensure_ascii=False,
                indent=2,
            )
        )

        if (
            not args.write
            and args.validate_embeddings
        ):
            sample = (
                validate_embedding_sample(
                    payload,
                    args.embed_url,
                    args.validate_embeddings,
                )
            )

            print()
            print(
                "EMBEDDING_VALIDATION"
            )

            print(
                json.dumps(
                    sample,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        if not args.write:
            print()
            print(
                "Validation complete. "
                "No database writes performed."
            )
            return

        checksum = (
            payload[
                "source_manifest"
            ][
                "document_sha256"
            ]
        )

        existing = (
            read_existing_document(
                checksum,
                args.db_container,
            )
        )

        if existing:
            raise RuntimeError(
                "Document checksum already exists "
                f"as document_id={existing}"
            )

        vectors = (
            precompute_embeddings(
                payload,
                args.embed_url,
            )
        )

        sql = build_transaction_sql(
            payload,
            vectors,
            args,
            chunks_path,
        )

        result = execute_transaction(
            sql,
            args.db_container,
        )

        print()
        print(
            "INGESTION_COMMITTED"
        )

        if result:
            print(result)

        print(
            f"Chunks: "
            f"{len(payload['chunks'])}"
        )

        print(
            "SHA256: "
            f"{checksum}"
        )

    except Exception as exc:
        raise SystemExit(
            "v2 ingestion failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


if __name__ == "__main__":
    main()
