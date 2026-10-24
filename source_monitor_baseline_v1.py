#!/usr/bin/env python3

import argparse
import json
import re
import tempfile

from pathlib import Path

import detect_source_changes_v1 as detector


BASELINE_VERSION = 1
SAFE_SOURCE_ID = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)


def validate_state_root(path):
    path = Path(path)

    if not path.is_absolute():
        raise ValueError(
            "state-root must be an absolute path."
        )

    return path


def baseline_path(
    state_root,
    source_id
):
    if not SAFE_SOURCE_ID.fullmatch(
        source_id
    ):
        raise ValueError(
            "source_id contains unsafe characters."
        )

    return (
        state_root
        / "baselines"
        / f"{source_id}.json"
    )


def load_selected_source(
    registry_path,
    source_id
):
    registry = detector.load_registry(
        registry_path
    )

    selected = detector.select_sources(
        registry,
        source_id=source_id
    )

    config = selected[source_id]

    detector.validate_source(
        source_id,
        config
    )

    return (
        registry,
        config,
        registry.get(
            "defaults",
            {}
        ),
    )


def probe(
    registry_path,
    source_id
):
    (
        registry,
        config,
        defaults,
    ) = load_selected_source(
        registry_path,
        source_id
    )

    observation = detector.probe_source(
        source_id,
        config,
        defaults
    )

    return registry, observation


def write_json_atomic(
    path,
    payload
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if path.exists():
        raise FileExistsError(
            f"Baseline already exists: {path}"
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as temp:
        temp_path = Path(temp.name)

        json.dump(
            payload,
            temp,
            indent=2,
            ensure_ascii=False,
        )

        temp.write("\n")

    try:
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(
            missing_ok=True
        )
        raise


def initialize_baseline(
    *,
    registry_path,
    source_id,
    state_root
):
    state_root = validate_state_root(
        state_root
    )

    path = baseline_path(
        state_root,
        source_id
    )

    if path.exists():
        raise FileExistsError(
            f"Baseline already exists: {path}"
        )

    registry, observation = probe(
        registry_path,
        source_id
    )

    payload = {
        "baseline_version":
            BASELINE_VERSION,
        "source_registry_version":
            registry[
                "source_registry_version"
            ],
        "source_id": source_id,
        "created_at":
            observation["checked_at"],
        "observation": observation,
    }

    write_json_atomic(
        path,
        payload
    )

    return {
        "mode": "initialize",
        "status": "BASELINE_CREATED",
        "source_id": source_id,
        "baseline_path": str(path),
        "baseline": payload,
    }


def load_baseline(path):
    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        payload = json.load(f)

    if payload.get(
        "baseline_version"
    ) != BASELINE_VERSION:
        raise ValueError(
            "Unsupported baseline_version."
        )

    if not isinstance(
        payload.get("observation"),
        dict
    ):
        raise ValueError(
            "Baseline observation is missing."
        )

    return payload


def compare_resource(
    baseline_resource,
    current_resource
):
    return {
        "changed":
            baseline_resource[
                "sha256"
            ]
            != current_resource[
                "sha256"
            ],
        "baseline_sha256":
            baseline_resource[
                "sha256"
            ],
        "current_sha256":
            current_resource[
                "sha256"
            ],
        "baseline_content_length":
            baseline_resource.get(
                "content_length"
            ),
        "current_content_length":
            current_resource.get(
                "content_length"
            ),
        "baseline_last_modified":
            baseline_resource.get(
                "last_modified"
            ),
        "current_last_modified":
            current_resource.get(
                "last_modified"
            ),
        "baseline_url":
            baseline_resource.get(
                "url"
            ),
        "current_url":
            current_resource.get(
                "url"
            ),
    }


def compare_observations(
    baseline_observation,
    current_observation
):
    index = compare_resource(
        baseline_observation["index"],
        current_observation["index"],
    )

    document = compare_resource(
        baseline_observation[
            "document"
        ],
        current_observation[
            "document"
        ],
    )

    if document["changed"]:
        status = "DOCUMENT_CHANGED"
    elif index["changed"]:
        status = "INDEX_CHANGED"
    else:
        status = "UNCHANGED"

    return status, {
        "index": index,
        "document": document,
    }


def check_against_baseline(
    *,
    registry_path,
    source_id,
    state_root
):
    state_root = validate_state_root(
        state_root
    )

    path = baseline_path(
        state_root,
        source_id
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Baseline not found: {path}"
        )

    baseline = load_baseline(path)

    if baseline.get(
        "source_id"
    ) != source_id:
        raise ValueError(
            "Baseline source_id mismatch."
        )

    _, current = probe(
        registry_path,
        source_id
    )

    status, changes = (
        compare_observations(
            baseline["observation"],
            current,
        )
    )

    return {
        "mode": "check",
        "status": status,
        "source_id": source_id,
        "baseline_path": str(path),
        "baseline_checked_at":
            baseline[
                "observation"
            ]["checked_at"],
        "current_checked_at":
            current["checked_at"],
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Baseline and compare layer for "
            "Jason OS Source Monitor v1."
        )
    )

    parser.add_argument(
        "--registry",
        default=str(
            detector.DEFAULT_REGISTRY
        ),
        help=(
            "Path to source_registry_v1.yaml."
        ),
    )

    parser.add_argument(
        "--source",
        required=True,
        help="Source Registry source ID.",
    )

    parser.add_argument(
        "--state-root",
        required=True,
        help=(
            "Absolute runtime state root. "
            "Example: "
            "/var/lib/jason-os/"
            "source-monitor-staging"
        ),
    )

    mode = parser.add_mutually_exclusive_group(
        required=True
    )

    mode.add_argument(
        "--initialize",
        action="store_true",
        help=(
            "Create the baseline once. "
            "Refuses to overwrite."
        ),
    )

    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Probe live source and compare "
            "with the stored baseline. "
            "Does not update the baseline."
        ),
    )

    args = parser.parse_args()

    if args.initialize:
        result = initialize_baseline(
            registry_path=args.registry,
            source_id=args.source,
            state_root=args.state_root,
        )
    else:
        result = check_against_baseline(
            registry_path=args.registry,
            source_id=args.source,
            state_root=args.state_root,
        )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
