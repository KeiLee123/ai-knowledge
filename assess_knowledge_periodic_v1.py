#!/usr/bin/env python3

import argparse
import datetime as dt
import json
from pathlib import Path


ASSESSMENT_VERSION = "sr-i-1"
ASSESSMENT_SCHEMA = "periodic-knowledge-assessment-v1"
SUPPORTED_REPORT_SCHEMA = "knowledge-analytics-report-v1"


def parse_utc(value: str) -> dt.datetime:
    text = str(value or "").strip()

    if not text:
        raise ValueError("report created_at_utc is required")

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = dt.datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        raise ValueError("report timestamp must include timezone")

    return parsed.astimezone(dt.timezone.utc)


def load_report(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if payload.get("schema_version") != SUPPORTED_REPORT_SCHEMA:
        raise RuntimeError(
            "Unsupported analytics report schema: "
            f"{payload.get('schema_version')!r}"
        )

    parse_utc(payload.get("created_at_utc"))

    return payload


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(text, encoding="utf-8")

    temporary.replace(path)


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)

    except (TypeError, ValueError):
        return default


def safe_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)

    except (TypeError, ValueError):
        return None


def signed_delta(current, previous):
    if current is None or previous is None:
        return None

    return current - previous


def report_scope(report: dict) -> tuple[str, str]:
    source = report.get("source_snapshot") or {}

    return (
        str(source.get("deck_name") or "").strip(),
        str(source.get("required_tag") or "").strip(),
    )


def report_timestamp(report: dict) -> dt.datetime:
    return parse_utc(report.get("created_at_utc"))


def topic_map(report: dict) -> dict[str, dict]:
    output = {}

    for item in report.get("topics") or []:
        if not isinstance(item, dict):
            continue

        topic = str(item.get("topic") or "").strip()

        if not topic:
            continue

        output[topic] = item

    return output


def ratings(report: dict) -> dict:
    source = (
        report.get("recall_strength", {}).get("ratings")
        or {}
    )

    return {
        name: safe_int(source.get(name), 0)
        for name in ("again", "hard", "good", "easy", "other")
    }


def compatibility_warnings(reports: list[dict]) -> list[str]:
    warnings = []

    if not reports:
        return warnings

    expected_scope = report_scope(reports[0])

    for index, report in enumerate(reports, 1):
        scope = report_scope(report)

        if scope != expected_scope:
            raise RuntimeError(
                "Reports use incompatible deck/tag scopes: "
                f"expected={expected_scope!r} got={scope!r} "
                f"at report #{index}"
            )

        source = report.get("source_snapshot") or {}

        if source.get("partial_review_window"):
            warnings.append(
                f"Report #{index} uses a partial review window; "
                "review-event deltas may be incomplete."
            )

    mapped_counts = {
        safe_int(
            report.get("coverage", {}).get("mapped_card_count"),
            0,
        )
        for report in reports
    }

    if len(mapped_counts) > 1:
        warnings.append(
            "Mapped-card denominator changed between reports; "
            "coverage-ratio changes may reflect deck growth or card changes."
        )

    return warnings


def compare_topics(previous: dict, current: dict) -> list[dict]:
    previous_topics = topic_map(previous)
    current_topics = topic_map(current)

    names = sorted(set(previous_topics) | set(current_topics))

    output = []

    for topic in names:
        before = previous_topics.get(topic) or {}
        after = current_topics.get(topic) or {}

        before_reviewed = safe_int(
            before.get("reviewed_card_count"),
            0,
        )

        after_reviewed = safe_int(
            after.get("reviewed_card_count"),
            0,
        )

        before_weak = safe_int(
            before.get("weak_card_count"),
            0,
        )

        after_weak = safe_int(
            after.get("weak_card_count"),
            0,
        )

        output.append({
            "topic": topic,
            "reviewed_card_count_previous": before_reviewed,
            "reviewed_card_count_current": after_reviewed,
            "reviewed_card_delta":
                after_reviewed - before_reviewed,
            "weak_card_count_previous": before_weak,
            "weak_card_count_current": after_weak,
            "weak_card_delta": after_weak - before_weak,
            "review_count_previous":
                safe_int(before.get("review_count"), 0),
            "review_count_current":
                safe_int(after.get("review_count"), 0),
            "observed_good_easy_ratio_previous":
                safe_float(before.get("observed_good_easy_ratio")),
            "observed_good_easy_ratio_current":
                safe_float(after.get("observed_good_easy_ratio")),
        })

    return output


def build_assessment(reports: list[dict]) -> dict:
    if not reports:
        raise ValueError("At least one analytics report is required")

    ordered = sorted(reports, key=report_timestamp)

    warnings = compatibility_warnings(ordered)

    current = ordered[-1]
    previous = ordered[-2] if len(ordered) >= 2 else None

    current_coverage = current.get("coverage") or {}
    current_recall = current.get("recall_strength") or {}
    current_weak = current.get("weak_areas") or {}

    current_ratings = ratings(current)

    scope_deck, scope_tag = report_scope(current)

    result = {
        "schema_version": ASSESSMENT_SCHEMA,
        "assessment_version": ASSESSMENT_VERSION,
        "created_at_utc":
            dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        "safety": {
            "read_only": True,
            "anki_write_performed": False,
            "database_write_performed": False,
            "absolute_knowledge_claimed": False,
        },
        "scope": {
            "deck_name": scope_deck,
            "required_tag": scope_tag,
        },
        "history": {
            "report_count": len(ordered),
            "baseline_at_utc": ordered[0].get("created_at_utc"),
            "current_at_utc": current.get("created_at_utc"),
            "previous_at_utc":
                previous.get("created_at_utc")
                if previous
                else None,
            "trend_available": previous is not None,
        },
        "current": {
            "mapped_card_count":
                safe_int(current_coverage.get("mapped_card_count"), 0),
            "reviewed_card_count":
                safe_int(current_coverage.get("reviewed_card_count"), 0),
            "introduced_coverage_ratio":
                safe_float(
                    current_coverage.get("introduced_coverage_ratio")
                ),
            "review_count":
                safe_int(current_recall.get("review_count"), 0),
            "ratings": current_ratings,
            "observed_good_easy_ratio":
                safe_float(
                    current_recall.get("observed_good_easy_ratio")
                ),
            "fsrs_retrievability_mean":
                safe_float(
                    current_recall.get("fsrs_retrievability_mean")
                ),
            "data_sufficiency":
                current_recall.get("data_sufficiency") or {},
            "weak_card_count":
                safe_int(current_weak.get("weak_card_count"), 0),
            "watch_card_count":
                safe_int(current_weak.get("watch_card_count"), 0),
            "repeated_failure_count":
                safe_int(current_weak.get("repeated_failure_count"), 0),
        },
        "changes": None,
        "topics": [],
        "warnings": warnings,
    }

    if previous is None:
        result["warnings"].append(
            "Only one report is available; baseline established but no trend can be calculated."
        )
        return result

    previous_coverage = previous.get("coverage") or {}
    previous_recall = previous.get("recall_strength") or {}
    previous_weak = previous.get("weak_areas") or {}

    previous_ratings = ratings(previous)

    current_reviewed = safe_int(
        current_coverage.get("reviewed_card_count"),
        0,
    )

    previous_reviewed = safe_int(
        previous_coverage.get("reviewed_card_count"),
        0,
    )

    current_mapped = safe_int(
        current_coverage.get("mapped_card_count"),
        0,
    )

    previous_mapped = safe_int(
        previous_coverage.get("mapped_card_count"),
        0,
    )

    current_reviews = safe_int(
        current_recall.get("review_count"),
        0,
    )

    previous_reviews = safe_int(
        previous_recall.get("review_count"),
        0,
    )

    current_ratio = safe_float(
        current_coverage.get("introduced_coverage_ratio")
    )

    previous_ratio = safe_float(
        previous_coverage.get("introduced_coverage_ratio")
    )

    current_good_easy = safe_float(
        current_recall.get("observed_good_easy_ratio")
    )

    previous_good_easy = safe_float(
        previous_recall.get("observed_good_easy_ratio")
    )

    current_retrievability = safe_float(
        current_recall.get("fsrs_retrievability_mean")
    )

    previous_retrievability = safe_float(
        previous_recall.get("fsrs_retrievability_mean")
    )

    current_weak_count = safe_int(
        current_weak.get("weak_card_count"),
        0,
    )

    previous_weak_count = safe_int(
        previous_weak.get("weak_card_count"),
        0,
    )

    current_repeated = safe_int(
        current_weak.get("repeated_failure_count"),
        0,
    )

    previous_repeated = safe_int(
        previous_weak.get("repeated_failure_count"),
        0,
    )

    rating_delta = {
        name:
            current_ratings[name]
            - previous_ratings[name]
        for name in current_ratings
    }

    result["changes"] = {
        "mapped_card_delta":
            current_mapped - previous_mapped,
        "reviewed_card_delta":
            current_reviewed - previous_reviewed,
        "introduced_coverage_ratio_delta":
            signed_delta(current_ratio, previous_ratio),
        "review_event_delta":
            current_reviews - previous_reviews,
        "rating_count_delta":
            rating_delta,
        "observed_good_easy_ratio_delta":
            signed_delta(current_good_easy, previous_good_easy),
        "fsrs_retrievability_mean_delta":
            signed_delta(
                current_retrievability,
                previous_retrievability,
            ),
        "weak_card_delta":
            current_weak_count - previous_weak_count,
        "repeated_failure_delta":
            current_repeated - previous_repeated,
    }

    result["topics"] = compare_topics(previous, current)

    if current_reviewed < previous_reviewed:
        result["warnings"].append(
            "Reviewed-card count decreased. This is not automatically interpreted as forgetting; "
            "cards or deck scope may have changed."
        )

    if current_reviews < previous_reviews:
        result["warnings"].append(
            "Cumulative review count decreased. Check whether one report used a partial or reset snapshot."
        )

    return result


def render_markdown(assessment: dict) -> str:
    current = assessment["current"]
    changes = assessment.get("changes")
    history = assessment["history"]

    ratio = current.get("introduced_coverage_ratio")

    coverage_text = (
        f"{ratio:.1%}"
        if ratio is not None
        else "n/a"
    )

    lines = [
        "# Jason OS Periodic Knowledge Assessment",
        "",
        f"Deck: {assessment['scope']['deck_name']}",
        "",
        "## Current coverage",
        "",
        (
            "- Reviewed cards: "
            f"{current['reviewed_card_count']} / "
            f"{current['mapped_card_count']} "
            f"({coverage_text})"
        ),
        (
            "- Review events: "
            f"{current['review_count']}"
        ),
        (
            "- Weak cards: "
            f"{current['weak_card_count']}"
        ),
        (
            "- Repeated failures: "
            f"{current['repeated_failure_count']}"
        ),
        (
            "- Data sufficiency: "
            f"{(current.get('data_sufficiency') or {}).get('level', 'unknown')}"
        ),
        "",
        "## Trend",
        "",
    ]

    if not history["trend_available"]:
        lines.append(
            "- Baseline established. A second compatible report is required for trend analysis."
        )

    else:
        lines.extend([
            (
                "- Reviewed-card delta: "
                f"{changes['reviewed_card_delta']:+d}"
            ),
            (
                "- Review-event delta: "
                f"{changes['review_event_delta']:+d}"
            ),
            (
                "- Weak-card delta: "
                f"{changes['weak_card_delta']:+d}"
            ),
            (
                "- Repeated-failure delta: "
                f"{changes['repeated_failure_delta']:+d}"
            ),
            "",
            "## Topic changes",
            "",
        ])

        for topic in assessment.get("topics") or []:
            lines.append(
                "- "
                + topic["topic"]
                + ": reviewed "
                + f"{topic['reviewed_card_delta']:+d}; "
                + "weak "
                + f"{topic['weak_card_delta']:+d}"
            )

    if assessment.get("warnings"):
        lines.extend([
            "",
            "## Warnings",
            "",
        ])

        for warning in assessment["warnings"]:
            lines.append("- " + warning)

    lines.extend([
        "",
        (
            "_This assessment tracks observed learning behavior over time. "
            "It does not measure absolute human knowledge._"
        ),
        "",
    ])

    return "\n".join(lines)


def fixture_report(
    timestamp: str,
    mapped: int,
    reviewed: int,
    reviews: int,
    good: int,
    easy: int,
    again: int,
    hard: int,
    weak: int,
    repeated: int,
    topic_reviewed: int,
    topic_weak: int,
) -> dict:
    total = good + easy + again + hard

    return {
        "schema_version": SUPPORTED_REPORT_SCHEMA,
        "analytics_version": "self-test",
        "created_at_utc": timestamp,
        "source_snapshot": {
            "deck_name": "Self Test",
            "required_tag": "jason-os",
            "partial_review_window": False,
        },
        "coverage": {
            "mapped_card_count": mapped,
            "reviewed_card_count": reviewed,
            "introduced_coverage_ratio":
                reviewed / mapped if mapped else None,
        },
        "recall_strength": {
            "review_count": reviews,
            "ratings": {
                "again": again,
                "hard": hard,
                "good": good,
                "easy": easy,
                "other": 0,
            },
            "observed_good_easy_ratio":
                (good + easy) / total if total else None,
            "fsrs_retrievability_mean": None,
            "data_sufficiency": {
                "level": "insufficient",
            },
        },
        "weak_areas": {
            "weak_card_count": weak,
            "watch_card_count": 0,
            "repeated_failure_count": repeated,
        },
        "topics": [
            {
                "topic": "test-topic",
                "card_count": mapped,
                "reviewed_card_count": topic_reviewed,
                "review_count": reviews,
                "observed_good_easy_ratio":
                    (good + easy) / total if total else None,
                "weak_card_count": topic_weak,
                "repeated_failure_count": repeated,
            }
        ],
    }


def self_test() -> None:
    baseline = fixture_report(
        "2026-01-01T00:00:00Z",
        mapped=4,
        reviewed=2,
        reviews=8,
        good=3,
        easy=1,
        again=2,
        hard=2,
        weak=2,
        repeated=1,
        topic_reviewed=2,
        topic_weak=2,
    )

    current = fixture_report(
        "2026-01-08T00:00:00Z",
        mapped=4,
        reviewed=4,
        reviews=20,
        good=10,
        easy=4,
        again=3,
        hard=3,
        weak=1,
        repeated=0,
        topic_reviewed=4,
        topic_weak=1,
    )

    baseline_only = build_assessment([baseline])

    assert baseline_only["history"]["trend_available"] is False
    assert baseline_only["changes"] is None

    assessment = build_assessment([current, baseline])

    assert assessment["history"]["report_count"] == 2
    assert assessment["changes"]["reviewed_card_delta"] == 2
    assert assessment["changes"]["review_event_delta"] == 12
    assert assessment["changes"]["weak_card_delta"] == -1
    assert assessment["changes"]["repeated_failure_delta"] == -1
    assert assessment["topics"][0]["reviewed_card_delta"] == 2
    assert assessment["topics"][0]["weak_card_delta"] == -1
    assert assessment["safety"]["read_only"] is True
    assert assessment["safety"]["anki_write_performed"] is False
    assert assessment["safety"]["database_write_performed"] is False

    print("SR-I self-test PASS")
    print("Reports:", assessment["history"]["report_count"])
    print(
        "Reviewed-card delta:",
        assessment["changes"]["reviewed_card_delta"],
    )
    print(
        "Review-event delta:",
        assessment["changes"]["review_event_delta"],
    )
    print(
        "Weak-card delta:",
        assessment["changes"]["weak_card_delta"],
    )
    print(
        "Repeated-failure delta:",
        assessment["changes"]["repeated_failure_delta"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Jason OS knowledge analytics reports over time. "
            "Read-only; no Anki or database writes."
        )
    )

    parser.add_argument(
        "--report",
        action="append",
        help=(
            "knowledge-analytics-report-v1 JSON. "
            "Repeat for multiple reports."
        ),
    )

    parser.add_argument(
        "--history-dir",
        help=(
            "Directory containing knowledge-analytics-report-v1 JSON files."
        ),
    )

    parser.add_argument(
        "--output",
        help="Optional assessment JSON output path.",
    )

    parser.add_argument(
        "--markdown-output",
        help="Optional assessment Markdown output path.",
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    paths = []

    for value in args.report or []:
        paths.append(
            Path(value).expanduser().resolve()
        )

    if args.history_dir:
        directory = (
            Path(args.history_dir)
            .expanduser()
            .resolve()
        )

        if not directory.is_dir():
            raise SystemExit(
                f"History directory not found: {directory}"
            )

        paths.extend(
            sorted(directory.glob("*.json"))
        )

    deduped_paths = []
    seen = set()

    for path in paths:
        key = str(path)

        if key in seen:
            continue

        seen.add(key)
        deduped_paths.append(path)

    if not deduped_paths:
        raise SystemExit(
            "At least one --report or --history-dir is required unless --self-test is used"
        )

    try:
        reports = [
            load_report(path)
            for path in deduped_paths
        ]

        assessment = build_assessment(reports)
        markdown = render_markdown(assessment)

        if args.output:
            atomic_write_json(
                Path(args.output).expanduser().resolve(),
                assessment,
            )

        if args.markdown_output:
            atomic_write_text(
                Path(args.markdown_output).expanduser().resolve(),
                markdown,
            )

    except Exception as exc:
        raise SystemExit(
            "Periodic assessment failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print(markdown)
    print("Assessment schema:", assessment["schema_version"])
    print("Read only:", assessment["safety"]["read_only"])
    print(
        "Anki write performed:",
        assessment["safety"]["anki_write_performed"],
    )
    print(
        "Database write performed:",
        assessment["safety"]["database_write_performed"],
    )


if __name__ == "__main__":
    main()
