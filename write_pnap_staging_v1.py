#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

from pathlib import Path

import detect_source_changes_v1 as detector
import source_monitor_baseline_v1 as baseline


DEFAULT_STATE_ROOT = Path(
    "/var/lib/jason-os/source-monitor-staging"
)

ALLOWED_WRITER_REMOTE = (
    "gdrive-bd-write:"
)

ALLOWED_STAGING_PREFIX = (
    "_Staging_Incoming/"
)


def sha256_file(path):
    h = hashlib.sha256()

    with Path(path).open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


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

    writer = config.get(
        "drive_writer"
    )

    if not isinstance(writer, dict):
        raise ValueError(
            f"{source_id}: drive_writer "
            "configuration is missing."
        )

    validate_writer_config(
        source_id,
        writer
    )

    return registry, config, writer


def validate_writer_config(
    source_id,
    writer,
):
    required = (
        "enabled",
        "environment",
        "remote",
        "destination",
        "allow_overwrite",
    )

    missing = [
        key
        for key in required
        if key not in writer
    ]

    if missing:
        raise ValueError(
            f"{source_id}: drive_writer "
            "missing fields: "
            + ", ".join(missing)
        )

    if writer["enabled"] is not True:
        raise ValueError(
            f"{source_id}: drive_writer "
            "is disabled."
        )

    if writer["environment"] != "staging":
        raise ValueError(
            f"{source_id}: writer must "
            "remain staging-only in v1."
        )

    if writer["remote"] != (
        ALLOWED_WRITER_REMOTE
    ):
        raise ValueError(
            f"{source_id}: unexpected "
            "writer remote."
        )

    destination = writer[
        "destination"
    ]

    if not isinstance(
        destination,
        str
    ):
        raise ValueError(
            f"{source_id}: destination "
            "must be a string."
        )

    if (
        destination.startswith("/")
        or ".." in Path(
            destination
        ).parts
        or not destination.startswith(
            ALLOWED_STAGING_PREFIX
        )
    ):
        raise ValueError(
            f"{source_id}: destination "
            "must remain under "
            "_Staging_Incoming/."
        )

    if writer[
        "allow_overwrite"
    ] is not False:
        raise ValueError(
            f"{source_id}: overwrite "
            "must remain disabled in v1."
        )


def load_expected_hash(
    state_root,
    source_id,
):
    state_root = Path(
        state_root
    )

    path = baseline.baseline_path(
        state_root,
        source_id
    )

    payload = baseline.load_baseline(
        path
    )

    if payload.get(
        "source_id"
    ) != source_id:
        raise ValueError(
            "Baseline source_id mismatch."
        )

    try:
        expected = (
            payload[
                "observation"
            ]["document"]["sha256"]
        )
    except KeyError as exc:
        raise ValueError(
            "Baseline document SHA-256 "
            "is missing."
        ) from exc

    if not (
        isinstance(expected, str)
        and len(expected) == 64
    ):
        raise ValueError(
            "Baseline document SHA-256 "
            "is invalid."
        )

    return expected, path


def download_document(
    config,
    destination_path,
):
    allowed_hosts = config[
        "allowed_hosts"
    ]

    url = config[
        "canonical_url"
    ]

    detector.validate_url(
        url,
        allowed_hosts
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Jason-OS-PNAP-Writer/1.0",
            "Accept":
                "application/pdf,*/*",
        },
        method="GET",
    )

    h = hashlib.sha256()

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        final_url = response.geturl()

        detector.validate_url(
            final_url,
            allowed_hosts
        )

        headers = response.headers

        if hasattr(
            headers,
            "get_content_type"
        ):
            content_type = (
                headers.get_content_type()
            )
        else:
            content_type = (
                headers.get(
                    "Content-Type",
                    ""
                )
                .split(";", 1)[0]
                .strip()
                .lower()
            )

        if content_type != (
            "application/pdf"
        ):
            raise RuntimeError(
                "Unexpected document "
                f"content type: "
                f"{content_type!r}"
            )

        size = 0

        with Path(
            destination_path
        ).open("wb") as out:
            while True:
                block = response.read(
                    1024 * 1024
                )

                if not block:
                    break

                out.write(block)
                h.update(block)
                size += len(block)

    with Path(
        destination_path
    ).open("rb") as f:
        magic = f.read(5)

    if magic != b"%PDF-":
        raise RuntimeError(
            "Downloaded file does not "
            "have a PDF signature."
        )

    return {
        "url": final_url,
        "content_type": content_type,
        "content_length": size,
        "sha256": h.hexdigest(),
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
            missing_markers = (
                "directory not found",
                "object not found",
            )

            lowered = stderr.lower()

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


def remote_parent_and_name(
    destination,
):
    path = Path(destination)

    parent = path.parent.as_posix()

    if parent == ".":
        parent = ""

    return parent, path.name


def remote_file_exists(
    remote,
    destination,
):
    parent, name = (
        remote_parent_and_name(
            destination
        )
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
        return False

    items = json.loads(
        output or "[]"
    )

    return any(
        item.get("Name") == name
        and item.get("IsDir") is False
        for item in items
    )


def ensure_remote_parent(
    remote,
    destination,
):
    parent, _ = (
        remote_parent_and_name(
            destination
        )
    )

    if not parent:
        return

    run_rclone(
        [
            "mkdir",
            remote + parent,
        ]
    )


def upload_and_verify(
    local_path,
    *,
    remote,
    destination,
):
    if remote_file_exists(
        remote,
        destination,
    ):
        raise FileExistsError(
            "Remote destination already "
            "exists; v1 refuses overwrite: "
            f"{remote}{destination}"
        )

    ensure_remote_parent(
        remote,
        destination,
    )

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
        prefix=(
            "jason-os-pnap-roundtrip-"
        ),
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

        if (
            local_sha
            != roundtrip_sha
        ):
            raise RuntimeError(
                "Remote round-trip "
                "SHA-256 mismatch. "
                "The staged object was "
                "left in place for "
                "manual inspection."
            )

        return {
            "remote_file":
                remote_file,
            "local_sha256":
                local_sha,
            "roundtrip_sha256":
                roundtrip_sha,
            "verified":
                True,
        }

    finally:
        roundtrip_path.unlink(
            missing_ok=True
        )


def build_plan(
    *,
    source_id,
    config,
    writer,
    expected_sha,
    baseline_path,
    download,
):
    return {
        "environment":
            writer["environment"],
        "source_id":
            source_id,
        "document_code":
            config["document_code"],
        "source_url":
            config["canonical_url"],
        "baseline_path":
            str(baseline_path),
        "expected_sha256":
            expected_sha,
        "download_sha256":
            download["sha256"],
        "download_bytes":
            download[
                "content_length"
            ],
        "writer_remote":
            writer["remote"],
        "writer_destination":
            writer["destination"],
        "overwrite_allowed":
            writer[
                "allow_overwrite"
            ],
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only BD PNAP Drive "
            "writer with baseline and "
            "round-trip SHA-256 guards."
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
            "Actually upload to the "
            "staging-only Drive path. "
            "Without this flag, perform "
            "download and validation only."
        ),
    )

    args = parser.parse_args()

    (
        _registry,
        config,
        writer,
    ) = load_source(
        args.registry,
        args.source,
    )

    expected_sha, base_path = (
        load_expected_hash(
            args.state_root,
            args.source,
        )
    )

    with tempfile.TemporaryDirectory(
        prefix="jason-os-pnap-writer-"
    ) as temp_dir:
        temp_dir = Path(temp_dir)

        local_path = (
            temp_dir
            / (
                config[
                    "document_code"
                ].replace("-", "")
                + ".pdf"
            )
        )

        download = download_document(
            config,
            local_path,
        )

        if (
            download["sha256"]
            != expected_sha
        ):
            raise RuntimeError(
                "Live document SHA-256 "
                "differs from the approved "
                "baseline. Refusing Drive "
                "write until the change is "
                "reviewed."
            )

        plan = build_plan(
            source_id=args.source,
            config=config,
            writer=writer,
            expected_sha=expected_sha,
            baseline_path=base_path,
            download=download,
        )

        if not args.execute:
            print(
                json.dumps(
                    {
                        "mode":
                            "dry-run",
                        "status":
                            "READY_TO_STAGE",
                        "plan":
                            plan,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        result = upload_and_verify(
            local_path,
            remote=writer["remote"],
            destination=writer[
                "destination"
            ],
        )

        print(
            json.dumps(
                {
                    "mode":
                        "execute",
                    "status":
                        "STAGED_AND_VERIFIED",
                    "plan":
                        plan,
                    "result":
                        result,
                    "baseline_updated":
                        False,
                    "canonical_current_updated":
                        False,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
