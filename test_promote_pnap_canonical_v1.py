#!/usr/bin/env python3

import json
import tempfile

from pathlib import Path
from unittest.mock import patch

import promote_pnap_canonical_v1 as promotion


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "source_registry_v1.yaml"
SCRIPT = ROOT / "promote_pnap_canonical_v1.py"


def test_registry_contract():
    (
        _registry,
        config,
        promote,
    ) = promotion.load_source(
        REGISTRY,
        "BD_PNAP_APP145",
    )

    assert config["document_code"] == "APP-145"
    assert promote["controller_environment"] == "staging"
    assert promote["remote"] == "gdrive-bd-write:"
    assert (
        promote["source"]
        == "_Staging_Incoming/APP/APP145.pdf"
    )
    assert (
        promote["destination"]
        == "Current/APP/APP145.pdf"
    )
    assert promote["allow_overwrite"] is False
    assert promote["retain_staging_source"] is True
    assert promote["update_baseline"] is False
    assert promote["trigger_ingestion"] is False


def test_config_guards():
    valid = {
        "enabled": True,
        "controller_environment": "staging",
        "remote": "gdrive-bd-write:",
        "source": "_Staging_Incoming/APP/APP145.pdf",
        "destination": "Current/APP/APP145.pdf",
        "allow_overwrite": False,
        "retain_staging_source": True,
        "update_baseline": False,
        "trigger_ingestion": False,
    }

    drive_writer = {
        "destination": "_Staging_Incoming/APP/APP145.pdf",
    }

    promotion.validate_promotion_config(
        "X",
        valid,
        drive_writer,
    )

    bad_remote = dict(valid)
    bad_remote["remote"] = "gdrive:"
    try:
        promotion.validate_promotion_config(
            "X",
            bad_remote,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Unexpected remote must fail.")

    bad_source = dict(valid)
    bad_source["source"] = "Current/APP/APP145.pdf"
    try:
        promotion.validate_promotion_config(
            "X",
            bad_source,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Source prefix guard failed.")

    bad_destination = dict(valid)
    bad_destination["destination"] = "_Staging_Incoming/APP/APP145.pdf"
    try:
        promotion.validate_promotion_config(
            "X",
            bad_destination,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Destination prefix guard failed.")

    bad_overwrite = dict(valid)
    bad_overwrite["allow_overwrite"] = True
    try:
        promotion.validate_promotion_config(
            "X",
            bad_overwrite,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Overwrite must remain disabled.")

    bad_retain = dict(valid)
    bad_retain["retain_staging_source"] = False
    try:
        promotion.validate_promotion_config(
            "X",
            bad_retain,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Staging source must be retained.")

    bad_baseline = dict(valid)
    bad_baseline["update_baseline"] = True
    try:
        promotion.validate_promotion_config(
            "X",
            bad_baseline,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Baseline update must remain disabled.")

    bad_ingest = dict(valid)
    bad_ingest["trigger_ingestion"] = True
    try:
        promotion.validate_promotion_config(
            "X",
            bad_ingest,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Ingestion trigger must remain disabled.")


def test_source_must_match_staging_writer():
    promote = {
        "enabled": True,
        "controller_environment": "staging",
        "remote": "gdrive-bd-write:",
        "source": "_Staging_Incoming/APP/OTHER.pdf",
        "destination": "Current/APP/APP145.pdf",
        "allow_overwrite": False,
        "retain_staging_source": True,
        "update_baseline": False,
        "trigger_ingestion": False,
    }

    drive_writer = {
        "destination": "_Staging_Incoming/APP/APP145.pdf",
    }

    try:
        promotion.validate_promotion_config(
            "X",
            promote,
            drive_writer,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Promotion source must match the frozen writer destination."
        )


def test_remote_file_info():
    listing = json.dumps(
        [
            {
                "Name": "APP145.pdf",
                "Size": 54814,
                "MimeType": "application/pdf",
                "IsDir": False,
            }
        ]
    )

    with patch.object(
        promotion,
        "run_rclone",
        return_value=listing,
    ):
        info = promotion.remote_file_info(
            "gdrive-bd-write:",
            "_Staging_Incoming/APP/APP145.pdf",
        )

    assert info["Name"] == "APP145.pdf"
    assert info["Size"] == 54814


def test_existing_destination_stops():
    with patch.object(
        promotion,
        "remote_directory_exists",
        return_value=True,
    ), patch.object(
        promotion,
        "remote_file_info",
        side_effect=[
            {
                "Name": "APP145.pdf",
                "Size": 54814,
                "MimeType": "application/pdf",
                "IsDir": False,
            },
            {
                "Name": "APP145.pdf",
                "Size": 54814,
                "MimeType": "application/pdf",
                "IsDir": False,
            },
        ],
    ):
        try:
            promotion.validate_remote_state(
                remote="gdrive-bd-write:",
                source="_Staging_Incoming/APP/APP145.pdf",
                destination="Current/APP/APP145.pdf",
                expected_size=54814,
            )
        except FileExistsError:
            pass
        else:
            raise AssertionError(
                "Existing canonical destination must stop promotion."
            )


def test_execute_roundtrip():
    staged_bytes = b"%PDF-canonical-promotion-test"

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        local = root / "staged.pdf"
        local.write_bytes(staged_bytes)

        def fake_run(args, **_kwargs):
            if args[0] != "copyto":
                return ""

            source = str(args[1])
            destination = str(args[2])

            if source.startswith("gdrive-bd-write:"):
                Path(destination).write_bytes(staged_bytes)
            elif destination.startswith("gdrive-bd-write:"):
                pass

            return ""

        with patch.object(
            promotion,
            "run_rclone",
            side_effect=fake_run,
        ):
            result = promotion.promote_and_verify(
                local,
                remote="gdrive-bd-write:",
                destination="Current/APP/APP145.pdf",
            )

        assert result["verified"] is True
        assert (
            result["local_sha256"]
            == result["roundtrip_sha256"]
        )


def test_no_destructive_or_downstream_behavior():
    text = SCRIPT.read_text(encoding="utf-8")

    forbidden = (
        "deletefile",
        " rmdir",
        " purge",
        " moveto",
        "baseline.write_json_atomic",
        "baseline.initialize_baseline",
        "replace_baseline",
        "ingest_document",
        "orchestrate_document",
        "gdrive-out:",
        "canonical_url",
        "urllib.request",
        "write_pnap_staging_v1",
    )

    for token in forbidden:
        assert token not in text, (
            "Canonical promotion contains forbidden token: "
            f"{token}"
        )


def main():
    test_registry_contract()
    test_config_guards()
    test_source_must_match_staging_writer()
    test_remote_file_info()
    test_existing_destination_stops()
    test_execute_roundtrip()
    test_no_destructive_or_downstream_behavior()

    print("Canonical Promotion v1: PASS")


if __name__ == "__main__":
    main()
