#!/usr/bin/env python3

import argparse
import datetime as dt
import hashlib
import json
import tempfile
from pathlib import Path

from analyze_anki_knowledge_v1 import (
    build_report,
    load_snapshot,
    render_markdown as render_analytics_markdown,
    resolve_knowledge,
)
from assess_knowledge_periodic_v1 import (
    build_assessment,
    load_report,
    render_markdown as render_assessment_markdown,
)
from source_locator_v1 import DEFAULT_DB_CONTAINER


RUNNER_VERSION = "sr-j-1"
DELIVERY_SCHEMA = "knowledge-report-delivery-v1"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc(value: str) -> dt.datetime:
    text = str(value or "").strip()

    if not text:
        raise ValueError(
            "snapshot created_at_utc is required"
        )

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = dt.datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        raise ValueError(
            "snapshot timestamp must include timezone"
        )

    return parsed.astimezone(dt.timezone.utc)


def slug_time(value: dt.datetime) -> str:
    return value.astimezone(
        dt.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def freshness(
    snapshot_created_at: dt.datetime,
    now: dt.datetime,
    stale_after_hours: float,
) -> dict:
    age_seconds = (
        now - snapshot_created_at
    ).total_seconds()

    age_hours = round(
        age_seconds / 3600,
        2,
    )

    if age_seconds < -300:
        status = "CLOCK_SKEW"

    elif age_hours > stale_after_hours:
        status = "STALE"

    else:
        status = "FRESH"

    return {
        "status":
            status,
        "snapshot_created_at_utc":
            iso_utc(
                snapshot_created_at
            ),
        "report_generated_at_utc":
            iso_utc(now),
        "age_hours":
            age_hours,
        "stale_after_hours":
            stale_after_hours,
    }


def history_reports(
    analytics_dir: Path,
) -> list[dict]:
    reports = []

    for path in sorted(
        analytics_dir.glob(
            "*.json"
        )
    ):
        reports.append(
            load_report(path)
        )

    if not reports:
        raise RuntimeError(
            "No analytics reports available"
        )

    return reports


def delivery_markdown(
    delivery: dict,
) -> str:
    data = delivery[
        "data_freshness"
    ]

    processed = delivery[
        "new_snapshot_processed"
    ]

    lines = [
        "# Jason OS Knowledge Report",
        "",
        "## Data freshness",
        "",
        (
            "- Status: "
            + str(
                data["status"]
            )
        ),
        (
            "- Latest Anki snapshot: "
            + str(
                data[
                    "snapshot_created_at_utc"
                ]
            )
        ),
        (
            "- Report generated: "
            + str(
                data[
                    "report_generated_at_utc"
                ]
            )
        ),
        (
            "- Snapshot age: "
            + str(
                data[
                    "age_hours"
                ]
            )
            + " hours"
        ),
        (
            "- New snapshot processed: "
            + (
                "yes"
                if processed
                else "no"
            )
        ),
    ]

    if data["status"] == "STALE":
        lines.extend([
            "",
            (
                "> The desktop has not supplied "
                "fresh Anki telemetry within the "
                "configured freshness window. "
                "The assessment below uses the "
                "latest available data."
            ),
        ])

    elif data[
        "status"
    ] == "CLOCK_SKEW":
        lines.extend([
            "",
            (
                "> The snapshot timestamp is in "
                "the future relative to the VPS. "
                "Check system clocks before "
                "interpreting the trend."
            ),
        ])

    lines.extend([
        "",
        render_assessment_markdown(
            delivery[
                "assessment"
            ]
        ).strip(),
        "",
    ])

    return "\n".join(lines)


def process_snapshot(
    snapshot_path: Path,
    work_dir: Path,
    db_container: str | None,
    stale_after_hours: float,
    now: dt.datetime | None = None,
) -> dict:
    now = now or utc_now()

    snapshot_path = (
        snapshot_path
        .expanduser()
        .resolve()
    )

    work_dir = (
        work_dir
        .expanduser()
        .resolve()
    )

    if not snapshot_path.is_file():
        raise RuntimeError(
            "Snapshot not found: "
            f"{snapshot_path}"
        )

    snapshot = load_snapshot(
        snapshot_path
    )

    snapshot_created_at = parse_utc(
        snapshot.get(
            "created_at_utc"
        )
    )

    snapshot_hash = file_sha256(
        snapshot_path
    )

    snapshot_slug = slug_time(
        snapshot_created_at
    )

    analytics_dir = (
        work_dir / "analytics"
    )

    assessments_dir = (
        work_dir / "assessments"
    )

    publish_dir = (
        work_dir / "publish"
    )

    for directory in (
        analytics_dir,
        assessments_dir,
        publish_dir,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    analytics_base = (
        snapshot_slug
        + "_"
        + snapshot_hash[:12]
    )

    analytics_json = (
        analytics_dir
        / (
            analytics_base
            + ".json"
        )
    )

    analytics_md = (
        analytics_dir
        / (
            analytics_base
            + ".md"
        )
    )

    new_snapshot_processed = (
        not analytics_json.exists()
    )

    if new_snapshot_processed:
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

        (
            locator_by_chunk,
            enrichment,
        ) = resolve_knowledge(
            cards,
            db_container,
        )

        analytics_report = build_report(
            snapshot,
            locator_by_chunk,
            enrichment,
        )

        analytics_report[
            "operational"
        ] = {
            "snapshot_sha256":
                snapshot_hash,
            "snapshot_created_at_utc":
                iso_utc(
                    snapshot_created_at
                ),
            "processed_at_utc":
                iso_utc(now),
            "runner_version":
                RUNNER_VERSION,
        }

        atomic_write_json(
            analytics_json,
            analytics_report,
        )

        atomic_write_text(
            analytics_md,
            render_analytics_markdown(
                analytics_report
            ),
        )

    reports = history_reports(
        analytics_dir
    )

    assessment = build_assessment(
        reports
    )

    run_slug = slug_time(now)

    assessment_base = (
        run_slug
        + "_"
        + snapshot_hash[:12]
    )

    assessment_path = (
        assessments_dir
        / (
            assessment_base
            + ".json"
        )
    )

    atomic_write_json(
        assessment_path,
        assessment,
    )

    data_freshness = freshness(
        snapshot_created_at,
        now,
        stale_after_hours,
    )

    delivery = {
        "schema_version":
            DELIVERY_SCHEMA,
        "runner_version":
            RUNNER_VERSION,
        "generated_at_utc":
            iso_utc(now),
        "new_snapshot_processed":
            new_snapshot_processed,
        "data_freshness":
            data_freshness,
        "source_snapshot": {
            "sha256":
                snapshot_hash,
            "created_at_utc":
                iso_utc(
                    snapshot_created_at
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
        },
        "history": {
            "analytics_report_count":
                len(reports),
        },
        "assessment":
            assessment,
        "safety": {
            "read_only": True,
            "anki_write_performed":
                False,
            "database_write_performed":
                False,
            "frozen_layers_modified":
                False,
        },
    }

    latest_json = (
        publish_dir / "latest.json"
    )

    latest_md = (
        publish_dir / "latest.md"
    )

    report_json = (
        publish_dir
        / (
            "report_"
            + run_slug
            + ".json"
        )
    )

    report_md = (
        publish_dir
        / (
            "report_"
            + run_slug
            + ".md"
        )
    )

    rendered = delivery_markdown(
        delivery
    )

    atomic_write_json(
        latest_json,
        delivery,
    )

    atomic_write_text(
        latest_md,
        rendered,
    )

    atomic_write_json(
        report_json,
        delivery,
    )

    atomic_write_text(
        report_md,
        rendered,
    )

    return delivery


def self_test() -> None:
    now = utc_now()

    def snapshot(
        created_at: dt.datetime,
        second_reviewed: bool,
        weak_first: bool,
    ) -> dict:
        first_reviews = (
            [
                {
                    "review_id":
                        1760000000000,
                    "rating": 1,
                    "new_interval":
                        -600,
                    "previous_interval":
                        0,
                },
                {
                    "review_id":
                        1760003600000,
                    "rating": 1,
                    "new_interval":
                        -600,
                    "previous_interval":
                        -600,
                },
                {
                    "review_id":
                        1760086400000,
                    "rating": 2,
                    "new_interval":
                        1,
                    "previous_interval":
                        -600,
                },
            ]
            if weak_first
            else [
                {
                    "review_id":
                        1761000000000,
                    "rating": 3,
                    "new_interval":
                        2,
                    "previous_interval":
                        1,
                }
            ]
        )

        cards = [
            {
                "card_key":
                    "card-one",
                "anki_card_id":
                    1,
                "knowledge_mapping": {
                    "chunk_ids": [101],
                    "source_title":
                        "Self Test",
                    "source_page":
                        "p.1",
                },
                "scheduling": {
                    "reps":
                        len(
                            first_reviews
                        ),
                    "lapses":
                        (
                            2
                            if weak_first
                            else 0
                        ),
                    "retrievability":
                        None,
                    "stability":
                        None,
                    "difficulty":
                        None,
                },
                "reviews":
                    first_reviews,
            },
            {
                "card_key":
                    "card-two",
                "anki_card_id":
                    2,
                "knowledge_mapping": {
                    "chunk_ids": [102],
                    "source_title":
                        "Self Test",
                    "source_page":
                        "p.2",
                },
                "scheduling": {
                    "reps":
                        (
                            1
                            if second_reviewed
                            else 0
                        ),
                    "lapses": 0,
                    "retrievability":
                        None,
                    "stability":
                        None,
                    "difficulty":
                        None,
                },
                "reviews":
                    (
                        [{
                            "review_id":
                                1761000001000,
                            "rating": 3,
                            "new_interval":
                                -600,
                            "previous_interval":
                                0,
                        }]
                        if second_reviewed
                        else []
                    ),
            },
        ]

        return {
            "schema_version":
                "anki-review-snapshot-v1",
            "sync_version":
                "sr-j-self-test",
            "created_at_utc":
                iso_utc(
                    created_at
                ),
            "scope": {
                "deck_name":
                    "Self Test",
                "required_tag":
                    "jason-os",
                "since_review_id_ms":
                    None,
            },
            "cards":
                cards,
        }

    with tempfile.TemporaryDirectory(
        prefix="sr-j-self-test-"
    ) as temp:
        root = Path(temp)

        baseline_path = (
            root / "baseline.json"
        )

        current_path = (
            root / "current.json"
        )

        baseline_path.write_text(
            json.dumps(
                snapshot(
                    now
                    - dt.timedelta(
                        days=7
                    ),
                    second_reviewed=False,
                    weak_first=True,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        current_path.write_text(
            json.dumps(
                snapshot(
                    now
                    - dt.timedelta(
                        hours=1
                    ),
                    second_reviewed=True,
                    weak_first=False,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        work_dir = (
            root / "work"
        )

        first = process_snapshot(
            baseline_path,
            work_dir,
            db_container=None,
            stale_after_hours=48,
            now=now,
        )

        assert (
            first[
                "data_freshness"
            ][
                "status"
            ]
            == "STALE"
        )

        assert (
            first[
                "history"
            ][
                "analytics_report_count"
            ]
            == 1
        )

        duplicate = process_snapshot(
            baseline_path,
            work_dir,
            db_container=None,
            stale_after_hours=48,
            now=now,
        )

        assert (
            duplicate[
                "new_snapshot_processed"
            ]
            is False
        )

        assert (
            duplicate[
                "history"
            ][
                "analytics_report_count"
            ]
            == 1
        )

        current = process_snapshot(
            current_path,
            work_dir,
            db_container=None,
            stale_after_hours=48,
            now=now,
        )

        assert (
            current[
                "data_freshness"
            ][
                "status"
            ]
            == "FRESH"
        )

        assert (
            current[
                "history"
            ][
                "analytics_report_count"
            ]
            == 2
        )

        assessment = current[
            "assessment"
        ]

        assert (
            assessment[
                "history"
            ][
                "trend_available"
            ]
            is True
        )

        assert (
            assessment[
                "changes"
            ][
                "reviewed_card_delta"
            ]
            == 1
        )

        assert (
            assessment[
                "changes"
            ][
                "weak_card_delta"
            ]
            == -1
        )

        assert (
            current[
                "safety"
            ][
                "anki_write_performed"
            ]
            is False
        )

        assert (
            current[
                "safety"
            ][
                "database_write_performed"
            ]
            is False
        )

        assert (
            (
                work_dir
                / "publish"
                / "latest.json"
            ).is_file()
        )

        assert (
            (
                work_dir
                / "publish"
                / "latest.md"
            ).is_file()
        )

    print("SR-J self-test PASS")
    print(
        "Duplicate snapshot dedupe: PASS"
    )
    print(
        "Stale detection: PASS"
    )
    print(
        "Fresh detection: PASS"
    )
    print(
        "Trend generation: PASS"
    )
    print(
        "Anki write performed: False"
    )
    print(
        "Database write performed: False"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Process the latest Jason OS "
            "Anki snapshot into persistent "
            "SR-H/SR-I reporting history. "
            "No Anki writes."
        )
    )

    parser.add_argument(
        "--snapshot",
        help=(
            "anki-review-snapshot-v1 JSON"
        ),
    )

    parser.add_argument(
        "--work-dir",
        help=(
            "Runtime work directory"
        ),
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    parser.add_argument(
        "--no-kb-enrichment",
        action="store_true",
    )

    parser.add_argument(
        "--stale-after-hours",
        type=float,
        default=48.0,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    if not args.snapshot:
        raise SystemExit(
            "--snapshot is required"
        )

    if not args.work_dir:
        raise SystemExit(
            "--work-dir is required"
        )

    if args.stale_after_hours <= 0:
        raise SystemExit(
            "--stale-after-hours "
            "must be positive"
        )

    db_container = (
        None
        if args.no_kb_enrichment
        else args.db_container
    )

    try:
        delivery = process_snapshot(
            Path(args.snapshot),
            Path(args.work_dir),
            db_container=
                db_container,
            stale_after_hours=
                args.stale_after_hours,
        )

    except Exception as exc:
        raise SystemExit(
            "Automated reporting failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    print(
        delivery_markdown(
            delivery
        )
    )

    print(
        "Delivery schema:",
        delivery[
            "schema_version"
        ],
    )

    print(
        "Data freshness:",
        delivery[
            "data_freshness"
        ][
            "status"
        ],
    )

    print(
        "New snapshot processed:",
        delivery[
            "new_snapshot_processed"
        ],
    )

    print(
        "Analytics history:",
        delivery[
            "history"
        ][
            "analytics_report_count"
        ],
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
