#!/usr/bin/env python3

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path

from source_locator_v1 import (
    DEFAULT_DB_CONTAINER,
    resolve_chunk_locators,
)


ANALYTICS_VERSION = "sr-h-1"
REPORT_SCHEMA = "knowledge-analytics-report-v1"
SUPPORTED_SNAPSHOT_SCHEMA = "anki-review-snapshot-v1"


def utc_now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_snapshot(path: Path) -> dict:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if (
        payload.get("schema_version")
        != SUPPORTED_SNAPSHOT_SCHEMA
    ):
        raise RuntimeError(
            "Unsupported snapshot schema: "
            f"{payload.get('schema_version')!r}"
        )

    cards = payload.get("cards")

    if not isinstance(cards, list):
        raise RuntimeError(
            "snapshot.cards must be a list"
        )

    return payload


def atomic_write_json(
    path: Path,
    payload: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
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

    temporary.replace(path)


def atomic_write_text(
    path: Path,
    text: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        text,
        encoding="utf-8",
    )

    temporary.replace(path)


def safe_int(
    value,
    default: int = 0,
) -> int:
    try:
        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_float(
    value,
) -> float | None:
    if value is None:
        return None

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return None


def ratio(
    numerator: int,
    denominator: int,
) -> float | None:
    if denominator <= 0:
        return None

    return round(
        numerator / denominator,
        4,
    )


def interval_normalized(
    raw_value,
) -> dict:
    value = safe_int(
        raw_value,
        0,
    )

    if value < 0:
        return {
            "raw": value,
            "unit": "seconds",
            "value": abs(value),
        }

    return {
        "raw": value,
        "unit": "days",
        "value": value,
    }


def review_timestamp_iso(
    review_id,
) -> str | None:
    value = safe_int(
        review_id,
        0,
    )

    if value <= 0:
        return None

    try:
        return (
            dt.datetime.fromtimestamp(
                value / 1000,
                tz=dt.timezone.utc,
            )
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    except (
        OverflowError,
        OSError,
        ValueError,
    ):
        return None


def unique_positive_ints(
    values,
) -> list[int]:
    output = []
    seen = set()

    if not isinstance(values, list):
        return output

    for value in values:
        parsed = safe_int(
            value,
            0,
        )

        if (
            parsed <= 0
            or parsed in seen
        ):
            continue

        seen.add(parsed)
        output.append(parsed)

    return output


def collect_chunk_ids(
    cards: list[dict],
) -> list[int]:
    output = []
    seen = set()

    for card in cards:
        if not isinstance(card, dict):
            continue

        mapping = (
            card.get("knowledge_mapping")
            or {}
        )

        for chunk_id in (
            unique_positive_ints(
                mapping.get(
                    "chunk_ids"
                )
            )
        ):
            if chunk_id in seen:
                continue

            seen.add(chunk_id)
            output.append(chunk_id)

    return output


def resolve_knowledge(
    cards: list[dict],
    db_container: str | None,
) -> tuple[
    dict[int, dict],
    dict,
]:
    chunk_ids = collect_chunk_ids(
        cards
    )

    if db_container is None:
        return {}, {
            "requested": False,
            "resolved_count": 0,
            "missing_chunk_ids":
                chunk_ids,
        }

    if not chunk_ids:
        return {}, {
            "requested": True,
            "resolved_count": 0,
            "missing_chunk_ids": [],
        }

    payload = resolve_chunk_locators(
        chunk_ids,
        db_container,
    )

    locators = {
        safe_int(
            item.get("chunk_id"),
            0,
        ): item
        for item in (
            payload.get("locators")
            or []
        )
        if isinstance(item, dict)
        and safe_int(
            item.get("chunk_id"),
            0,
        ) > 0
    }

    return locators, {
        "requested": True,
        "resolved_count":
            len(locators),
        "missing_chunk_ids":
            payload.get(
                "missing_chunk_ids"
            )
            or [],
        "database_write_performed":
            False,
    }


def rating_counts(
    reviews,
) -> dict:
    counts = Counter()

    if not isinstance(reviews, list):
        reviews = []

    for review in reviews:
        if not isinstance(
            review,
            dict,
        ):
            continue

        rating = safe_int(
            review.get("rating"),
            0,
        )

        name = {
            1: "again",
            2: "hard",
            3: "good",
            4: "easy",
        }.get(
            rating,
            "other",
        )

        counts[name] += 1

    return {
        "again":
            counts["again"],
        "hard":
            counts["hard"],
        "good":
            counts["good"],
        "easy":
            counts["easy"],
        "other":
            counts["other"],
    }


def locator_for_card(
    chunk_ids: list[int],
    locator_by_chunk:
        dict[int, dict],
) -> dict:
    items = []

    for chunk_id in chunk_ids:
        item = locator_by_chunk.get(
            chunk_id
        )

        if not item:
            continue

        items.append({
            "chunk_id":
                chunk_id,
            "document_id":
                item.get(
                    "document_id"
                ),
            "document_title":
                item.get(
                    "document_title",
                    "",
                ),
            "domain":
                item.get(
                    "domain",
                    "",
                ),
            "topic":
                item.get(
                    "topic",
                    "",
                ),
            "page_start":
                item.get(
                    "page_start"
                ),
            "page_end":
                item.get(
                    "page_end"
                ),
            "locator_label":
                item.get(
                    "locator_label",
                    "",
                ),
            "source_filename":
                item.get(
                    "source_filename",
                    "",
                ),
            "source_url":
                item.get(
                    "source_url",
                    "",
                ),
        })

    return {
        "resolved":
            bool(items),
        "locators":
            items,
    }


def card_analysis(
    card: dict,
    locator_by_chunk:
        dict[int, dict],
) -> dict:
    card_key = str(
        card.get("card_key")
        or ""
    ).strip()

    mapping = (
        card.get(
            "knowledge_mapping"
        )
        or {}
    )

    scheduling = (
        card.get("scheduling")
        or {}
    )

    reviews = card.get(
        "reviews"
    )

    if not isinstance(reviews, list):
        reviews = []

    counts = rating_counts(
        reviews
    )

    valid_review_count = sum(
        counts[name]
        for name in (
            "again",
            "hard",
            "good",
            "easy",
        )
    )

    problem_count = (
        counts["again"]
        + counts["hard"]
    )

    reps = safe_int(
        scheduling.get("reps"),
        0,
    )

    lapses = safe_int(
        scheduling.get("lapses"),
        0,
    )

    retrievability = safe_float(
        scheduling.get(
            "retrievability"
        )
    )

    stability = safe_float(
        scheduling.get(
            "stability"
        )
    )

    difficulty = safe_float(
        scheduling.get(
            "difficulty"
        )
    )

    repeated_failure = (
        counts["again"] >= 2
        or lapses >= 2
    )

    weak_reasons = []

    if repeated_failure:
        weak_reasons.append(
            "repeated_failure"
        )

    if (
        valid_review_count >= 3
        and ratio(
            problem_count,
            valid_review_count,
        ) is not None
        and (
            problem_count
            / valid_review_count
        ) >= 0.5
    ):
        weak_reasons.append(
            "high_again_hard_share"
        )

    if (
        retrievability is not None
        and valid_review_count >= 2
        and retrievability < 0.75
    ):
        weak_reasons.append(
            "low_retrievability"
        )

    weak = bool(
        weak_reasons
    )

    watch = (
        not weak
        and valid_review_count > 0
        and problem_count > 0
    )

    chunk_ids = (
        unique_positive_ints(
            mapping.get("chunk_ids")
        )
    )

    source = locator_for_card(
        chunk_ids,
        locator_by_chunk,
    )

    if not source["resolved"]:
        source = {
            "resolved": False,
            "locators": [{
                "chunk_id":
                    chunk_ids[0]
                    if chunk_ids
                    else None,
                "document_id":
                    None,
                "document_title":
                    str(
                        mapping.get(
                            "source_title"
                        )
                        or ""
                    ),
                "domain": "",
                "topic": "",
                "page_start":
                    None,
                "page_end":
                    None,
                "locator_label":
                    " ".join(
                        value
                        for value in [
                            str(
                                mapping.get(
                                    "source_title"
                                )
                                or ""
                            ).strip(),
                            str(
                                mapping.get(
                                    "source_page"
                                )
                                or ""
                            ).strip(),
                        ]
                        if value
                    ),
                "source_filename":
                    str(
                        mapping.get(
                            "source_filename"
                        )
                        or ""
                    ),
                "source_url":
                    str(
                        mapping.get(
                            "source_url"
                        )
                        or ""
                    ),
            }],
        }

    latest_review = (
        reviews[-1]
        if reviews
        and isinstance(
            reviews[-1],
            dict,
        )
        else None
    )

    latest_interval = (
        interval_normalized(
            latest_review.get(
                "new_interval"
            )
        )
        if latest_review
        else None
    )

    topics = sorted({
        str(
            item.get("topic")
            or ""
        ).strip()
        for item in source["locators"]
        if str(
            item.get("topic")
            or ""
        ).strip()
    })

    domains = sorted({
        str(
            item.get("domain")
            or ""
        ).strip()
        for item in source["locators"]
        if str(
            item.get("domain")
            or ""
        ).strip()
    })

    return {
        "card_key":
            card_key,
        "anki_card_id":
            card.get(
                "anki_card_id"
            ),
        "review_count":
            len(reviews),
        "valid_rating_count":
            valid_review_count,
        "ratings":
            counts,
        "again_hard_share":
            ratio(
                problem_count,
                valid_review_count,
            ),
        "scheduling": {
            "reps": reps,
            "lapses": lapses,
            "retrievability":
                retrievability,
            "stability":
                stability,
            "difficulty":
                difficulty,
        },
        "latest_review": {
            "review_id":
                latest_review.get(
                    "review_id"
                )
                if latest_review
                else None,
            "timestamp_utc":
                review_timestamp_iso(
                    latest_review.get(
                        "review_id"
                    )
                )
                if latest_review
                else None,
            "rating":
                safe_int(
                    latest_review.get(
                        "rating"
                    ),
                    0,
                )
                if latest_review
                else None,
            "interval":
                latest_interval,
        },
        "weak":
            weak,
        "weak_reasons":
            weak_reasons,
        "watch":
            watch,
        "repeated_failure":
            repeated_failure,
        "chunk_ids":
            chunk_ids,
        "topics":
            topics,
        "domains":
            domains,
        "source":
            source,
    }


def aggregate_topics(
    cards: list[dict],
) -> list[dict]:
    groups = defaultdict(
        lambda: {
            "card_keys": set(),
            "reviewed_card_keys": set(),
            "reviews": 0,
            "ratings": Counter(),
            "weak_card_keys": set(),
            "repeated_failure_card_keys":
                set(),
            "source_locators": set(),
        }
    )

    for card in cards:
        topics = (
            card.get("topics")
            or ["(unclassified)"]
        )

        for topic in topics:
            group = groups[
                topic
            ]

            key = card.get(
                "card_key"
            )

            if key:
                group[
                    "card_keys"
                ].add(key)

            if (
                card.get(
                    "review_count",
                    0,
                ) > 0
                and key
            ):
                group[
                    "reviewed_card_keys"
                ].add(key)

            group["reviews"] += (
                card.get(
                    "review_count",
                    0,
                )
            )

            for (
                rating_name,
                count,
            ) in (
                card.get(
                    "ratings"
                )
                or {}
            ).items():
                group[
                    "ratings"
                ][
                    rating_name
                ] += safe_int(
                    count,
                    0,
                )

            if (
                card.get("weak")
                and key
            ):
                group[
                    "weak_card_keys"
                ].add(key)

            if (
                card.get(
                    "repeated_failure"
                )
                and key
            ):
                group[
                    "repeated_failure_card_keys"
                ].add(key)

            for locator in (
                card.get("source", {})
                .get(
                    "locators",
                    []
                )
            ):
                label = str(
                    locator.get(
                        "locator_label"
                    )
                    or ""
                ).strip()

                if label:
                    group[
                        "source_locators"
                    ].add(label)

    output = []

    for topic in sorted(
        groups
    ):
        group = groups[topic]

        valid = sum(
            group[
                "ratings"
            ][name]
            for name in (
                "again",
                "hard",
                "good",
                "easy",
            )
        )

        success = (
            group[
                "ratings"
            ]["good"]
            + group[
                "ratings"
            ]["easy"]
        )

        output.append({
            "topic":
                topic,
            "card_count":
                len(
                    group[
                        "card_keys"
                    ]
                ),
            "reviewed_card_count":
                len(
                    group[
                        "reviewed_card_keys"
                    ]
                ),
            "review_count":
                group[
                    "reviews"
                ],
            "ratings": {
                name:
                    group[
                        "ratings"
                    ][name]
                for name in (
                    "again",
                    "hard",
                    "good",
                    "easy",
                    "other",
                )
            },
            "observed_good_easy_ratio":
                ratio(
                    success,
                    valid,
                ),
            "weak_card_count":
                len(
                    group[
                        "weak_card_keys"
                    ]
                ),
            "repeated_failure_count":
                len(
                    group[
                        "repeated_failure_card_keys"
                    ]
                ),
            "source_locators":
                sorted(
                    group[
                        "source_locators"
                    ]
                ),
        })

    return output


def data_sufficiency(
    reviewed_card_count: int,
    review_count: int,
    multi_reviewed_card_count: int,
) -> dict:
    if review_count == 0:
        return {
            "level": "none",
            "recall_strength_interpretation":
                "No review history is available.",
        }

    if (
        review_count < 20
        or reviewed_card_count < 5
        or multi_reviewed_card_count < 3
    ):
        return {
            "level": "insufficient",
            "recall_strength_interpretation":
                (
                    "Review history is too small "
                    "for a reliable recall-strength "
                    "estimate. Reported rating "
                    "ratios are descriptive only."
                ),
        }

    if (
        review_count < 100
        or reviewed_card_count < 20
    ):
        return {
            "level": "provisional",
            "recall_strength_interpretation":
                (
                    "There is enough history for "
                    "a provisional trend, but not "
                    "for an absolute knowledge "
                    "measurement."
                ),
        }

    return {
        "level": "moderate",
        "recall_strength_interpretation":
            (
                "There is a broader review sample. "
                "Metrics remain estimates of "
                "observed recall behavior, not "
                "absolute human knowledge."
            ),
    }


def build_report(
    snapshot: dict,
    locator_by_chunk:
        dict[int, dict],
    enrichment: dict,
) -> dict:
    raw_cards = [
        card
        for card in (
            snapshot.get("cards")
            or []
        )
        if isinstance(card, dict)
    ]

    cards = [
        card_analysis(
            card,
            locator_by_chunk,
        )
        for card in raw_cards
    ]

    reviewed_cards = [
        card
        for card in cards
        if card[
            "review_count"
        ] > 0
    ]

    multi_reviewed_cards = [
        card
        for card in cards
        if card[
            "review_count"
        ] >= 2
    ]

    weak_cards = [
        card
        for card in cards
        if card["weak"]
    ]

    repeated_failures = [
        card
        for card in cards
        if card[
            "repeated_failure"
        ]
    ]

    watch_cards = [
        card
        for card in cards
        if card["watch"]
    ]

    total_ratings = Counter()

    for card in cards:
        for (
            name,
            count,
        ) in card[
            "ratings"
        ].items():
            total_ratings[
                name
            ] += count

    valid_rating_count = sum(
        total_ratings[name]
        for name in (
            "again",
            "hard",
            "good",
            "easy",
        )
    )

    good_easy_count = (
        total_ratings["good"]
        + total_ratings["easy"]
    )

    retrievabilities = [
        card[
            "scheduling"
        ][
            "retrievability"
        ]
        for card in cards
        if card[
            "scheduling"
        ][
            "retrievability"
        ]
        is not None
    ]

    source_documents = {
        str(
            locator.get(
                "document_title"
            )
            or ""
        ).strip()
        for card in reviewed_cards
        for locator in card[
            "source"
        ][
            "locators"
        ]
        if str(
            locator.get(
                "document_title"
            )
            or ""
        ).strip()
    }

    source_pages = {
        str(
            locator.get(
                "locator_label"
            )
            or ""
        ).strip()
        for card in reviewed_cards
        for locator in card[
            "source"
        ][
            "locators"
        ]
        if str(
            locator.get(
                "locator_label"
            )
            or ""
        ).strip()
    }

    total_card_count = len(
        cards
    )

    reviewed_card_count = len(
        reviewed_cards
    )

    review_count = sum(
        card[
            "review_count"
        ]
        for card in cards
    )

    sufficiency = data_sufficiency(
        reviewed_card_count,
        review_count,
        len(
            multi_reviewed_cards
        ),
    )

    partial_window = (
        snapshot.get(
            "scope",
            {}
        ).get(
            "since_review_id_ms"
        )
        is not None
    )

    warnings = []

    if partial_window:
        warnings.append(
            "Snapshot contains a partial "
            "review window; lifetime trends "
            "may be incomplete."
        )

    if (
        enrichment.get(
            "requested"
        )
        and enrichment.get(
            "missing_chunk_ids"
        )
    ):
        warnings.append(
            "Some Knowledge Brain chunks "
            "could not be resolved."
        )

    if not enrichment.get(
        "requested"
    ):
        warnings.append(
            "Knowledge Brain enrichment was "
            "disabled; topic aggregation may "
            "fall back to unclassified."
        )

    return {
        "schema_version":
            REPORT_SCHEMA,
        "analytics_version":
            ANALYTICS_VERSION,
        "created_at_utc":
            utc_now_iso(),
        "source_snapshot": {
            "schema_version":
                snapshot.get(
                    "schema_version"
                ),
            "sync_version":
                snapshot.get(
                    "sync_version"
                ),
            "created_at_utc":
                snapshot.get(
                    "created_at_utc"
                ),
            "deck_name":
                snapshot.get(
                    "scope",
                    {}
                ).get(
                    "deck_name"
                ),
            "required_tag":
                snapshot.get(
                    "scope",
                    {}
                ).get(
                    "required_tag"
                ),
            "partial_review_window":
                partial_window,
        },
        "safety": {
            "read_only": True,
            "anki_write_performed": False,
            "database_write_performed": False,
            "absolute_knowledge_claimed": False,
        },
        "knowledge_brain_enrichment":
            enrichment,
        "coverage": {
            "mapped_card_count":
                total_card_count,
            "reviewed_card_count":
                reviewed_card_count,
            "introduced_coverage_ratio":
                ratio(
                    reviewed_card_count,
                    total_card_count,
                ),
            "reviewed_source_document_count":
                len(
                    source_documents
                ),
            "reviewed_source_page_count":
                len(
                    source_pages
                ),
            "reviewed_source_documents":
                sorted(
                    source_documents
                ),
        },
        "recall_strength": {
            "data_sufficiency":
                sufficiency,
            "review_count":
                review_count,
            "valid_rating_count":
                valid_rating_count,
            "ratings": {
                name:
                    total_ratings[name]
                for name in (
                    "again",
                    "hard",
                    "good",
                    "easy",
                    "other",
                )
            },
            "observed_good_easy_ratio":
                ratio(
                    good_easy_count,
                    valid_rating_count,
                ),
            "fsrs_retrievability_mean":
                (
                    round(
                        sum(
                            retrievabilities
                        )
                        / len(
                            retrievabilities
                        ),
                        4,
                    )
                    if retrievabilities
                    else None
                ),
            "fsrs_retrievability_card_count":
                len(
                    retrievabilities
                ),
        },
        "weak_areas": {
            "weak_card_count":
                len(
                    weak_cards
                ),
            "watch_card_count":
                len(
                    watch_cards
                ),
            "repeated_failure_count":
                len(
                    repeated_failures
                ),
            "weak_cards":
                weak_cards,
            "watch_cards":
                watch_cards,
            "repeated_failures":
                repeated_failures,
        },
        "topics":
            aggregate_topics(
                cards
            ),
        "cards":
            cards,
        "warnings":
            warnings,
    }


def render_markdown(
    report: dict,
) -> str:
    coverage = report[
        "coverage"
    ]

    recall = report[
        "recall_strength"
    ]

    weak = report[
        "weak_areas"
    ]

    sufficiency = recall[
        "data_sufficiency"
    ]

    coverage_ratio = coverage[
        "introduced_coverage_ratio"
    ]

    coverage_text = (
        f"{coverage_ratio:.1%}"
        if coverage_ratio
        is not None
        else "n/a"
    )

    observed_ratio = recall[
        "observed_good_easy_ratio"
    ]

    observed_text = (
        f"{observed_ratio:.1%}"
        if observed_ratio
        is not None
        else "n/a"
    )

    lines = [
        "# Jason OS Knowledge Analytics",
        "",
        (
            "Deck: "
            + str(
                report[
                    "source_snapshot"
                ].get(
                    "deck_name"
                )
                or ""
            )
        ),
        "",
        "## Knowledge coverage",
        "",
        (
            "- Reviewed cards: "
            f"{coverage['reviewed_card_count']}"
            " / "
            f"{coverage['mapped_card_count']}"
            f" ({coverage_text})"
        ),
        (
            "- Reviewed source documents: "
            f"{coverage['reviewed_source_document_count']}"
        ),
        (
            "- Reviewed source pages: "
            f"{coverage['reviewed_source_page_count']}"
        ),
        "",
        "## Recall strength",
        "",
        (
            "- Data sufficiency: "
            f"{sufficiency['level']}"
        ),
        (
            "- Review events: "
            f"{recall['review_count']}"
        ),
        (
            "- Observed Good/Easy ratio: "
            f"{observed_text}"
        ),
        (
            "- Interpretation: "
            + sufficiency[
                "recall_strength_interpretation"
            ]
        ),
        "",
        "## Weak areas",
        "",
        (
            "- Weak cards: "
            f"{weak['weak_card_count']}"
        ),
        (
            "- Watch cards: "
            f"{weak['watch_card_count']}"
        ),
        (
            "- Repeated failures: "
            f"{weak['repeated_failure_count']}"
        ),
        "",
        "## Topic summary",
        "",
    ]

    topics = report.get(
        "topics"
    ) or []

    if topics:
        for topic in topics:
            ratio_value = topic[
                "observed_good_easy_ratio"
            ]

            ratio_text = (
                f"{ratio_value:.1%}"
                if ratio_value
                is not None
                else "n/a"
            )

            lines.append(
                "- "
                + str(
                    topic[
                        "topic"
                    ]
                )
                + ": "
                + (
                    f"{topic['reviewed_card_count']}"
                    f"/{topic['card_count']} "
                    "cards reviewed; "
                    f"{topic['review_count']} "
                    "reviews; "
                    "Good/Easy "
                    f"{ratio_text}; "
                    f"{topic['weak_card_count']} "
                    "weak"
                )
            )

    else:
        lines.append(
            "- No topic data available."
        )

    if weak[
        "weak_cards"
    ]:
        lines.extend([
            "",
            "## Weak-card source locators",
            "",
        ])

        for card in weak[
            "weak_cards"
        ]:
            labels = [
                str(
                    item.get(
                        "locator_label"
                    )
                    or ""
                ).strip()
                for item in (
                    card[
                        "source"
                    ][
                        "locators"
                    ]
                )
                if str(
                    item.get(
                        "locator_label"
                    )
                    or ""
                ).strip()
            ]

            lines.append(
                "- "
                + card[
                    "card_key"
                ][:12]
                + ": "
                + (
                    ", ".join(
                        labels
                    )
                    or "source unresolved"
                )
                + " — "
                + ", ".join(
                    card[
                        "weak_reasons"
                    ]
                )
            )

    if report[
        "warnings"
    ]:
        lines.extend([
            "",
            "## Warnings",
            "",
        ])

        for warning in report[
            "warnings"
        ]:
            lines.append(
                "- " + warning
            )

    lines.extend([
        "",
        (
            "_This report estimates observed "
            "learning coverage and recall "
            "behavior. It does not measure "
            "absolute human knowledge._"
        ),
        "",
    ])

    return "\n".join(
        lines
    )


def self_test() -> None:
    snapshot = {
        "schema_version":
            SUPPORTED_SNAPSHOT_SCHEMA,
        "sync_version":
            "self-test",
        "created_at_utc":
            "2026-01-01T00:00:00Z",
        "scope": {
            "deck_name":
                "Self Test",
            "required_tag":
                "jason-os",
            "since_review_id_ms":
                None,
        },
        "cards": [
            {
                "card_key":
                    "weak-card",
                "anki_card_id":
                    1,
                "knowledge_mapping": {
                    "chunk_ids": [101],
                    "source_title":
                        "Test Source",
                    "source_page":
                        "p.9",
                },
                "scheduling": {
                    "reps": 4,
                    "lapses": 2,
                    "retrievability":
                        0.62,
                    "stability":
                        2.1,
                    "difficulty":
                        8.0,
                },
                "reviews": [
                    {
                        "review_id":
                            1760000000000,
                        "rating": 1,
                        "new_interval": -600,
                        "previous_interval": 0,
                    },
                    {
                        "review_id":
                            1760003600000,
                        "rating": 1,
                        "new_interval": -600,
                        "previous_interval": -600,
                    },
                    {
                        "review_id":
                            1760086400000,
                        "rating": 2,
                        "new_interval": 1,
                        "previous_interval": -600,
                    },
                ],
            },
            {
                "card_key":
                    "good-card",
                "anki_card_id":
                    2,
                "knowledge_mapping": {
                    "chunk_ids": [102],
                    "source_title":
                        "Test Source",
                    "source_page":
                        "p.10",
                },
                "scheduling": {
                    "reps": 3,
                    "lapses": 0,
                    "retrievability":
                        0.94,
                    "stability":
                        12.0,
                    "difficulty":
                        3.0,
                },
                "reviews": [
                    {
                        "review_id":
                            1760000001000,
                        "rating": 3,
                        "new_interval": 1,
                        "previous_interval": 0,
                    },
                    {
                        "review_id":
                            1760086401000,
                        "rating": 4,
                        "new_interval": 4,
                        "previous_interval": 1,
                    },
                ],
            },
        ],
    }

    locators = {
        101: {
            "chunk_id": 101,
            "document_id": 9,
            "document_title":
                "Test Source",
            "domain":
                "test-domain",
            "topic":
                "weak-topic",
            "page_start": 9,
            "page_end": 9,
            "locator_label":
                "Test Source — p.9",
            "source_filename":
                "test.pdf",
            "source_url": "",
        },
        102: {
            "chunk_id": 102,
            "document_id": 9,
            "document_title":
                "Test Source",
            "domain":
                "test-domain",
            "topic":
                "strong-topic",
            "page_start": 10,
            "page_end": 10,
            "locator_label":
                "Test Source — p.10",
            "source_filename":
                "test.pdf",
            "source_url": "",
        },
    }

    report = build_report(
        snapshot,
        locators,
        {
            "requested": True,
            "resolved_count": 2,
            "missing_chunk_ids": [],
            "database_write_performed":
                False,
        },
    )

    assert (
        report[
            "coverage"
        ][
            "reviewed_card_count"
        ]
        == 2
    )

    assert (
        report[
            "weak_areas"
        ][
            "weak_card_count"
        ]
        == 1
    )

    assert (
        report[
            "weak_areas"
        ][
            "repeated_failure_count"
        ]
        == 1
    )

    weak_card = (
        report[
            "weak_areas"
        ][
            "weak_cards"
        ][0]
    )

    assert (
        weak_card[
            "source"
        ][
            "locators"
        ][0][
            "locator_label"
        ]
        == "Test Source — p.9"
    )

    topics = {
        item["topic"]:
            item
        for item in report[
            "topics"
        ]
    }

    assert (
        "weak-topic"
        in topics
    )

    print(
        "SR-H self-test PASS"
    )

    print(
        "Reviewed cards:",
        report[
            "coverage"
        ][
            "reviewed_card_count"
        ],
    )

    print(
        "Weak cards:",
        report[
            "weak_areas"
        ][
            "weak_card_count"
        ],
    )

    print(
        "Repeated failures:",
        report[
            "weak_areas"
        ][
            "repeated_failure_count"
        ],
    )

    print(
        "Weak source:",
        weak_card[
            "source"
        ][
            "locators"
        ][0][
            "locator_label"
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a Jason OS Anki review "
            "snapshot and map learning signals "
            "back to Knowledge Brain sources. "
            "Read-only; no Anki or DB writes."
        )
    )

    parser.add_argument(
        "snapshot",
        nargs="?",
        help=(
            "anki-review-snapshot-v1 JSON"
        ),
    )

    parser.add_argument(
        "--output",
        help=(
            "Optional knowledge analytics "
            "JSON report path"
        ),
    )

    parser.add_argument(
        "--markdown-output",
        help=(
            "Optional human-readable "
            "Markdown report path"
        ),
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
        help=(
            "Knowledge Brain PostgreSQL "
            "container used for read-only "
            "chunk/topic/source enrichment"
        ),
    )

    parser.add_argument(
        "--no-kb-enrichment",
        action="store_true",
        help=(
            "Do not query Knowledge Brain; "
            "analyze snapshot only"
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run deterministic analytics "
            "self-test and exit"
        ),
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    if not args.snapshot:
        raise SystemExit(
            "snapshot is required unless "
            "--self-test is used"
        )

    snapshot_path = (
        Path(args.snapshot)
        .expanduser()
        .resolve()
    )

    try:
        snapshot = load_snapshot(
            snapshot_path
        )

        cards = [
            card
            for card in (
                snapshot.get(
                    "cards"
                )
                or []
            )
            if isinstance(
                card,
                dict,
            )
        ]

        db_container = (
            None
            if args.no_kb_enrichment
            else args.db_container
        )

        (
            locator_by_chunk,
            enrichment,
        ) = resolve_knowledge(
            cards,
            db_container,
        )

        report = build_report(
            snapshot,
            locator_by_chunk,
            enrichment,
        )

        markdown = render_markdown(
            report
        )

        if args.output:
            atomic_write_json(
                Path(args.output)
                .expanduser()
                .resolve(),
                report,
            )

        if args.markdown_output:
            atomic_write_text(
                Path(
                    args.markdown_output
                )
                .expanduser()
                .resolve(),
                markdown,
            )

    except Exception as exc:
        raise SystemExit(
            "Knowledge analytics failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    print(markdown)

    print(
        "Analytics schema:",
        report[
            "schema_version"
        ],
    )

    print(
        "Read only:",
        report[
            "safety"
        ][
            "read_only"
        ],
    )

    print(
        "Anki write performed:",
        report[
            "safety"
        ][
            "anki_write_performed"
        ],
    )

    print(
        "Database write performed:",
        report[
            "safety"
        ][
            "database_write_performed"
        ],
    )


if __name__ == "__main__":
    main()
