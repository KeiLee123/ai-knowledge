#!/usr/bin/env python3

import json
import tempfile

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import write_pnap_staging_v1 as writer


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "source_registry_v1.yaml"
SCRIPT = ROOT / "write_pnap_staging_v1.py"


def test_registry_writer_contract():
    (
        _registry,
        config,
        drive_writer,
    ) = writer.load_source(
        REGISTRY,
        "BD_PNAP_APP145",
    )

    assert (
        config["document_code"]
        == "APP-145"
    )

    assert (
        drive_writer["environment"]
        == "staging"
    )

    assert (
        drive_writer["remote"]
        == "gdrive-bd-write:"
    )

    assert (
        drive_writer["destination"]
        == (
            "_Staging_Incoming/"
            "APP/APP145.pdf"
        )
    )

    assert (
        drive_writer[
            "allow_overwrite"
        ]
        is False
    )


def test_writer_path_guard():
    valid = {
        "enabled": True,
        "environment": "staging",
        "remote": "gdrive-bd-write:",
        "destination": (
            "_Staging_Incoming/"
            "APP/APP145.pdf"
        ),
        "allow_overwrite": False,
    }

    writer.validate_writer_config(
        "X",
        valid,
    )

    bad_current = dict(valid)
    bad_current[
        "destination"
    ] = "Current/APP/APP145.pdf"

    try:
        writer.validate_writer_config(
            "X",
            bad_current,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Current/ path should be "
            "rejected by staging writer."
        )

    bad_remote = dict(valid)
    bad_remote[
        "remote"
    ] = "gdrive:"

    try:
        writer.validate_writer_config(
            "X",
            bad_remote,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Read-only gdrive remote "
            "must not be accepted."
        )


def test_remote_exists_parser():
    listing = json.dumps(
        [
            {
                "Name":
                    "APP145.pdf",
                "IsDir": False,
            }
        ]
    )

    with patch.object(
        writer,
        "run_rclone",
        return_value=listing,
    ):
        assert writer.remote_file_exists(
            "gdrive-bd-write:",
            (
                "_Staging_Incoming/"
                "APP/APP145.pdf"
            ),
        ) is True


def test_missing_parent_means_absent():
    missing = SimpleNamespace(
        returncode=3,
        stdout="",
        stderr=(
            "ERROR : error listing: "
            "directory not found"
        ),
    )

    with patch.object(
        writer.subprocess,
        "run",
        return_value=missing,
    ):
        assert writer.remote_file_exists(
            "gdrive-bd-write:",
            (
                "_Staging_Incoming/"
                "APP/APP145.pdf"
            ),
        ) is False


def test_non_missing_rclone_error_still_fails():
    denied = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr=(
            "ERROR : permission denied"
        ),
    )

    with patch.object(
        writer.subprocess,
        "run",
        return_value=denied,
    ):
        try:
            writer.remote_file_exists(
                "gdrive-bd-write:",
                (
                    "_Staging_Incoming/"
                    "APP/APP145.pdf"
                ),
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "Non-missing rclone errors "
                "must remain fatal."
            )


def test_no_overwrite():
    with tempfile.NamedTemporaryFile(
        suffix=".pdf",
        delete=False,
    ) as temp:
        path = Path(temp.name)
        temp.write(b"%PDF-test")

    try:
        with patch.object(
            writer,
            "remote_file_exists",
            return_value=True,
        ):
            try:
                writer.upload_and_verify(
                    path,
                    remote=(
                        "gdrive-bd-write:"
                    ),
                    destination=(
                        "_Staging_Incoming/"
                        "APP/APP145.pdf"
                    ),
                )
            except FileExistsError:
                pass
            else:
                raise AssertionError(
                    "Existing remote file "
                    "must not be overwritten."
                )
    finally:
        path.unlink(
            missing_ok=True
        )


def test_roundtrip_verification():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        local = root / "source.pdf"
        local.write_bytes(
            b"%PDF-roundtrip"
        )

        def fake_run(args):
            if (
                args[0]
                == "lsjson"
            ):
                return "[]"

            if (
                args[0]
                == "copyto"
                and str(
                    args[1]
                ).startswith(
                    "gdrive-bd-write:"
                )
            ):
                destination = Path(
                    args[2]
                )

                destination.write_bytes(
                    local.read_bytes()
                )

                return ""

            return ""

        with patch.object(
            writer,
            "run_rclone",
            side_effect=fake_run,
        ):
            result = (
                writer.upload_and_verify(
                    local,
                    remote=(
                        "gdrive-bd-write:"
                    ),
                    destination=(
                        "_Staging_Incoming/"
                        "APP/APP145.pdf"
                    ),
                )
            )

        assert (
            result["verified"]
            is True
        )

        assert (
            result[
                "local_sha256"
            ]
            == result[
                "roundtrip_sha256"
            ]
        )


def test_writer_has_no_baseline_mutation():
    text = SCRIPT.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "replace_baseline",
        "update_baseline",
        "baseline_updated = True",
        "Current/APP/",
        "gdrive-out:",
    )

    for token in forbidden:
        assert token not in text, (
            "Staging writer contains "
            f"forbidden token: {token}"
        )


def main():
    test_registry_writer_contract()
    test_writer_path_guard()
    test_remote_exists_parser()
    test_missing_parent_means_absent()
    test_non_missing_rclone_error_still_fails()
    test_no_overwrite()
    test_roundtrip_verification()
    test_writer_has_no_baseline_mutation()

    print(
        "PNAP staging writer v1: PASS"
    )


if __name__ == "__main__":
    main()
