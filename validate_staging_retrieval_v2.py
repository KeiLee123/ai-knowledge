#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)


VALIDATOR_VERSION = "canary-retrieval-v1"
DEFAULT_EMBED_URL = "http://127.0.0.1:8088/embed"
EXPECTED_DIMENSIONS = 384
EMBED_MODEL = "multilingual-e5-small"


def embed_query(
    query: str,
    embed_url: str,
) -> list[float]:
    payload = json.dumps(
        {
            "inputs":
                "query: " + query
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
            "Unexpected query embedding dimension: "
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


def validate_checksum(
    value: str,
) -> str:
    value = (
        value
        .strip()
        .lower()
    )

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        value,
    ):
        raise RuntimeError(
            "Document checksum must be 64 lowercase/uppercase hex characters"
        )

    return value


def build_retrieval_sql(
    checksum: str,
    vector: list[float],
    limit: int,
) -> str:
    checksum = validate_checksum(
        checksum
    )

    if (
        limit < 1
        or limit > 50
    ):
        raise RuntimeError(
            "Limit must be between 1 and 50"
        )

    if len(vector) != EXPECTED_DIMENSIONS:
        raise RuntimeError(
            "Query vector dimension mismatch"
        )

    vec = vector_literal(
        vector
    )

    return f"""
SELECT
    c.id::text,
    COALESCE(c.page_start::text, ''),
    COALESCE(c.page_end::text, ''),
    COALESCE(c.metadata->>'evidence_origin', ''),
    COALESCE(c.metadata->>'evidence_tier', ''),
    COALESCE(c.metadata->>'retrieval_role', ''),
    (e.embedding <=> '{vec}'::vector)::text,
    encode(convert_to(c.content, 'UTF8'), 'hex')
FROM embeddings e
JOIN chunks c
  ON c.id = e.chunk_id
JOIN documents d
  ON d.id = c.document_id
WHERE d.checksum_sha256 = '{checksum}'
  AND e.provider = 'local'
  AND e.model = '{EMBED_MODEL}'
ORDER BY e.embedding <=> '{vec}'::vector
LIMIT {limit};
""".strip()


def assert_read_only_sql(
    sql: str,
) -> None:
    forbidden = [
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "ALTER ",
        "DROP ",
        "CREATE ",
        "TRUNCATE ",
    ]

    upper = (
        " "
        + " ".join(
            sql.upper().split()
        )
        + " "
    )

    for token in forbidden:
        if (
            " " + token
            in upper
        ):
            raise RuntimeError(
                "Refusing non-read-only SQL: "
                f"{token.strip()}"
            )


def run_staging_query(
    sql: str,
) -> str:
    if (
        STAGING_DB_CONTAINER
        == PRODUCTION_DB_CONTAINER
    ):
        raise RuntimeError(
            "Staging DB equals Production DB"
        )

    assert_read_only_sql(
        sql
    )

    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            STAGING_DB_CONTAINER,
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
            or "Staging retrieval query failed"
        )

    return result.stdout


def parse_rows(
    text: str,
) -> list[dict]:
    rows = []

    for line in text.splitlines():
        if not line.strip():
            continue

        parts = line.split(
            "\t",
            7,
        )

        if len(parts) != 8:
            raise RuntimeError(
                "Unexpected retrieval row shape"
            )

        (
            chunk_id,
            page_start,
            page_end,
            origin,
            tier,
            role,
            distance,
            content_b64,
        ) = parts

        content = bytes.fromhex(
            content_b64
        ).decode(
            "utf-8",
            errors="replace",
        )

        rows.append({
            "chunk_id":
                int(chunk_id),
            "page_start":
                int(page_start)
                if page_start
                else None,
            "page_end":
                int(page_end)
                if page_end
                else None,
            "evidence_origin":
                origin,
            "evidence_tier":
                tier,
            "retrieval_role":
                role,
            "cosine_distance":
                float(distance),
            "content":
                content,
        })

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only semantic retrieval validator for "
            "the isolated Jason OS staging canary DB."
        )
    )

    parser.add_argument(
        "--query",
        required=True,
    )

    parser.add_argument(
        "--checksum",
        required=True,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--embed-url",
        default=
            DEFAULT_EMBED_URL,
    )

    parser.add_argument(
        "--full-content",
        action="store_true",
        help=(
            "Print full chunk content instead of "
            "a compact preview"
        ),
    )

    args = parser.parse_args()

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    guard = verify_runtime(
        repo_root
    )

    checksum = validate_checksum(
        args.checksum
    )

    vector = embed_query(
        args.query,
        args.embed_url,
    )

    sql = build_retrieval_sql(
        checksum=checksum,
        vector=vector,
        limit=args.limit,
    )

    rows = parse_rows(
        run_staging_query(
            sql
        )
    )

    print(
        json.dumps(
            {
                "validator_version":
                    VALIDATOR_VERSION,
                "guard_ok":
                    guard["guard_ok"],
                "branch":
                    guard["branch"],
                "db_container":
                    STAGING_DB_CONTAINER,
                "read_only":
                    True,
                "query":
                    args.query,
                "document_checksum":
                    checksum,
                "embedding_model":
                    EMBED_MODEL,
                "embedding_dimensions":
                    EXPECTED_DIMENSIONS,
                "result_count":
                    len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        "RETRIEVAL_RESULTS"
    )

    for rank, row in enumerate(
        rows,
        start=1,
    ):
        content = row["content"]

        if not args.full_content:
            content = (
                " ".join(
                    content.split()
                )
            )

            if len(content) > 500:
                content = (
                    content[:500]
                    + "..."
                )

        print()
        print(
            f"#{rank} "
            f"chunk={row['chunk_id']} "
            f"page={row['page_start']} "
            f"origin={row['evidence_origin']} "
            f"tier={row['evidence_tier']} "
            f"role={row['retrieval_role']} "
            f"distance={row['cosine_distance']:.6f}"
        )
        print(
            content
        )

    if not rows:
        raise SystemExit(
            "No retrieval results found for "
            "the requested staging document"
        )


if __name__ == "__main__":
    main()
