#!/usr/bin/env python3

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile

from datetime import datetime, timezone
from pathlib import Path

import yaml


REGISTRY = Path(
    "/opt/ai-knowledge/legislation_registry.yaml"
)

MASTER_URL = (
    "https://resource.data.one.gov.hk/doj/data/"
    "hkel_list_c_all_en.json"
)

WATCH_ROOT = Path(
    "/opt/ai-knowledge/watch/legislation"
)

CURRENT_ROOT = WATCH_ROOT / "current"

MANIFEST_FILE = WATCH_ROOT / "baseline_manifest.json"


def fetch_bytes(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Jason-AI-Knowledge-Law-Watch/1.0"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=120
    ) as response:
        return response.read()


def fetch_json(url):
    return json.loads(
        fetch_bytes(url).decode("utf-8")
    )


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b""
        ):
            h.update(block)

    return h.hexdigest()


def load_registry():
    with REGISTRY.open(
        "r",
        encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def get_current_version(chapter_item):

    versions = chapter_item.get(
        "Version",
        []
    )

    if isinstance(versions, dict):
        versions = [versions]

    for version in versions:

        vd = version.get(
            "VersionDate",
            {}
        )

        if vd.get("isCurrentVersion") is True:
            return version

    return None


def build_chapter_index(master):

    result = {}

    chapters = master.get(
        "Chapter",
        []
    )

    for item in chapters:

        cap = str(
            item.get(
                "CapNo",
                ""
            )
        ).strip()

        if cap:
            result[cap] = item

    return result


def safe_extract_member(
    zip_path,
    file_location,
    file_name,
    output_path
):

    expected = (
        f"{file_location}/{file_name}"
        if file_location
        else file_name
    )

    expected = expected.replace("\\", "/")

    with zipfile.ZipFile(
        zip_path,
        "r"
    ) as zf:

        names = {
            name.replace("\\", "/"): name
            for name in zf.namelist()
        }

        actual_name = names.get(expected)

        if not actual_name:

            # Fallback:
            # locate exact filename anywhere in archive.
            matches = [
                original
                for normalized, original
                in names.items()
                if Path(normalized).name == file_name
            ]

            if len(matches) == 1:
                actual_name = matches[0]

            elif not matches:
                raise FileNotFoundError(
                    f"{expected} not found in ZIP"
                )

            else:
                raise RuntimeError(
                    f"Multiple matches for {file_name}"
                )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with zf.open(
            actual_name
        ) as src, output_path.open(
            "wb"
        ) as dst:

            shutil.copyfileobj(
                src,
                dst
            )


def bootstrap():

    registry = load_registry()

    laws = registry.get(
        "legislation",
        {}
    )

    enabled = {
        key: item
        for key, item in laws.items()
        if item.get("enabled", False)
    }

    print("=" * 72)
    print("HK LEGISLATION WATCH — BOOTSTRAP")
    print("=" * 72)
    print()
    print(
        "Enabled legislation:",
        len(enabled)
    )
    print()

    print(
        "Downloading HKeL current manifest..."
    )

    master = fetch_json(
        MASTER_URL
    )

    chapter_index = build_chapter_index(
        master
    )

    CURRENT_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    baseline = {
        "registry_version":
            registry.get(
                "legislation_registry_version"
            ),

        "source":
            "Hong Kong e-Legislation",

        "source_manifest":
            MASTER_URL,

        "manifest_updated":
            master.get("UpdatedDateTime"),

        "bootstrap_time":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "legislation": {}
    }

    failures = []

    # One run may reference the same large ZIP many times.
    # Cache each ZIP only during this bootstrap.
    with tempfile.TemporaryDirectory(
        prefix="hkel-bootstrap-"
    ) as temp_dir:

        temp_dir = Path(temp_dir)

        zip_cache = {}

        for registry_key, config in enabled.items():

            chapter = str(
                config["chapter"]
            )

            print("-" * 72)
            print(
                registry_key,
                f"(Cap.{chapter})"
            )

            chapter_item = (
                chapter_index.get(chapter)
            )

            if not chapter_item:

                print(
                    "ERROR: chapter not found "
                    "in HKeL manifest."
                )

                failures.append(
                    registry_key
                )

                continue

            version = get_current_version(
                chapter_item
            )

            if not version:

                print(
                    "ERROR: current version "
                    "not found."
                )

                failures.append(
                    registry_key
                )

                continue

            version_date_info = (
                version.get(
                    "VersionDate",
                    {}
                )
            )

            version_date = (
                version_date_info.get(
                    "value"
                )
            )

            status_category = (
                version_date_info.get(
                    "statusCategory"
                )
            )

            status_code = (
                version_date_info.get(
                    "statusCode"
                )
            )

            resource_url = version.get(
                "DataResourceUrl"
            )

            file_location = version.get(
                "FileLocation"
            )

            file_name = version.get(
                "FileName"
            )

            web_url = version.get(
                "Web"
            )

            print(
                "Title:",
                chapter_item.get(
                    "ChapterTitleEnglish"
                )
            )

            print(
                "Version:",
                version_date
            )

            print(
                "Status:",
                status_category
            )

            if not (
                resource_url
                and file_name
            ):
                print(
                    "ERROR: incomplete HKeL "
                    "resource metadata."
                )

                failures.append(
                    registry_key
                )

                continue

            if resource_url not in zip_cache:

                zip_name = (
                    hashlib.sha256(
                        resource_url.encode(
                            "utf-8"
                        )
                    ).hexdigest()[:16]
                    + ".zip"
                )

                zip_path = (
                    temp_dir / zip_name
                )

                print(
                    "Downloading data package..."
                )

                zip_path.write_bytes(
                    fetch_bytes(
                        resource_url
                    )
                )

                zip_cache[
                    resource_url
                ] = zip_path

            else:

                zip_path = zip_cache[
                    resource_url
                ]

                print(
                    "Using cached data package."
                )

            law_dir = (
                CURRENT_ROOT
                / registry_key
                / "machine"
            )

            output_path = (
                law_dir
                / file_name
            )

            try:

                safe_extract_member(
                    zip_path,
                    file_location,
                    file_name,
                    output_path
                )

            except Exception as exc:

                print(
                    "ERROR extracting:",
                    exc
                )

                failures.append(
                    registry_key
                )

                continue

            checksum = sha256_file(
                output_path
            )

            # Stable alias for applications.
            current_alias = (
                law_dir / "current.xml"
            )

            shutil.copy2(
                output_path,
                current_alias
            )

            baseline[
                "legislation"
            ][registry_key] = {

                "chapter":
                    chapter,

                "title":
                    chapter_item.get(
                        "ChapterTitleEnglish"
                    ),

                "legislation_type":
                    chapter_item.get(
                        "LegislationType"
                    ),

                "principal_ordinance":
                    chapter_item.get(
                        "PrincipalOrdinance"
                    ),

                "version_date":
                    version_date,

                "status_category":
                    status_category,

                "status_code":
                    status_code,

                "file_name":
                    file_name,

                "file_location":
                    file_location,

                "data_resource_url":
                    resource_url,

                "web_url":
                    web_url,

                "sha256":
                    checksum,

                "local_file":
                    str(
                        output_path
                    ),

                "current_alias":
                    str(
                        current_alias
                    )
            }

            print(
                "Saved:",
                output_path
            )

            print(
                "SHA256:",
                checksum
            )

    WATCH_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_manifest = (
        MANIFEST_FILE.with_suffix(
            ".json.tmp"
        )
    )

    temp_manifest.write_text(
        json.dumps(
            baseline,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temp_manifest.replace(
        MANIFEST_FILE
    )

    print()
    print("=" * 72)
    print("BOOTSTRAP COMPLETE")
    print("=" * 72)

    print(
        "Downloaded:",
        len(
            baseline["legislation"]
        )
    )

    print(
        "Failures:",
        len(failures)
    )

    print(
        "Manifest:",
        MANIFEST_FILE
    )

    if failures:

        print(
            "Failed entries:",
            ", ".join(failures)
        )

        raise SystemExit(2)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Hong Kong legislation "
            "version watcher."
        )
    )

    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help=(
            "Download current HKeL versions "
            "and create baseline."
        )
    )

    args = parser.parse_args()

    if args.bootstrap:
        bootstrap()
        return

    print(
        "Watch mode will be added after "
        "the bootstrap baseline is verified."
    )


if __name__ == "__main__":
    main()
