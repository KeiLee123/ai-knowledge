#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import yaml

import detect_source_changes_v1 as detector
from version_snapshot_store_v1 import (
    current_snapshot_path,
    load_record,
    validate_state_root,
    validate_source_id,
)


VERSION = "source-monitor-schedule-v1"


def load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected YAML mapping: {path}"
        )

    return payload


def validate_schedule(
    *,
    schedule_path: Path,
    registry_path: Path,
    state_root: Path,
    require_references: bool = True,
) -> dict:
    state_root = validate_state_root(
        state_root
    )

    schedule = load_yaml(
        schedule_path
    )

    if (
        schedule.get(
            "source_monitor_schedule_version"
        )
        != 1
    ):
        raise ValueError(
            "Unsupported source monitor schedule version"
        )

    if (
        schedule.get("environment")
        != "staging"
    ):
        raise ValueError(
            "Source monitor schedule must be staging-only"
        )

    defaults = (
        schedule.get("defaults")
        or {}
    )

    if (
        defaults.get("cadence")
        != "daily"
        or defaults.get("timezone")
        != "Asia/Hong_Kong"
        or str(defaults.get("time"))
        != "09:15"
    ):
        raise ValueError(
            "M9 MVP schedule must remain daily 09:15 Asia/Hong_Kong"
        )

    entries = schedule.get(
        "sources"
    )

    if (
        not isinstance(entries, list)
        or not entries
    ):
        raise ValueError(
            "Schedule sources must be a non-empty list"
        )

    registry = detector.load_registry(
        registry_path
    )

    approved = []
    seen = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(
                "Schedule entry must be a mapping"
            )

        source_id = validate_source_id(
            str(
                entry.get("source_id")
                or ""
            )
        )

        if source_id in seen:
            raise ValueError(
                f"Duplicate scheduled source: {source_id}"
            )

        seen.add(
            source_id
        )

        if (
            entry.get("enabled")
            is not True
        ):
            continue

        source = (
            registry.get("sources")
            or {}
        ).get(
            source_id
        )

        if not isinstance(source, dict):
            raise ValueError(
                f"Scheduled source is absent from registry: {source_id}"
            )

        if (
            source.get("enabled")
            is not True
        ):
            raise ValueError(
                f"Scheduled source is disabled in registry: {source_id}"
            )

        detector.validate_source(
            source_id,
            source,
        )

        if require_references:
            reference_path = (
                current_snapshot_path(
                    state_root,
                    source_id,
                )
            )

            if not reference_path.is_file():
                raise FileNotFoundError(
                    "Scheduled source is missing current "
                    f"Staging version reference: {source_id}"
                )

            record = load_record(
                reference_path
            )

            if (
                record.get("source_id")
                != source_id
            ):
                raise ValueError(
                    "Stored reference source_id mismatch: "
                    f"{source_id}"
                )

        approved.append(
            source_id
        )

    if not approved:
        raise ValueError(
            "No enabled scheduled sources"
        )

    return {
        "version": VERSION,
        "environment": "staging",
        "source_ids": approved,
        "source_count": len(approved),
        "state_root": str(state_root),
        "production_access": False,
        "production_write": False,
    }


def main() -> None:
    root = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description=(
            "Validate the explicit M9 Staging source-monitor "
            "schedule and source readiness. No Production access."
        )
    )

    parser.add_argument(
        "--schedule",
        default=str(
            root
            / "source_monitor_schedule_v1.yaml"
        ),
    )
    parser.add_argument(
        "--registry",
        default=str(
            root
            / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--state-root",
        default=(
            "/var/lib/jason-os/"
            "source-monitor-staging"
        ),
    )
    parser.add_argument(
        "--skip-reference-check",
        action="store_true",
    )

    args = parser.parse_args()

    result = validate_schedule(
        schedule_path=Path(
            args.schedule
        ).expanduser().resolve(),
        registry_path=Path(
            args.registry
        ).expanduser().resolve(),
        state_root=Path(
            args.state_root
        ).expanduser(),
        require_references=(
            not args.skip_reference_check
        ),
    )

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )
    print()
    print(
        "STATUS: SOURCE_MONITOR_SCHEDULE_VALID"
    )


if __name__ == "__main__":
    main()
