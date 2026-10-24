#!/usr/bin/env python3

import hashlib
import json
import subprocess
from pathlib import Path

from ingest_manifest_v2 import (
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    sql_quote,
    vector_literal,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
)
from production_release_contract_v2 import (
    FROZEN_INGESTION_VERSION,
    RELEASE_GATE_VERSION,
    REQUIRED_ROUTE,
    canonical_remote_path,
    validate_sha256,
)


CHUNKS_FILENAME = "retrieval-chunks-production-v2.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def download_canonical(
    config: dict,
    destination: Path,
) -> None:
    result = subprocess.run(
        [
            "rclone",
            "copyto",
            canonical_remote_path(config),
            str(destination),
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Canonical Drive download failed"
        )


def verify_canonical_download(
    path: Path,
    config: dict,
) -> dict:
    actual = sha256_file(path)
    expected = validate_sha256(
        config["expected_sha256"],
        "expected_sha256",
    )

    if actual != expected:
        raise RuntimeError(
            "Canonical SHA-256 does not match "
            "the Git-controlled release contract"
        )

    return {
        "sha256": actual,
        "size_bytes": path.stat().st_size,
        "verified": True,
    }


def validate_chunk_contract(
    payload: dict,
    config: dict,
) -> dict:
    chunks = payload.get("chunks") or []
    expected = int(
        config["expected_chunk_count"]
    )

    if len(chunks) != expected:
        raise RuntimeError(
            "Chunk count drift: "
            f"expected {expected}, got {len(chunks)}"
        )

    counts = (
        payload.get("summary")
        or {}
    ).get(
        "counts_by_origin"
    ) or {}

    if counts.get("native_text") != expected:
        raise RuntimeError(
            "native_text count drift: "
            f"expected {expected}, got "
            f"{counts.get('native_text')}"
        )

    for index, chunk in enumerate(chunks):
        metadata = chunk.get(
            "metadata"
        ) or {}

        if (
            metadata.get("evidence_origin")
            != "native_text"
        ):
            raise RuntimeError(
                f"Chunk {index} is not native_text"
            )

        if (
            metadata.get("evidence_tier")
            != "primary"
        ):
            raise RuntimeError(
                f"Chunk {index} is not primary evidence"
            )

    source_manifest = (
        payload.get("source_manifest")
        or {}
    )

    if (
        source_manifest.get("document_sha256")
        != config["expected_sha256"]
    ):
        raise RuntimeError(
            "Chunk source checksum does not match "
            "release contract"
        )

    return {
        "chunk_count": len(chunks),
        "native_text_chunks": expected,
        "chunk_contract_ok": True,
    }


def validate_chunks_file(
    path: Path,
    config: dict,
) -> str:
    actual = sha256_file(path)
    expected = validate_sha256(
        config["expected_chunks_sha256"],
        "expected_chunks_sha256",
    )

    if actual != expected:
        raise RuntimeError(
            "Prepared chunks SHA-256 does not match "
            "the Git-controlled release contract"
        )

    return actual


def document_metadata(
    payload: dict,
    chunks_path: Path,
    canonical_source: str,
    canonical_sha256: str,
    release_id: str,
) -> dict:
    source_manifest = (
        payload.get("source_manifest")
        or {}
    )
    summary = (
        payload.get("summary")
        or {}
    )

    return {
        "synthetic": False,
        "ingestion_version":
            FROZEN_INGESTION_VERSION,
        "ingester_version":
            FROZEN_INGESTION_VERSION,
        "release_gate":
            RELEASE_GATE_VERSION,
        "release_id":
            release_id,
        "multimodal":
            False,
        "routing_profile":
            REQUIRED_ROUTE,
        "canonical_source":
            canonical_source,
        "canonical_sha256":
            canonical_sha256,
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
                    payload.get("chunks")
                    or []
                ),
            ),
        "evidence_counts":
            summary.get(
                "counts_by_origin"
            ) or {},
    }


def chunk_metadata(
    chunk: dict,
    release_id: str,
) -> dict:
    metadata = dict(
        chunk.get("metadata")
        or {}
    )

    metadata.update(
        {
            "synthetic": False,
            "ingestion_version":
                FROZEN_INGESTION_VERSION,
            "ingester_version":
                FROZEN_INGESTION_VERSION,
            "release_gate":
                RELEASE_GATE_VERSION,
            "release_id":
                release_id,
            "retrieval_role":
                "text-primary",
            "multimodal":
                False,
        }
    )

    return metadata


def build_transaction_sql(
    *,
    payload: dict,
    vectors: list[list[float]],
    chunks_path: Path,
    source: dict,
    config: dict,
    defaults: dict,
) -> str:
    chunks = payload["chunks"]

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Embedding count does not match "
            f"chunk count: {len(vectors)} "
            f"!= {len(chunks)}"
        )

    if (
        len(vectors)
        != config[
            "expected_embedding_count"
        ]
    ):
        raise RuntimeError(
            "Embedding count does not match "
            "release contract"
        )

    checksum = (
        payload[
            "source_manifest"
        ]["document_sha256"]
    )

    if checksum != config["expected_sha256"]:
        raise RuntimeError(
            "Transaction checksum does not match "
            "release contract"
        )

    title = str(
        source.get("title")
        or source.get("document_code")
        or "Canonical document"
    )
    domain = str(
        source.get("domain")
        or "unknown"
    )
    topic = str(
        source.get("topic")
        or ""
    )
    document_type = str(
        config.get("document_type")
        or source.get("source_type")
        or "official-document"
    )
    authority = str(
        source.get("authority_code")
        or ""
    )
    jurisdiction = str(
        defaults.get("jurisdiction")
        or "HK"
    )
    language = str(
        config.get("language")
        or "en"
    )
    source_url = str(
        source.get("canonical_url")
        or ""
    )

    metadata = json.dumps(
        document_metadata(
            payload,
            chunks_path,
            config["source"],
            config["expected_sha256"],
            config["release_id"],
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    source_url_sql = (
        "'" + sql_quote(source_url) + "'"
        if source_url
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
            f"'{sql_quote(title)}', "
            f"'{sql_quote(domain)}', "
            f"'{sql_quote(topic)}', "
            f"'{sql_quote(document_type)}', "
            f"'{sql_quote(authority)}', "
            f"'{sql_quote(jurisdiction)}', "
            "'canonical-drive-text', "
            f"{source_url_sql}, "
            f"'{sql_quote(checksum)}', "
            f"'{sql_quote(language)}', "
            f"'{sql_quote(metadata)}'::jsonb"
            ") RETURNING id AS doc_id "
            r"\gset"
        ),
    ]

    for index, (
        chunk,
        vector,
    ) in enumerate(
        zip(
            chunks,
            vectors,
        )
    ):
        metadata = json.dumps(
            chunk_metadata(
                chunk,
                config["release_id"],
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
                    chunk["page_start"]
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
                    chunk["page_end"]
                )
            )
        )

        lines.append(
            (
                "INSERT INTO chunks ("
                "document_id, chunk_index, "
                "content, page_start, page_end, "
                "metadata"
                ") VALUES ("
                ":'doc_id', "
                f"{index}, "
                f"'{sql_quote(chunk['content'])}', "
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

    lines.extend(
        [
            r"\echo DOCUMENT_ID :doc_id",
            "COMMIT;",
        ]
    )

    return "\n".join(
        lines
    ) + "\n"


def build_zero_state_sql(
    checksum: str,
) -> str:
    checksum = validate_sha256(
        checksum,
        "checksum",
    )

    return f"""
SELECT json_build_object(
    'document_count', (
        SELECT COUNT(*)
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
    )
)::text;
""".strip()


def parse_json_payload(
    text: str,
    label: str,
) -> dict:
    payload = json.loads(
        text.strip()
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            f"{label} did not return "
            "a JSON object"
        )

    return payload


def validate_zero_state(
    payload: dict,
) -> dict:
    counts = {
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
    }

    if any(
        counts.values()
    ):
        raise RuntimeError(
            "Production candidate checksum "
            "already has rows: "
            + json.dumps(
                counts,
                sort_keys=True,
            )
        )

    return {
        **counts,
        "zero_state_ok": True,
    }


def run_production_query(
    sql: str,
) -> str:
    from production_read_only_retrieval_v1 import (
        assert_read_only_sql,
    )

    assert_read_only_sql(
        sql
    )

    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            PRODUCTION_DB_CONTAINER,
            "psql",
            "-U",
            "ai_knowledge",
            "-d",
            "ai_knowledge",
            "-qAt",
            "-F",
            "\t",
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
            or "Production read-only query failed"
        )

    return result.stdout
