#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

from classify_knowledge import get_model_config
from source_locator_v1 import (
    DEFAULT_DB_CONTAINER,
    resolve_chunk_locators,
)


GENERATOR_VERSION = "sr-c-1"
SCHEMA_VERSION = "anki-card-manifest-v1"


def run_db_query(
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
            or "Database read-only query failed"
        )

    return result.stdout.strip()


def load_chunk(
    chunk_id: int,
    db_container: str,
) -> dict:
    sql = f"""
    SELECT
        json_build_object(
            'chunk_id', c.id,
            'document_id', d.id,
            'document_title',
                COALESCE(d.title, ''),
            'document_checksum',
                COALESCE(
                    d.checksum_sha256,
                    ''
                ),
            'domain',
                COALESCE(d.domain, ''),
            'topic',
                COALESCE(d.topic, ''),
            'page_start', c.page_start,
            'page_end', c.page_end,
            'content',
                COALESCE(c.content, ''),
            'chunk_metadata',
                COALESCE(
                    c.metadata,
                    '{{}}'::jsonb
                )
        )::text
    FROM chunks c
    JOIN documents d
      ON d.id = c.document_id
    WHERE c.id = {int(chunk_id)}
    LIMIT 1;
    """

    raw = run_db_query(
        sql,
        db_container,
    )

    if not raw:
        raise RuntimeError(
            f"Chunk not found: {chunk_id}"
        )

    return json.loads(
        raw.splitlines()[0]
    )


def call_model(
    chunk: dict,
    card_count: int,
) -> list[dict]:
    api_key, model, base_url = (
        get_model_config()
    )

    system_prompt = """
You create high-quality spaced-repetition cards
from ONE supplied source excerpt.

Use ONLY the supplied source evidence.
Do not add facts from general knowledge.
Do not correct or expand the source.
If the excerpt does not support a useful card,
return an empty cards array.

Rules:
- one recall target per card
- concise question
- concise answer
- avoid yes/no questions
- preserve important units, numbers and qualifiers
- no unsupported explanation
- explanation may be empty
- related_knowledge must only contain concepts
  explicitly present in the excerpt
- card_type must be text_recall or context_card
- visual_recall is reserved for a later media phase

Return JSON exactly in this form:

{
  "cards": [
    {
      "card_type": "text_recall",
      "question": "",
      "answer": "",
      "explanation": "",
      "related_knowledge": []
    }
  ]
}
""".strip()

    user_prompt = f"""
Create up to {card_count} cards.

Document:
{chunk.get("document_title", "")}

Topic:
{chunk.get("topic", "")}

Page:
{chunk.get("page_start")}

SOURCE EXCERPT
--------------
{chunk.get("content", "")}
--------------
""".strip()

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "response_format": {
            "type": "json_object"
        },
        "temperature": 0,
    }

    request = urllib.request.Request(
        base_url.rstrip("/")
        + "/chat/completions",
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Authorization":
                f"Bearer {api_key}",
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        result = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    content = (
        result["choices"][0]
        ["message"]["content"]
    )

    decoded = json.loads(
        content
    )

    cards = decoded.get(
        "cards",
        [],
    )

    if not isinstance(cards, list):
        raise RuntimeError(
            "Model response cards must "
            "be a list"
        )

    return cards[:card_count]


def normalize_text(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )


def validate_card(
    card: dict,
) -> dict:
    if not isinstance(card, dict):
        raise RuntimeError(
            "Generated card is not an object"
        )

    card_type = normalize_text(
        card.get(
            "card_type"
        )
    )

    if card_type not in {
        "text_recall",
        "context_card",
    }:
        raise RuntimeError(
            "Unsupported generated card_type: "
            f"{card_type!r}"
        )

    question = normalize_text(
        card.get("question")
    )

    answer = normalize_text(
        card.get("answer")
    )

    explanation = normalize_text(
        card.get(
            "explanation"
        )
    )

    related = card.get(
        "related_knowledge",
        [],
    )

    if not isinstance(
        related,
        list,
    ):
        raise RuntimeError(
            "related_knowledge must "
            "be a list"
        )

    related = [
        normalize_text(value)
        for value in related
        if normalize_text(value)
    ]

    if not question:
        raise RuntimeError(
            "Generated question is empty"
        )

    if not answer:
        raise RuntimeError(
            "Generated answer is empty"
        )

    if len(question) > 500:
        raise RuntimeError(
            "Generated question is too long"
        )

    if len(answer) > 1000:
        raise RuntimeError(
            "Generated answer is too long"
        )

    return {
        "card_type": card_type,
        "question": question,
        "answer": answer,
        "explanation": explanation,
        "related_knowledge": related,
    }


def stable_card_key(
    chunk: dict,
    card: dict,
) -> str:
    evidence_hash = hashlib.sha256(
        normalize_text(
            chunk.get("content", "")
        ).encode("utf-8")
    ).hexdigest()

    source = "\n".join([
        SCHEMA_VERSION,
        str(
            chunk.get(
                "document_checksum",
                "",
            )
        ),
        str(
            chunk.get(
                "page_start",
                "",
            )
        ),
        str(
            chunk.get(
                "page_end",
                "",
            )
        ),
        evidence_hash,
        card["card_type"],
        normalize_text(
            card["question"]
        ).lower(),
    ])

    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def make_card(
    chunk: dict,
    locator: dict,
    generated: dict,
) -> dict:
    card = validate_card(
        generated
    )

    card_key = stable_card_key(
        chunk,
        card,
    )

    source = {
        "document_id":
            locator.get(
                "document_id"
            ),
        "document_title":
            locator.get(
                "document_title",
                "",
            ),
        "document_checksum":
            locator.get(
                "document_checksum",
                "",
            ),
        "chunk_ids": [
            int(
                locator["chunk_id"]
            )
        ],
        "page_start":
            locator.get(
                "page_start"
            ),
        "page_end":
            locator.get(
                "page_end"
            ),
        "source_type":
            locator.get(
                "source_type",
                "",
            ),
        "source_file_id":
            locator.get(
                "source_file_id",
                "",
            ),
        "source_url":
            locator.get(
                "source_url",
                "",
            ),
        "source_filename":
            locator.get(
                "source_filename",
                "",
            ),
        "source_path":
            locator.get(
                "source_path",
                "",
            ),
        "locator_label":
            locator.get(
                "locator_label",
                "",
            ),
    }

    tags = [
        "jason-os",
        chunk.get(
            "domain",
            "",
        ),
        chunk.get(
            "topic",
            "",
        ),
        card["card_type"],
    ]

    tags = [
        value
        for value in tags
        if value
    ]

    return {
        **card,
        "source": source,
        "media": [],
        "tags": tags,
        "card_key": card_key,
    }


def build_manifest(
    chunk_ids: list[int],
    deck_name: str,
    cards_per_chunk: int,
    db_container: str,
) -> dict:
    locator_payload = (
        resolve_chunk_locators(
            chunk_ids,
            db_container,
        )
    )

    if locator_payload[
        "missing_chunk_ids"
    ]:
        raise RuntimeError(
            "Missing source locators for "
            "chunk IDs: "
            + ", ".join(
                str(value)
                for value in
                locator_payload[
                    "missing_chunk_ids"
                ]
            )
        )

    locator_by_chunk = {
        int(
            item["chunk_id"]
        ): item
        for item in
        locator_payload["locators"]
    }

    output_cards = []

    for chunk_id in chunk_ids:
        chunk = load_chunk(
            chunk_id,
            db_container,
        )

        locator = (
            locator_by_chunk[
                int(chunk_id)
            ]
        )

        generated_cards = (
            call_model(
                chunk,
                cards_per_chunk,
            )
        )

        for generated in generated_cards:
            output_cards.append(
                make_card(
                    chunk,
                    locator,
                    generated,
                )
            )

    seen_keys = set()
    deduped = []

    for card in output_cards:
        key = card["card_key"]

        if key in seen_keys:
            continue

        seen_keys.add(key)
        deduped.append(card)

    return {
        "schema_version":
            SCHEMA_VERSION,
        "generator_version":
            GENERATOR_VERSION,
        "read_only":
            True,
        "database_write_performed":
            False,
        "deck": {
            "name": deck_name,
        },
        "generation": {
            "requested_chunk_ids":
                chunk_ids,
            "cards_per_chunk":
                cards_per_chunk,
            "generated_card_count":
                len(deduped),
            "model_call_performed":
                True,
            "media_rendered":
                False,
            "anki_package_created":
                False,
        },
        "cards":
            deduped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a source-grounded "
            "Anki card manifest from selected "
            "Knowledge Brain chunks. "
            "Read-only; no DB or Anki writes."
        )
    )

    parser.add_argument(
        "--chunk-id",
        action="append",
        required=True,
        type=int,
        help=(
            "Knowledge Brain chunk ID. "
            "Repeat for multiple chunks."
        ),
    )

    parser.add_argument(
        "--deck-name",
        default="Jason OS",
    )

    parser.add_argument(
        "--cards-per-chunk",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output card manifest JSON"
        ),
    )

    args = parser.parse_args()

    if (
        args.cards_per_chunk < 1
        or args.cards_per_chunk > 5
    ):
        raise SystemExit(
            "--cards-per-chunk must "
            "be between 1 and 5"
        )

    chunk_ids = []

    seen = set()

    for chunk_id in args.chunk_id:
        if chunk_id <= 0:
            raise SystemExit(
                "chunk IDs must be positive"
            )

        if chunk_id in seen:
            continue

        seen.add(chunk_id)
        chunk_ids.append(chunk_id)

    try:
        manifest = build_manifest(
            chunk_ids=chunk_ids,
            deck_name=args.deck_name,
            cards_per_chunk=
                args.cards_per_chunk,
            db_container=
                args.db_container,
        )

    except Exception as exc:
        raise SystemExit(
            "Card manifest generation "
            "failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    output_path = (
        Path(args.output)
        .expanduser()
        .resolve()
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(output_path)

    print(
        "Generated cards:",
        manifest[
            "generation"
        ][
            "generated_card_count"
        ],
    )

    print(
        "Database write performed:",
        False,
    )

    print(
        "Anki package created:",
        False,
    )


if __name__ == "__main__":
    main()
