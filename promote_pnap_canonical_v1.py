#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
import tempfile

from pathlib import Path

import detect_source_changes_v1 as detector
import source_monitor_baseline_v1 as baseline


DEFAULT_STATE_ROOT = Path(
    "/var/lib/jason-os/source-monitor-staging"
)

ALLOWED_REMOTE = "gdrive-bd-write:"
ALLOWED_SOURCE_PREFIX = "_Staging_Incoming/"
ALLOWED_DESTINATION_PREFIX = "Current/"


def sha256_file(path):
    h = hashlib.sha256()

    with Path(path).open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def validate_promotion_config(
    source_id,
    promotion,
    drive_writer,
):
    required = (
        "enabled",
        "controller_environment",
        "remote",
        "source",
        "destination",
        "allow_overwrite",
        "retain_staging_source",
        "update_baseline",
        "trigger_ingestion",
    )

    missing = [
        key
        for key in required
        if key not in promotion
    ]

    if missing:
        raise ValueError(
            f"{source_id}: canonical_promotion "
            "missing fields: "
            + ", ".join(missing)
        )

    if promotion["enabled"] is not True:
        raise ValueError(
            f"{source_id}: canonical promotion is disabled."
        )

    if promotion["controller_environment"] != "staging":
        raise ValueError(
            f"{source_id}: v1 controller must remain staging-only."
        )

    if promotion["remote"] != ALLOWED_REMOTE:
        raise ValueError(
            f"{source_id}: unexpected promotion remote."
        )

    source = promotion["source"]
    destination = promotion["destination"]

    if not isinstance(source, str):
        raise ValueError(
            f"{source_id}: promotion source must be a string."
        )

    if not isinstance(destination, str):
        raise ValueError(
            f"{source_id}: promotion destination must be a string."
        )

    source_parts = Path(source).parts
    destination_parts = Path(destination).parts

    if (
        source.startswith("/")
        or ".." in source_parts
        or not source.startswith(
            ALLOWED_SOURCE_PREFIX
        )
    ):
        raise ValueError(
            f"{source_id}: promotion source must remain under "
            "_Staging_Incoming/."
        )

    if (
        destination.startswith("/")
        or ".." in destination_parts
        or not destination.startswith(
            ALLOWED_DESTINATION_PREFIX
        )
    ):
        raise ValueError(
            f"{source_id}: promotion destination must remain under "
            "Current/."
        )

    if promotion["allow_overwrite"] is not False:
        raise ValueError(
            f"{source_id}: overwrite must remain disabled in v1."
        )

    if promotion["retain_staging_source"] is not True:
        raise ValueError(
            f"{source_id}: v1 must retain the Staging source."
        )

    if promotion["update_baseline"] is not False:
        raise ValueError(
            f"{source_id}: baseline mutation is forbidden in v1."
        )

    if promotion["trigger_ingestion"] is not False:
        raise ValueError(
            f"{source_id}: ingestion trigger is forbidden in v1."
        )

    if not isinstance(drive_writer, dict):
        raise ValueError(
            f"{source_id}: drive_writer configuration is required."
        )

    writer_destination = drive_writer.get(
        "destination"
    )

    if writer_destination != source:
        raise ValueError(
            f"{source_id}: promotion source must exactly match "
            "the Staging writer destination."
        )


def load_source(
    registry_path,
    source_id,
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

    promotion = config.get(
        "canonical_promotion"
    )

    if not isinstance(promotion, dict):
        raise ValueError(
            f"{source_id}: canonical_promotion configuration is missing."
        )

    validate_promotion_config(
        source_id,
        promotion,
        config.get("drive_writer"),
    )

    return registry, config, promotion


def load_expected_fingerprint(
    state_root,
    source_id,
):
    state_root = baseline.validate_state_root(
        state_root
    )

    path = baseline.baseline_path(
        state_root,
        source_id
    )

    payload = baseline.load_baseline(
        path
    )

    if payload.get("source_id") != source_id:
        raise ValueError(
            "Baseline source_id mismatch."
        )

    try:
        document = payload[
            "observation"
        ]["document"]
        expected_sha = document["sha256"]
    except KeyError as exc:
        raise ValueError(
            "Baseline document fingerprint is missing."
        ) from exc

    if not (
        isinstance(expected_sha, str)
        and len(expected_sha) == 64
    ):
        raise ValueError(
            "Baseline document SHA-256 is invalid."
        )

    expected_size = document.get(
        "content_length"
    )

    if (
        expected_size is not None
        and not isinstance(expected_size, int)
    ):
        raise ValueError(
            "Baseline document content length is invalid."
        )

    return {
        "sha256": expected_sha,
        "size": expected_size,
        "baseline_path": str(path),
    }


def run_rclone(
    args,
    *,
    missing_ok=False,
):
    result = subprocess.run(
        ["rclone", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        stderr = (
            result.stderr or ""
        ).strip()

        if missing_ok:
            lowered = stderr.lower()
            missing_markers = (
                "directory not found",
                "object not found",
            )

            if any(
                marker in lowered
                for marker in missing_markers
            ):
                return None

        raise RuntimeError(
            "rclone command failed: "
            + " ".join(args)
            + "\n"
            + stderr
        )

    return result.stdout


def remote_parent_and_name(path):
    path = Path(path)

    parent = path.parent.as_posix()

    if parent == ".":
        parent = ""

    return parent, path.name


def remote_file_info(
    remote,
    path,
):
    parent, name = remote_parent_and_name(
        path
    )

    target = (
        remote + parent
        if parent
        else remote
    )

    output = run_rclone(
        [
            "lsjson",
            target,
        ],
        missing_ok=True,
    )

    if output is None:
        return None

    items = json.loads(
        output or "[]"
    )

    for item in items:
        if (
            item.get("Name") == name
            and item.get("IsDir") is False
        ):
            return item

    return None


def remote_directory_exists(
    remote,
    path,
):
    output = run_rclone(
        [
            "lsf",
            remote + path,
        ],
        missing_ok=True,
    )

    return output is not None


def validate_remote_state(
    *,
    remote,
    source,
    destination,
    expected_size,
):
    source_info = remote_file_info(
        remote,
        source,
    )

    if source_info is None:
        raise FileNotFoundError(
            "Staged source does not exist: "
            f"{remote}{source}"
        )

    mime_type = source_info.get(
        "MimeType"
    )

    if mime_type != "application/pdf":
        raise ValueError(
            "Staged source is not an application/pdf object."
        )

    source_size = source_info.get(
        "Size"
    )

    if (
        expected_size is not None
        and source_size != expected_size
    ):
        raise RuntimeError(
            "Staged source size differs from the approved baseline."
        )

    destination_parent, _ = (
        remote_parent_and_name(
            destination
        )
    )

    if not destination_parent:
        raise ValueError(
            "Canonical destination must have an existing parent folder."
        )

    if not remote_directory_exists(
        remote,
        destination_parent,
    ):
        raise FileNotFoundError(
            "Canonical parent folder does not exist: "
            f"{remote}{destination_parent}"
        )

    destination_info = remote_file_info(
        remote,
        destination,
    )

    if destination_info is not None:
        raise FileExistsError(
            "Canonical destination already exists; "
            "v1 refuses overwrite: "
            f"{remote}{destination}"
        )

    return source_info


def download_staged_source(
    *,
    remote,
    source,
    local_path,
):
    run_rclone(
        [
            "copyto",
            remote + source,
            str(local_path),
        ]
    )

    with Path(local_path).open(
        "rb"
    ) as f:
        magic = f.read(5)

    if magic != b"%PDF-":
        raise RuntimeError(
            "Downloaded staged object does not have a PDF signature."
        )

    return {
        "sha256": sha256_file(
            local_path
        ),
        "size": Path(
            local_path
        ).stat().st_size,
    }


def promote_and_verify(
    local_path,
    *,
    remote,
    destination,
):
    remote_file = (
        remote + destination
    )

    run_rclone(
        [
            "copyto",
            str(local_path),
            remote_file,
        ]
    )

    with tempfile.NamedTemporaryFile(
        prefix="jason-os-canonical-roundtrip-",
        suffix=".pdf",
        delete=False,
    ) as temp:
        roundtrip_path = Path(
            temp.name
        )

    try:
        run_rclone(
            [
                "copyto",
                remote_file,
                str(roundtrip_path),
            ]
        )

        local_sha = sha256_file(
            local_path
        )

        roundtrip_sha = sha256_file(
            roundtrip_path
        )

        if local_sha != roundtrip_sha:
            raise RuntimeError(
                "Canonical round-trip SHA-256 mismatch. "
                "The new object was left in place for manual inspection."
            )

        return {
            "remote_file": remote_file,
            "local_sha256": local_sha,
            "roundtrip_sha256": roundtrip_sha,
            "verified": True,
        }

    finally:
        roundtrip_path.unlink(
            missing_ok=True
        )


def build_plan(
    *,
    source_id,
    config,
    promotion,
    expected,
    staged,
):
    return {
        "controller_environment":
            promotion[
                "controller_environment"
            ],
        "source_id":
            source_id,
        "document_code":
            config[
                "document_code"
            ],
        "baseline_path":
            expected[
                "baseline_path"
            ],
        "expected_sha256":
            expected[
                "sha256"
            ],
        "expected_bytes":
            expected[
                "size"
            ],
        "staged_sha256":
            staged[
                "sha256"
            ],
        "staged_bytes":
            staged[
                "size"
            ],
        "remote":
            promotion[
                "remote"
            ],
        "staging_source":
            promotion[
                "source"
            ],
        "canonical_destination":
            promotion[
                "destination"
            ],
        "overwrite_allowed":
            promotion[
                "allow_overwrite"
            ],
        "staging_source_retained":
            promotion[
                "retain_staging_source"
            ],
        "baseline_changed":
            False,
        "ingestion_triggered":
            False,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Explicit Staging-controlled canonical promotion "
            "for verified BD PNAP documents."
        )
    )

    parser.add_argument(
        "--registry",
        default=str(
            detector.DEFAULT_REGISTRY
        ),
    )

    parser.add_argument(
        "--source",
        required=True,
    )

    parser.add_argument(
        "--state-root",
        default=str(
            DEFAULT_STATE_ROOT
        ),
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Write the verified staged bytes to the exact "
            "registry-approved Current path. "
            "Without this flag, validate only."
        ),
    )

    args = parser.parse_args()

    (
        _registry,
        config,
        promotion,
    ) = load_source(
        args.registry,
        args.source,
    )

    expected = load_expected_fingerprint(
        args.state_root,
        args.source,
    )

    validate_remote_state(
        remote=promotion["remote"],
        source=promotion["source"],
        destination=promotion[
            "destination"
        ],
        expected_size=expected[
            "size"
        ],
    )

    with tempfile.TemporaryDirectory(
        prefix="jason-os-canonical-promotion-"
    ) as temp_dir:
        local_path = (
            Path(temp_dir)
            / (
                config[
                    "document_code"
                ].replace("-", "")
                + ".pdf"
            )
        )

        staged = download_staged_source(
            remote=promotion[
                "remote"
            ],
            source=promotion[
                "source"
            ],
            local_path=local_path,
        )

        if (
            staged["sha256"]
            != expected["sha256"]
        ):
            raise RuntimeError(
                "Staged source SHA-256 differs from the approved baseline. "
                "Refusing canonical promotion."
            )

        if (
            expected["size"] is not None
            and staged["size"]
            != expected["size"]
        ):
            raise RuntimeError(
                "Staged source byte size differs from the approved baseline. "
                "Refusing canonical promotion."
            )

        plan = build_plan(
            source_id=args.source,
            config=config,
            promotion=promotion,
            expected=expected,
            staged=staged,
        )

        if not args.execute:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "status": "READY_TO_PROMOTE",
                        "plan": plan,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        result = promote_and_verify(
            local_path,
            remote=promotion[
                "remote"
            ],
            destination=promotion[
                "destination"
            ],
        )

        print(
            json.dumps(
                {
                    "mode": "execute",
                    "status": "PROMOTED_AND_VERIFIED",
                    "plan": plan,
                    "result": result,
                    "staging_source_retained": True,
                    "baseline_changed": False,
                    "ingestion_triggered": False,
                    "production_modified": False,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
