#!/usr/bin/env python3

import json
import re
import urllib.request


DEFAULT_EMBED_URL = "http://127.0.0.1:8088/embed"
EXPECTED_DIMENSIONS = 384
EMBED_MODEL = "multilingual-e5-small"


def embed_query(query, embed_url):
    payload = json.dumps(
        {
            "inputs": "query: " + query,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        embed_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=60,
    ) as response:
        vector = json.loads(
            response.read().decode("utf-8")
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


def vector_literal(vector):
    return (
        "["
        + ",".join(
            str(value)
            for value in vector
        )
        + "]"
    )


def validate_checksum(value):
    value = value.strip().lower()

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        value,
    ):
        raise RuntimeError(
            "Document checksum must be 64 hex characters"
        )

    return value


def build_retrieval_sql(
    checksum,
    vector,
    limit,
):
    checksum = validate_checksum(checksum)

    if limit < 1 or limit > 50:
        raise RuntimeError(
            "Limit must be between 1 and 50"
        )

    if len(vector) != EXPECTED_DIMENSIONS:
        raise RuntimeError(
            "Query vector dimension mismatch"
        )

    vec = vector_literal(vector)

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


def assert_read_only_sql(sql):
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
        if " " + token in upper:
            raise RuntimeError(
                "Refusing non-read-only SQL: "
                f"{token.strip()}"
            )


def parse_rows(text):
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
            content_hex,
        ) = parts

        content = bytes.fromhex(
            content_hex
        ).decode(
            "utf-8",
            errors="replace",
        )

        rows.append(
            {
                "chunk_id": int(chunk_id),
                "page_start": (
                    int(page_start)
                    if page_start
                    else None
                ),
                "page_end": (
                    int(page_end)
                    if page_end
                    else None
                ),
                "evidence_origin": origin,
                "evidence_tier": tier,
                "retrieval_role": role,
                "cosine_distance": float(distance),
                "content": content,
            }
        )

    return rows
