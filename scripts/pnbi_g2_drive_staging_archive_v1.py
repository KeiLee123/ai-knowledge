#!/usr/bin/env python3
"""G2 single-PNBI immutable Drive Staging archive + full-byte SHA256 readback.

Owner-approved candidate archive only. No Current, DB, registry, embeddings, or Production.
Needs existing rclone remote gdrive-bd-write:; never reads or prints credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import build_opener

import pnbi_g1_pdf_probe_v1 as g1
from pnbi_g0_readonly_probe_v1 import NoRedirect

REMOTE = "gdrive-bd-write:"
ROOT_ID = "1kuV9-bFx5Yc37WbwxDGXkvVCK86h9T81"
PNBI_FOLDER_ID = "10Lwio560k4gXdjFFPg5Le8NB2mTrNYCV"
ROOT_PATH = REMOTE + "_Staging_Incoming"
PNBI_PATH = ROOT_PATH + "/PNBI"
# Captured from 10/10 owner VPS independent G1 passes (normal English PDFs).
EXPECTED = {
    1: ("bfca7fa908fc3bab8835ebc69f7ec33917bfe18440c37d31de153a038d77cf56", 21971, 4),
    2: ("b1cfccd74c13301702a1f99321a36a74be96110052480b1158df749d527d8938", 50077, 3),
    3: ("c092c44bbb7f5c1b6f3583d567e2734e1cc08975f4017cb2506b35c71ca4d8b7", 99733, 3),
    4: ("bb85a02897080f68f4177f1df20386305a709dc542afe1a36820d6dcfdb297e0", 10664, 1),
    5: ("39ba31027374ff85881430baeb5bcdc4b9d327f40300736df6f6bf53c04e22dd", 8532, 1),
    6: ("aa6ef369ca34d5fb22c3fbfc878941e9a57317655e671d58975a3a0778e9935a", 87735, 2),
    7: ("a5631dbd133fde90dfc63024a1947760d177775ce0d381f8b933df224c32c663", 1941407, 73),
    8: ("1d15656f3e99a48a83eca75e83c6712cf606953cb9b4a6407bfe002df0fa9b9a", 365130, 36),
    9: ("3b4b4cb61b624c91e096f941636b6a8bb81ecc0227c6deae9133014000be271d", 404513, 6),
    10: ("9990b7d6673d7f975faf6829a7e5d137070746a18415b19373ad014adaba1e57", 1206920, 63),
}


def run(*args, timeout=120):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("RCLONE_OR_COMMAND_FAILED_HOLD: " + str(error)) from error


def list_json(path, *, dirs=False, files=False):
    args = ["rclone", "lsjson", path]
    if dirs:
        args.append("--dirs-only")
    if files:
        args.append("--files-only")
    try:
        result = json.loads(run(*args, timeout=60))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("RCLONE_LIST_JSON_HOLD") from error
    if not isinstance(result, list):
        raise ValueError("RCLONE_LIST_NOT_ARRAY_HOLD")
    return result


def one_named(items, name, expected_id=None):
    matched = [x for x in items if x.get("Name") == name and x.get("IsDir") is True]
    if len(matched) != 1:
        raise ValueError("FOLDER_MISSING_OR_DUPLICATE_HOLD: " + name)
    if expected_id is not None and matched[0].get("ID") != expected_id:
        raise ValueError("FOLDER_ID_MISMATCH_HOLD: " + name)
    return matched[0]


def check_folder_identity():
    remotes = run("rclone", "listremotes", timeout=30).decode("utf-8", errors="strict").splitlines()
    if REMOTE not in remotes:
        raise ValueError("EXPECTED_WRITE_REMOTE_NOT_CONFIGURED_HOLD")
    one_named(list_json(REMOTE, dirs=True), "_Staging_Incoming", ROOT_ID)
    one_named(list_json(ROOT_PATH, dirs=True), "PNBI", PNBI_FOLDER_ID)


def expected_filename(number):
    return f"PNBI{number:03}_{EXPECTED[number][0]}.pdf"


def check_existing(items, number):
    """Reject duplicate and a different SHA-addressed version for same PNBI."""
    prefix = f"PNBI{number:03}_"
    present = [x for x in items if x.get("Name", "").startswith(prefix)]
    if not present:
        return False
    if len(present) != 1 or present[0].get("Name") != expected_filename(number):
        raise ValueError("EXISTING_SOURCE_VARIANT_OR_DUPLICATE_HOLD")
    if present[0].get("Size") != EXPECTED[number][1] or not present[0].get("ID"):
        raise ValueError("EXISTING_REMOTE_METADATA_HOLD")
    return True


def verify_remote(number):
    matches = [x for x in list_json(PNBI_PATH, files=True)
               if x.get("Name") == expected_filename(number)]
    if len(matches) != 1:
        raise ValueError("REMOTE_FILE_MISSING_OR_DUPLICATE_HOLD")
    info = matches[0]
    if info.get("Size") != EXPECTED[number][1] or not info.get("ID"):
        raise ValueError("REMOTE_FILE_SIZE_OR_ID_HOLD")
    remote_file = PNBI_PATH + "/" + expected_filename(number)
    # Independently read every byte back from Google Drive; no checksum metadata shortcut.
    readback = run("rclone", "cat", remote_file, timeout=120)
    if len(readback) != EXPECTED[number][1]:
        raise ValueError("REMOTE_READBACK_SIZE_HOLD")
    if hashlib.sha256(readback).hexdigest() != EXPECTED[number][0]:
        raise ValueError("REMOTE_READBACK_SHA256_HOLD")
    return info["ID"]


def fetch_exact_source(number):
    opener = build_opener(NoRedirect)
    linked = g1.fetch_official_index(opener, source="detail")  # Live official index each time.
    official_url = linked[number]
    expected_path = f"/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/PNBI{number:03}.pdf"
    if official_url != "https://www.bd.gov.hk" + expected_path:
        raise ValueError("SOURCE_LINK_CHANGED_HOLD")
    data = g1.fetch_pdf(opener, official_url)
    expected_sha, expected_bytes, _ = EXPECTED[number]
    if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("SOURCE_BYTES_OR_SHA_CHANGED_HOLD")
    return data, official_url


def archive_one(number):
    if number not in EXPECTED:
        raise ValueError("OUT_OF_APPROVED_SCOPE_HOLD")
    check_folder_identity()  # Must match both verified Drive IDs before source/network write.
    files = list_json(PNBI_PATH, files=True)
    already = check_existing(files, number)

    data, url = fetch_exact_source(number)
    with tempfile.TemporaryDirectory(prefix="jason-pnbi-g2-") as temp:
        local = Path(temp) / expected_filename(number)
        with local.open("xb") as output:
            output.write(data)
        if not already:
            # copyto is non-deleting; --immutable prevents changing any existing object.
            run("rclone", "copyto", "--immutable", "--retries", "1",
                "--low-level-retries", "1", str(local),
                PNBI_PATH + "/" + expected_filename(number), timeout=180)
    file_id = verify_remote(number)
    return {
        "number": number, "sha256": EXPECTED[number][0], "bytes": EXPECTED[number][1],
        "pages_g1": EXPECTED[number][2], "url": url,
        "file_id": file_id, "folder_id": PNBI_FOLDER_ID,
        "outcome": "EXISTING_VERIFIED" if already else "NEW_UPLOAD_VERIFIED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnbi", type=int, required=True, choices=range(1, 11))
    args = parser.parse_args(argv)
    os.umask(0o077)
    result = archive_one(args.pnbi)
    print("G2_PNBI_{number:02d}_DRIVE_STAGING_IMMUTABLE_READBACK_PASS "
          "| OUTCOME={outcome} | SHA256={sha256} | BYTES={bytes} | G1_PAGES={pages_g1} "
          "| DRIVE_FILE_ID={file_id} | PARENT_ID={folder_id} | SOURCE={url}".format(**result))
    print("G2_CANDIDATE_ARCHIVE_ONLY; REGISTRY_NONE; DB_NONE; CURRENT_NONE; PRODUCTION_NONE")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("G2_HOLD: " + str(error), file=sys.stderr)
        sys.exit(1)
