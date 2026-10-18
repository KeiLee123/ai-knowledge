#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
DB_USER = "ai_knowledge"
DB_NAME = "ai_knowledge"

TMP_ROOT = Path("/opt/ai-knowledge/tmp")

CLASSIFY_CMD = "/usr/local/bin/classify-knowledge"
INGEST_CMD = "/usr/local/bin/ingest-knowledge"

MIN_CONFIDENCE = 0.80


def run(cmd, **kwargs):
    return subprocess.run(
        cmd,
        text=True,
        **kwargs
    )


def sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b""
        ):
            h.update(block)

    return h.hexdigest()


def psql(sql, variables=None):
    cmd = [
        "docker", "exec", "-i",
        DB_CONTAINER,
        "psql",
        "-U", DB_USER,
        "-d", DB_NAME,
        "-At",
        "-v", "ON_ERROR_STOP=1"
    ]

    for key, value in (variables or {}).items():
        cmd += ["-v", f"{key}={value}"]

    result = run(
        cmd,
        input=sql,
        capture_output=True
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)

    return result.stdout.strip()


def find_document_by_checksum(checksum):
    value = psql(
        """
        SELECT id
        FROM documents
        WHERE checksum_sha256 = :'checksum'
        ORDER BY id DESC
        LIMIT 1;
        """,
        {
            "checksum": checksum
        }
    )

    return int(value) if value else None


def update_metadata(
    document_id,
    classification,
    remote_path,
    file_name,
    source_file_id,
    source_url,
    modified_time
):
    metadata = dict(
        classification.get("metadata", {})
    )

    metadata.update({
        "authority_code":
            classification.get("authority_code"),
        "taxonomy_version":
            classification.get("taxonomy_version"),
        "classification_confidence":
            classification.get("confidence"),
        "classification_evidence":
            classification.get("evidence_summary"),
        "source_filename":
            file_name,
        "source_path":
            remote_path,
        "drive_modified_time":
            modified_time,
        "synthetic":
            False
    })

    metadata_json = json.dumps(
        metadata,
        ensure_ascii=False
    )

    psql(
        """
        UPDATE documents
        SET
            source_type = 'google-drive',
            source_file_id =
                NULLIF(:'source_file_id',''),
            source_url =
                NULLIF(:'source_url',''),
            metadata =
                COALESCE(metadata, '{}'::jsonb)
                ||
                :'metadata_json'::jsonb,
            updated_at = NOW()
        WHERE id = :document_id;
        """,
        {
            "document_id": document_id,
            "source_file_id": source_file_id or "",
            "source_url": source_url or "",
            "metadata_json": metadata_json
        }
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Classify and ingest a Google Drive "
            "knowledge document."
        )
    )

    parser.add_argument(
        "remote_path",
        help=(
            "Path relative to gdrive root, "
            "e.g. 00_Inbox/APP-001.pdf"
        )
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt."
    )

    args = parser.parse_args()

    remote_path = args.remote_path.strip().lstrip("/")

    if ".." in PurePosixPath(remote_path).parts:
        raise SystemExit("Invalid remote path.")

    remote_spec = f"gdrive:{remote_path}"

    print("=" * 72)
    print("GOOGLE DRIVE AUTO INGEST")
    print("=" * 72)
    print()
    print("Source:", remote_spec)
    print()

    # --------------------------------------------------------
    # Read Drive metadata
    # --------------------------------------------------------

    stat = run(
        [
            "rclone",
            "lsjson",
            remote_spec,
            "--stat"
        ],
        capture_output=True
    )

    if stat.returncode != 0:
        print(stat.stderr, file=sys.stderr)
        raise SystemExit(stat.returncode)

    info = json.loads(stat.stdout)

    if info.get("IsDir"):
        raise SystemExit(
            "The supplied path is a directory."
        )

    file_name = (
        info.get("Name")
        or PurePosixPath(remote_path).name
    )

    source_file_id = info.get("ID", "")
    modified_time = info.get("ModTime", "")

    source_url = (
        f"https://drive.google.com/file/d/"
        f"{source_file_id}/view"
        if source_file_id
        else ""
    )

    TMP_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Temporary download
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="ingest-gdrive-",
        dir=TMP_ROOT
    ) as temp_dir:

        local_path = Path(temp_dir) / file_name

        print("Downloading temporary copy...")

        copy_result = run(
            [
                "rclone",
                "copyto",
                remote_spec,
                str(local_path)
            ]
        )

        if copy_result.returncode != 0:
            raise SystemExit(
                copy_result.returncode
            )

        checksum = sha256_file(local_path)

        print("SHA256:", checksum)
        print()

        # ----------------------------------------------------
        # AI classification
        # ----------------------------------------------------

        print("Classifying document...")
        print()

        classify_result = run(
            [
                CLASSIFY_CMD,
                str(local_path)
            ],
            capture_output=True
        )

        if classify_result.returncode != 0:
            print(
                classify_result.stderr,
                file=sys.stderr
            )
            raise SystemExit(
                classify_result.returncode
            )

        classification = json.loads(
            classify_result.stdout
        )

        print(
            json.dumps(
                classification,
                indent=2,
                ensure_ascii=False
            )
        )

        print()

        # ----------------------------------------------------
        # Safety gates
        # ----------------------------------------------------

        if not classification.get(
            "taxonomy_valid",
            False
        ):
            raise SystemExit(
                "STOP: taxonomy validation failed."
            )

        confidence = float(
            classification.get(
                "confidence",
                0
            )
        )

        if confidence < MIN_CONFIDENCE:
            raise SystemExit(
                f"STOP: confidence {confidence:.2f} "
                f"is below {MIN_CONFIDENCE:.2f}."
            )

        # ----------------------------------------------------
        # Duplicate detection
        # ----------------------------------------------------

        existing_id = find_document_by_checksum(
            checksum
        )

        if existing_id:
            print(
                f"Exact file already exists as "
                f"Document ID {existing_id}."
            )

            print(
                "No duplicate chunks or embeddings "
                "will be created."
            )

        # ----------------------------------------------------
        # Confirmation
        # ----------------------------------------------------

        print()
        print("-" * 72)

        print(
            "Title:",
            classification.get(
                "proposed_title",
                ""
            )
        )

        print(
            "Authority:",
            classification.get(
                "authority_code",
                ""
            ),
            "-",
            classification.get(
                "authority_name",
                ""
            )
        )

        print(
            "Domain:",
            classification.get(
                "domain",
                ""
            )
        )

        print(
            "Topic:",
            classification.get(
                "topic",
                ""
            )
        )

        print(
            "Document type:",
            classification.get(
                "document_type",
                ""
            )
        )

        print(
            "Confidence:",
            confidence
        )

        print("-" * 72)

        if not args.yes:

            answer = input(
                "\nProceed with ingestion? [y/N]: "
            ).strip().lower()

            if answer not in {"y", "yes"}:
                print("Cancelled.")
                return

        # ----------------------------------------------------
        # Ingest new document
        # ----------------------------------------------------

        if existing_id:
            document_id = existing_id

        else:

            command = [
                INGEST_CMD,
                str(local_path),

                "--title",
                classification[
                    "proposed_title"
                ],

                "--domain",
                classification[
                    "domain"
                ],

                "--topic",
                classification[
                    "topic"
                ],

                "--document-type",
                classification[
                    "document_type"
                ],

                "--authority",
                classification[
                    "authority_name"
                ],

                "--jurisdiction",
                classification.get(
                    "jurisdiction",
                    "HK"
                )
            ]

            ingest_result = run(command)

            if ingest_result.returncode != 0:
                raise SystemExit(
                    ingest_result.returncode
                )

            document_id = (
                find_document_by_checksum(
                    checksum
                )
            )

            if not document_id:
                raise SystemExit(
                    "Ingestion completed but "
                    "document could not be resolved "
                    "by checksum."
                )

        # ----------------------------------------------------
        # Add classification + Drive provenance
        # ----------------------------------------------------

        update_metadata(
            document_id=document_id,
            classification=classification,
            remote_path=remote_path,
            file_name=file_name,
            source_file_id=source_file_id,
            source_url=source_url,
            modified_time=modified_time
        )

        print()
        print("=" * 72)
        print("INGEST COMPLETE")
        print("=" * 72)

        print(
            "Document ID:",
            document_id
        )

        print(
            "Google Drive ID:",
            source_file_id
        )

        print(
            "Taxonomy:",
            classification.get(
                "taxonomy_version"
            )
        )

        print(
            "Topic:",
            classification.get(
                "topic"
            )
        )

        print(
            "Temporary copy: deleted automatically"
        )


if __name__ == "__main__":
    main()
