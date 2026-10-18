#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from ingest_manifest_v2 import (
    DEFAULT_DB_CONTAINER,
    read_existing_document,
)


DRIVE_ORCHESTRATOR_VERSION = "phase-d5-3a"
TMP_ROOT = Path("/opt/ai-knowledge/tmp")
CLASSIFY_CMD = "/usr/local/bin/classify-knowledge"
MIN_CONFIDENCE = 0.80


def run(
    command: list[str],
    *,
    capture_output: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    print(
        "+",
        " ".join(
            str(part)
            for part in command
        ),
        flush=True,
    )

    result = subprocess.run(
        command,
        text=True,
        capture_output=capture_output,
        input=input_text,
    )

    if result.returncode != 0:
        if capture_output:
            if result.stdout:
                print(
                    result.stdout,
                    file=sys.stderr,
                )

            if result.stderr:
                print(
                    result.stderr,
                    file=sys.stderr,
                )

        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + " ".join(
                str(part)
                for part in command
            )
        )

    return result


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def script_path(name: str) -> Path:
    path = (
        Path(__file__)
        .resolve()
        .parent
        / name
    )

    if not path.is_file():
        raise RuntimeError(
            f"Required script missing: {path}"
        )

    return path


def write_state(
    path: Path | None,
    state: dict,
) -> None:
    if path is None:
        return

    path.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def validate_remote_path(
    value: str,
) -> str:
    remote_path = (
        value.strip()
        .lstrip("/")
    )

    if not remote_path:
        raise RuntimeError(
            "Remote path is empty"
        )

    parts = PurePosixPath(
        remote_path
    ).parts

    if ".." in parts:
        raise RuntimeError(
            "Invalid remote path"
        )

    return remote_path


def classify(
    local_path: Path,
) -> dict:
    result = run(
        [
            CLASSIFY_CMD,
            str(local_path),
        ],
        capture_output=True,
    )

    try:
        classification = json.loads(
            result.stdout
        )

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Classifier did not return "
            "valid JSON"
        ) from exc

    if not classification.get(
        "taxonomy_valid",
        False,
    ):
        raise RuntimeError(
            "Taxonomy validation failed: "
            + json.dumps(
                classification.get(
                    "validation_errors",
                    [],
                ),
                ensure_ascii=False,
            )
        )

    confidence = float(
        classification.get(
            "confidence",
            0,
        )
        or 0
    )

    if confidence < MIN_CONFIDENCE:
        raise RuntimeError(
            f"Classification confidence "
            f"{confidence:.2f} is below "
            f"{MIN_CONFIDENCE:.2f}"
        )

    required = [
        "proposed_title",
        "domain",
        "topic",
        "document_type",
    ]

    missing = [
        key
        for key in required
        if not str(
            classification.get(
                key,
                ""
            )
        ).strip()
    ]

    if missing:
        raise RuntimeError(
            "Classifier missing required "
            "fields: "
            + ", ".join(
                missing
            )
        )

    return classification


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in Google Drive entrypoint for "
            "selected-document multimodal v2. "
            "Default mode routes only; --prepare "
            "may run OCR/vision/embeddings but "
            "never writes to the database."
        )
    )

    parser.add_argument(
        "remote_path",
        help=(
            "Path relative to gdrive root"
        ),
    )

    parser.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "Run the v2 prepare-only path "
            "when routing selects multimodal-v2. "
            "No database write is allowed."
        ),
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the confirmation prompt before "
            "prepare-only OCR/vision work"
        ),
    )

    parser.add_argument(
        "--language",
        default="en",
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    parser.add_argument(
        "--workdir",
        help=(
            "Optional persistent orchestrator "
            "workdir. Also stores "
            "gdrive-v2-state.json."
        ),
    )

    args = parser.parse_args()

    remote_path = validate_remote_path(
        args.remote_path
    )

    remote_spec = (
        f"gdrive:{remote_path}"
    )

    persistent_workdir = None
    state_path = None

    if args.workdir:
        persistent_workdir = (
            Path(args.workdir)
            .expanduser()
            .resolve()
        )

        persistent_workdir.mkdir(
            parents=True,
            exist_ok=True,
        )

        state_path = (
            persistent_workdir
            / "gdrive-v2-state.json"
        )

    state = {
        "drive_orchestrator_version":
            DRIVE_ORCHESTRATOR_VERSION,
        "remote_path":
            remote_path,
        "remote_spec":
            remote_spec,
        "mode":
            (
                "prepare"
                if args.prepare
                else "route-only"
            ),
        "stages": [],
        "database_write_performed":
            False,
    }

    write_state(
        state_path,
        state,
    )

    try:
        print("=" * 72)
        print(
            "GOOGLE DRIVE V2 OPT-IN"
        )
        print("=" * 72)
        print(
            "Source:",
            remote_spec,
        )
        print(
            "Mode:",
            state["mode"],
        )
        print()

        stat_result = run(
            [
                "rclone",
                "lsjson",
                remote_spec,
                "--stat",
            ],
            capture_output=True,
        )

        try:
            info = json.loads(
                stat_result.stdout
            )

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "rclone lsjson did not "
                "return valid JSON"
            ) from exc

        if info.get("IsDir"):
            raise RuntimeError(
                "Remote path is a directory"
            )

        file_name = (
            info.get("Name")
            or PurePosixPath(
                remote_path
            ).name
        )

        source_file_id = (
            info.get("ID")
            or ""
        )

        modified_time = (
            info.get("ModTime")
            or ""
        )

        source_url = (
            (
                "https://drive.google.com/"
                f"file/d/{source_file_id}/view"
            )
            if source_file_id
            else ""
        )

        state["drive"] = {
            "file_name":
                file_name,
            "source_file_id":
                source_file_id,
            "modified_time":
                modified_time,
            "source_url":
                source_url,
        }

        state["stages"].append(
            "drive-stat"
        )

        write_state(
            state_path,
            state,
        )

        TMP_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.TemporaryDirectory(
            prefix="gdrive-v2-optin-",
            dir=TMP_ROOT,
        ) as temp_dir:
            local_path = (
                Path(temp_dir)
                / file_name
            )

            run([
                "rclone",
                "copyto",
                remote_spec,
                str(local_path),
            ])

            state["stages"].append(
                "drive-download"
            )

            checksum = sha256_file(
                local_path
            )

            state["checksum_sha256"] = (
                checksum
            )

            write_state(
                state_path,
                state,
            )

            print()
            print(
                "SHA256:",
                checksum,
            )

            existing = (
                read_existing_document(
                    checksum,
                    args.db_container,
                )
            )

            if existing:
                state[
                    "duplicate_document_id"
                ] = existing

                state["stages"].append(
                    "duplicate-preflight"
                )

                write_state(
                    state_path,
                    state,
                )

                print()
                print(
                    "DUPLICATE_DOCUMENT:",
                    existing,
                )

                print(
                    "Stopped before classifier, "
                    "OCR, vision, embeddings, "
                    "or database writes."
                )
                return

            state["stages"].append(
                "duplicate-preflight"
            )

            write_state(
                state_path,
                state,
            )

            print()
            print(
                "Classifying document..."
            )

            classification = classify(
                local_path
            )

            state["classification"] = {
                "proposed_title":
                    classification.get(
                        "proposed_title"
                    ),
                "authority_code":
                    classification.get(
                        "authority_code"
                    ),
                "authority_name":
                    classification.get(
                        "authority_name"
                    ),
                "domain":
                    classification.get(
                        "domain"
                    ),
                "topic":
                    classification.get(
                        "topic"
                    ),
                "document_type":
                    classification.get(
                        "document_type"
                    ),
                "jurisdiction":
                    classification.get(
                        "jurisdiction",
                        "HK",
                    ),
                "confidence":
                    classification.get(
                        "confidence"
                    ),
                "taxonomy_version":
                    classification.get(
                        "taxonomy_version"
                    ),
                "evidence_summary":
                    classification.get(
                        "evidence_summary"
                    ),
                "metadata":
                    classification.get(
                        "metadata",
                        {},
                    ),
            }

            state["stages"].append(
                "classification"
            )

            write_state(
                state_path,
                state,
            )

            print(
                json.dumps(
                    state[
                        "classification"
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )

            if (
                args.prepare
                and not args.yes
            ):
                answer = input(
                    "\nProceed with prepare-only "
                    "OCR/vision/embedding work? "
                    "[y/N]: "
                ).strip().lower()

                if answer not in {
                    "y",
                    "yes",
                }:
                    print(
                        "Cancelled before "
                        "v2 orchestration."
                    )
                    return

            command = [
                sys.executable,
                str(
                    script_path(
                        "orchestrate_document_v2.py"
                    )
                ),
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
                classification.get(
                    "authority_name",
                    "",
                ),
                "--jurisdiction",
                classification.get(
                    "jurisdiction",
                    "HK",
                ),
                "--language",
                args.language,
                "--db-container",
                args.db_container,
            ]

            if source_url:
                command.extend([
                    "--source-url",
                    source_url,
                ])

            if args.prepare:
                command.append(
                    "--prepare"
                )

            if persistent_workdir:
                command.extend([
                    "--workdir",
                    str(
                        persistent_workdir
                    ),
                ])

            run(
                command
            )

            state["stages"].append(
                (
                    "v2-prepare"
                    if args.prepare
                    else
                    "v2-route-only"
                )
            )

            write_state(
                state_path,
                state,
            )

        print()
        print("=" * 72)
        print(
            "GOOGLE DRIVE V2 OPT-IN COMPLETE"
        )
        print("=" * 72)

        print(
            "Mode:",
            state["mode"],
        )

        print(
            "Database write performed:",
            False,
        )

        if persistent_workdir:
            print(
                "Artifacts retained at:",
                persistent_workdir,
            )

    except Exception as exc:
        state["error"] = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        write_state(
            state_path,
            state,
        )

        if persistent_workdir:
            print(
                "Failure state retained at:",
                state_path,
                file=sys.stderr,
            )

        raise SystemExit(
            "Google Drive v2 opt-in failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


if __name__ == "__main__":
    main()
