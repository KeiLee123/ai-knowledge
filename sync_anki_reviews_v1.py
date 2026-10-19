#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


SNAPSHOT_SCHEMA = "anki-review-snapshot-v1"
SYNC_VERSION = "sr-g-1"
DEFAULT_ENDPOINT = "http://127.0.0.1:8765"

NOTE_FIELDS = [
    "CardKey",
    "ChunkIDs",
    "SourceTitle",
    "SourcePage",
    "SourceURL",
    "SourceFileID",
    "SourceFilename",
    "Tags",
]


def utc_now_iso() -> str:
    return (
        dt.datetime.now(
            dt.timezone.utc
        )
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def invoke(
    action: str,
    params: dict | None,
    endpoint: str,
    api_key: str | None,
) -> object:
    payload = {
        "action": action,
        "version": 6,
    }

    if params is not None:
        payload["params"] = params

    if api_key:
        payload["key"] = api_key

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            decoded = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Unable to reach AnkiConnect at "
            f"{endpoint}. Keep Anki open and "
            "confirm AnkiConnect is installed."
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "AnkiConnect returned invalid JSON"
        ) from exc

    if not isinstance(decoded, dict):
        raise RuntimeError(
            "Unexpected AnkiConnect response"
        )

    if decoded.get("error"):
        raise RuntimeError(
            f"AnkiConnect {action} failed: "
            f"{decoded['error']}"
        )

    return decoded.get("result")


def escape_query_value(
    value: str,
) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def build_query(
    deck_name: str,
    required_tag: str | None,
) -> str:
    query = (
        'deck:"'
        + escape_query_value(
            deck_name
        )
        + '"'
    )

    if required_tag:
        query += (
            ' tag:"'
            + escape_query_value(
                required_tag
            )
            + '"'
        )

    return query


def field_value(
    card_info: dict,
    name: str,
) -> str:
    fields = (
        card_info.get("fields")
        or {}
    )

    item = fields.get(name)

    if not isinstance(item, dict):
        return ""

    return str(
        item.get("value")
        or ""
    ).strip()


def parse_chunk_ids(
    raw: str,
) -> list[int]:
    values = []

    seen = set()

    for token in re.split(
        r"[,;\s]+",
        raw.strip(),
    ):
        if not token:
            continue

        try:
            value = int(token)

        except ValueError:
            continue

        if value <= 0:
            continue

        if value in seen:
            continue

        seen.add(value)
        values.append(value)

    return values


def local_endpoint(
    endpoint: str,
) -> bool:
    parsed = urlparse(
        endpoint
    )

    return (
        parsed.scheme in {
            "http",
            "https",
        }
        and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
    )


def get_cards_info(
    card_ids: list[int],
    endpoint: str,
    api_key: str | None,
) -> list[dict]:
    if not card_ids:
        return []

    # Newer AnkiConnect builds can return only
    # the note fields and scheduling metrics we
    # need. Fall back to the classic cardsInfo
    # contract if those optional parameters are
    # unsupported.
    modern_params = {
        "cards": card_ids,
        "noteFields":
            NOTE_FIELDS,
        "fields": [
            "prop:r",
            "prop:s",
            "prop:d",
        ],
        "retrieved_info_mode":
            "COMPACT",
    }

    try:
        result = invoke(
            "cardsInfo",
            modern_params,
            endpoint,
            api_key,
        )

    except RuntimeError:
        result = invoke(
            "cardsInfo",
            {
                "cards": card_ids,
            },
            endpoint,
            api_key,
        )

    if not isinstance(
        result,
        list,
    ):
        raise RuntimeError(
            "cardsInfo did not return a list"
        )

    return [
        item
        for item in result
        if isinstance(
            item,
            dict,
        )
    ]


def get_reviews(
    card_ids: list[int],
    deck_name: str,
    endpoint: str,
    api_key: str | None,
) -> dict[str, list[dict]]:
    if not card_ids:
        return {}

    try:
        result = invoke(
            "getReviewsOfCards",
            {
                "cards": [
                    str(card_id)
                    for card_id
                    in card_ids
                ]
            },
            endpoint,
            api_key,
        )

        if not isinstance(
            result,
            dict,
        ):
            raise RuntimeError(
                "getReviewsOfCards did "
                "not return an object"
            )

        normalized = {}

        for card_id in card_ids:
            rows = result.get(
                str(card_id),
                [],
            )

            if not isinstance(
                rows,
                list,
            ):
                rows = []

            normalized[
                str(card_id)
            ] = [
                item
                for item in rows
                if isinstance(
                    item,
                    dict,
                )
            ]

        return normalized

    except RuntimeError:
        # Compatibility fallback for older
        # AnkiConnect builds. cardReviews
        # returns all deck reviews after a
        # timestamp; startID=0 means all.
        rows = invoke(
            "cardReviews",
            {
                "deck":
                    deck_name,
                "startID":
                    0,
            },
            endpoint,
            api_key,
        )

        if not isinstance(
            rows,
            list,
        ):
            raise RuntimeError(
                "cardReviews did not "
                "return a list"
            )

        wanted = set(
            card_ids
        )

        grouped = {
            str(card_id): []
            for card_id in card_ids
        }

        for row in rows:
            if (
                not isinstance(
                    row,
                    list,
                )
                or len(row) < 9
            ):
                continue

            card_id = int(
                row[1]
            )

            if card_id not in wanted:
                continue

            grouped[
                str(card_id)
            ].append({
                "id": row[0],
                "usn": row[2],
                "ease": row[3],
                "ivl": row[4],
                "lastIvl": row[5],
                "factor": row[6],
                "time": row[7],
                "type": row[8],
            })

        return grouped


def filter_reviews(
    reviews: list[dict],
    since_ms: int | None,
) -> list[dict]:
    output = []

    for review in reviews:
        try:
            review_id = int(
                review.get(
                    "id",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            since_ms is not None
            and review_id <= since_ms
        ):
            continue

        output.append({
            "review_id":
                review_id,
            "rating":
                int(
                    review.get(
                        "ease",
                        0,
                    )
                    or 0
                ),
            "new_interval":
                int(
                    review.get(
                        "ivl",
                        0,
                    )
                    or 0
                ),
            "previous_interval":
                int(
                    review.get(
                        "lastIvl",
                        0,
                    )
                    or 0
                ),
            "factor":
                int(
                    review.get(
                        "factor",
                        0,
                    )
                    or 0
                ),
            "duration_ms":
                int(
                    review.get(
                        "time",
                        0,
                    )
                    or 0
                ),
            "review_type":
                int(
                    review.get(
                        "type",
                        0,
                    )
                    or 0
                ),
        })

    output.sort(
        key=lambda item:
            item[
                "review_id"
            ]
    )

    return output


def review_summary(
    reviews: list[dict],
) -> dict:
    counts = {
        "again": 0,
        "hard": 0,
        "good": 0,
        "easy": 0,
        "other": 0,
    }

    for review in reviews:
        rating = review.get(
            "rating"
        )

        key = {
            1: "again",
            2: "hard",
            3: "good",
            4: "easy",
        }.get(
            rating,
            "other",
        )

        counts[key] += 1

    return {
        "review_count":
            len(reviews),
        "ratings":
            counts,
        "latest_review_id":
            (
                reviews[-1][
                    "review_id"
                ]
                if reviews
                else None
            ),
    }


def nullable_number(
    value,
) -> float | int | None:
    if value is None:
        return None

    if isinstance(
        value,
        (int, float),
    ):
        return value

    try:
        parsed = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if parsed.is_integer():
        return int(parsed)

    return parsed


def build_snapshot(
    deck_name: str,
    required_tag: str | None,
    endpoint: str,
    api_key: str | None,
    since_ms: int | None,
) -> dict:
    query = build_query(
        deck_name,
        required_tag,
    )

    result = invoke(
        "findCards",
        {
            "query": query,
        },
        endpoint,
        api_key,
    )

    if not isinstance(
        result,
        list,
    ):
        raise RuntimeError(
            "findCards did not return a list"
        )

    card_ids = []

    for value in result:
        try:
            card_id = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if card_id > 0:
            card_ids.append(
                card_id
            )

    card_ids = sorted(
        set(card_ids)
    )

    infos = get_cards_info(
        card_ids,
        endpoint,
        api_key,
    )

    reviews_by_card = get_reviews(
        card_ids,
        deck_name,
        endpoint,
        api_key,
    )

    cards = []
    unmapped = []

    for info in infos:
        try:
            card_id = int(
                info.get(
                    "cardId"
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        card_key = field_value(
            info,
            "CardKey",
        )

        if not card_key:
            unmapped.append(
                card_id
            )
            continue

        chunk_ids = parse_chunk_ids(
            field_value(
                info,
                "ChunkIDs",
            )
        )

        reviews = filter_reviews(
            reviews_by_card.get(
                str(card_id),
                [],
            ),
            since_ms,
        )

        raw_tags = info.get(
            "tags"
        )

        if isinstance(
            raw_tags,
            list,
        ):
            tags = [
                str(value)
                for value in raw_tags
                if str(value)
            ]

        else:
            tags_field = (
                field_value(
                    info,
                    "Tags",
                )
            )

            tags = [
                token
                for token in re.split(
                    r"\s+",
                    tags_field,
                )
                if token
            ]

        cards.append({
            "card_key":
                card_key,
            "anki_card_id":
                card_id,
            "anki_note_id":
                int(
                    info.get(
                        "note",
                        0,
                    )
                    or 0
                ),
            "deck_name":
                str(
                    info.get(
                        "deckName",
                        deck_name,
                    )
                    or deck_name
                ),
            "model_name":
                str(
                    info.get(
                        "modelName",
                        ""
                    )
                    or ""
                ),
            "tags":
                sorted(
                    set(tags)
                ),
            "knowledge_mapping": {
                "chunk_ids":
                    chunk_ids,
                "source_title":
                    field_value(
                        info,
                        "SourceTitle",
                    ),
                "source_page":
                    field_value(
                        info,
                        "SourcePage",
                    ),
                "source_url":
                    field_value(
                        info,
                        "SourceURL",
                    ),
                "source_file_id":
                    field_value(
                        info,
                        "SourceFileID",
                    ),
                "source_filename":
                    field_value(
                        info,
                        "SourceFilename",
                    ),
            },
            "scheduling": {
                "card_type":
                    info.get("type"),
                "queue":
                    info.get("queue"),
                "due":
                    info.get("due"),
                "interval":
                    info.get(
                        "interval"
                    ),
                "reps":
                    info.get("reps"),
                "lapses":
                    info.get(
                        "lapses"
                    ),
                "factor":
                    info.get(
                        "factor"
                    ),
                "retrievability":
                    nullable_number(
                        info.get(
                            "prop:r"
                        )
                    ),
                "stability":
                    nullable_number(
                        info.get(
                            "prop:s"
                        )
                    ),
                "difficulty":
                    nullable_number(
                        info.get(
                            "prop:d"
                        )
                    ),
            },
            "review_summary":
                review_summary(
                    reviews
                ),
            "reviews":
                reviews,
        })

    total_reviews = sum(
        card[
            "review_summary"
        ][
            "review_count"
        ]
        for card in cards
    )

    return {
        "schema_version":
            SNAPSHOT_SCHEMA,
        "sync_version":
            SYNC_VERSION,
        "created_at_utc":
            utc_now_iso(),
        "read_only":
            True,
        "anki_write_performed":
            False,
        "database_write_performed":
            False,
        "privacy": {
            "question_answer_content_included":
                False,
            "anki_api_key_included":
                False,
        },
        "source": {
            "type":
                "ankiconnect-local",
            "endpoint":
                endpoint,
            "local_endpoint":
                local_endpoint(
                    endpoint
                ),
        },
        "scope": {
            "deck_name":
                deck_name,
            "required_tag":
                required_tag,
            "query":
                query,
            "since_review_id_ms":
                since_ms,
        },
        "summary": {
            "found_card_count":
                len(card_ids),
            "mapped_card_count":
                len(cards),
            "unmapped_card_count":
                len(unmapped),
            "review_count":
                total_reviews,
        },
        "unmapped_card_ids":
            unmapped,
        "cards":
            cards,
    }


def atomic_write_json(
    path: Path,
    payload: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        path
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a privacy-minimized, "
            "read-only Anki review snapshot "
            "from a local AnkiConnect instance."
        )
    )

    parser.add_argument(
        "--deck",
        required=True,
        help=(
            "Exact Anki deck name to read"
        ),
    )

    parser.add_argument(
        "--tag",
        default="jason-os",
        help=(
            "Required Anki tag. "
            "Default: jason-os. "
            "Use --tag '' to disable."
        ),
    )

    parser.add_argument(
        "--endpoint",
        default=
            DEFAULT_ENDPOINT,
    )

    parser.add_argument(
        "--api-key-env",
        default=
            "ANKICONNECT_KEY",
        help=(
            "Environment variable containing "
            "optional AnkiConnect API key"
        ),
    )

    parser.add_argument(
        "--since-review-id-ms",
        type=int,
        help=(
            "Only include reviews with "
            "review ID/timestamp greater "
            "than this Unix millisecond value"
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    args = parser.parse_args()

    required_tag = (
        args.tag.strip()
        if args.tag is not None
        else ""
    )

    if not required_tag:
        required_tag = None

    if (
        args.since_review_id_ms
        is not None
        and args.since_review_id_ms
            < 0
    ):
        raise SystemExit(
            "--since-review-id-ms "
            "must be non-negative"
        )

    api_key = (
        os.environ.get(
            args.api_key_env,
            ""
        ).strip()
        or None
    )

    output_path = (
        Path(args.output)
        .expanduser()
        .resolve()
    )

    try:
        snapshot = build_snapshot(
            deck_name=
                args.deck,
            required_tag=
                required_tag,
            endpoint=
                args.endpoint,
            api_key=
                api_key,
            since_ms=
                args.since_review_id_ms,
        )

        atomic_write_json(
            output_path,
            snapshot,
        )

    except Exception as exc:
        raise SystemExit(
            "Anki review sync failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    print(
        output_path
    )

    print(
        "Schema:",
        snapshot[
            "schema_version"
        ],
    )

    print(
        "Deck:",
        snapshot[
            "scope"
        ][
            "deck_name"
        ],
    )

    print(
        "Found cards:",
        snapshot[
            "summary"
        ][
            "found_card_count"
        ],
    )

    print(
        "Mapped cards:",
        snapshot[
            "summary"
        ][
            "mapped_card_count"
        ],
    )

    print(
        "Unmapped cards:",
        snapshot[
            "summary"
        ][
            "unmapped_card_count"
        ],
    )

    print(
        "Reviews:",
        snapshot[
            "summary"
        ][
            "review_count"
        ],
    )

    print(
        "Question/answer content included:",
        False,
    )

    print(
        "Anki write performed:",
        False,
    )

    print(
        "Database write performed:",
        False,
    )


if __name__ == "__main__":
    main()
