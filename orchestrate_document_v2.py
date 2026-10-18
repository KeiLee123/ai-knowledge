#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ingest_manifest_v2 import (
    DEFAULT_DB_CONTAINER,
    read_existing_document,
)


ORCHESTRATOR_VERSION = "phase-d5-2"


def run_checked(
    command: list[str],
    capture_output: bool = False,
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


def read_json(path: Path) -> dict:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def route_manifest(
    python: str,
    manifest_path: Path,
) -> dict:
    result = run_checked(
        [
            python,
            str(
                script_path(
                    "route_document_v2.py"
                )
            ),
            str(manifest_path),
        ],
        capture_output=True,
    )

    return json.loads(
        result.stdout
    )


def print_route(route: dict) -> None:
    decision = (
        route.get("decision")
        or {}
    )

    signals = (
        route.get(
            "signal_summary"
        )
        or {}
    )

    print()
    print("ROUTING_DECISION")

    print(
        json.dumps(
            {
                "router_version":
                    route.get(
                        "router_version"
                    ),
                "recommended_pipeline":
                    decision.get(
                        "recommended_pipeline"
                    ),
                "eligible_for_v2":
                    decision.get(
                        "eligible_for_v2"
                    ),
                "production_decision_valid":
                    decision.get(
                        "production_decision_valid"
                    ),
                "reasons":
                    decision.get(
                        "reasons"
                    ),
                "strong_signal_pages":
                    signals.get(
                        "strong_signal_pages"
                    ),
                "reason_pages":
                    signals.get(
                        "reason_pages"
                    ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_state(
    path: Path,
    payload: dict,
) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_metadata_args(
    args,
) -> list[str]:
    result = [
        "--title",
        args.title,
        "--domain",
        args.domain,
        "--topic",
        args.topic,
        "--document-type",
        args.document_type,
        "--authority",
        args.authority,
        "--jurisdiction",
        args.jurisdiction,
        "--language",
        args.language,
    ]

    if args.source_url:
        result.extend([
            "--source-url",
            args.source_url,
        ])

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in selected-document multimodal v2 "
            "orchestrator. Default mode performs only "
            "Phase A extraction and deterministic routing. "
            "It never invokes legacy v1 ingestion."
        )
    )

    parser.add_argument(
        "file",
        help=(
            "Local PDF/DOCX/TXT/MD source file"
        ),
    )

    parser.add_argument(
        "--title",
        required=True,
    )

    parser.add_argument(
        "--domain",
        required=True,
    )

    parser.add_argument(
        "--topic",
        required=True,
    )

    parser.add_argument(
        "--document-type",
        required=True,
    )

    parser.add_argument(
        "--authority",
        default="",
    )

    parser.add_argument(
        "--jurisdiction",
        default="HK",
    )

    parser.add_argument(
        "--language",
        default="en",
    )

    parser.add_argument(
        "--source-url",
        default="",
    )

    parser.add_argument(
        "--db-container",
        default=
            DEFAULT_DB_CONTAINER,
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "For a v2-eligible document, run "
            "OCR, vision, chunk build and D3 "
            "write-preparation without DB writes"
        ),
    )

    mode.add_argument(
        "--write",
        action="store_true",
        help=(
            "For a v2-eligible document, run "
            "the full pipeline and ingest it"
        ),
    )

    parser.add_argument(
        "--synthetic",
        action="store_true",
        help=(
            "Pass synthetic isolation through "
            "to the v2 ingester"
        ),
    )

    parser.add_argument(
        "--confirm-live-write",
        action="store_true",
        help=(
            "Required for non-synthetic --write"
        ),
    )

    parser.add_argument(
        "--workdir",
        help=(
            "Optional persistent working directory. "
            "Without this option a temporary directory "
            "is deleted automatically."
        ),
    )

    args = parser.parse_args()

    if (
        args.confirm_live_write
        and not args.write
    ):
        raise SystemExit(
            "--confirm-live-write requires --write"
        )

    if (
        args.write
        and not args.synthetic
        and not args.confirm_live_write
    ):
        raise SystemExit(
            "Non-synthetic --write requires "
            "--confirm-live-write"
        )

    source = (
        Path(args.file)
        .expanduser()
        .resolve()
    )

    if not source.is_file():
        raise SystemExit(
            f"Source file not found: {source}"
        )

    python = sys.executable

    temp_context = None

    if args.workdir:
        workdir = (
            Path(args.workdir)
            .expanduser()
            .resolve()
        )

        workdir.mkdir(
            parents=True,
            exist_ok=True,
        )

    else:
        temp_context = (
            tempfile.TemporaryDirectory(
                prefix="ai-knowledge-v2-"
            )
        )

        workdir = Path(
            temp_context.name
        )

    state_path = (
        workdir
        / "orchestration-state.json"
    )

    phase_a = (
        workdir
        / "phase-a.json"
    )

    phase_b = (
        workdir
        / "phase-b.json"
    )

    phase_c = (
        workdir
        / "phase-c.json"
    )

    chunks = (
        workdir
        / "retrieval-chunks-v2.json"
    )

    state = {
        "orchestrator_version":
            ORCHESTRATOR_VERSION,
        "source":
            str(source),
        "workdir":
            str(workdir),
        "mode":
            (
                "write"
                if args.write
                else (
                    "prepare"
                    if args.prepare
                    else "route-only"
                )
            ),
        "synthetic":
            bool(args.synthetic),
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
            "SELECTED-DOCUMENT V2 ORCHESTRATION"
        )
        print("=" * 72)
        print(
            "Source:",
            source,
        )
        print(
            "Mode:",
            state["mode"],
        )
        print(
            "Workdir:",
            workdir,
        )
        print()

        run_checked([
            python,
            str(
                script_path(
                    "extract_document_v2.py"
                )
            ),
            str(source),
            "-o",
            str(phase_a),
        ])

        state["stages"].append(
            "phase-a-extraction"
        )

        phase_a_data = read_json(
            phase_a
        )

        route = route_manifest(
            python,
            phase_a,
        )

        state["route"] = (
            route.get("decision")
            or {}
        )

        state["stages"].append(
            "d5-routing"
        )

        write_state(
            state_path,
            state,
        )

        print_route(
            route
        )

        decision = (
            route.get("decision")
            or {}
        )

        if not decision.get(
            "production_decision_valid"
        ):
            raise RuntimeError(
                "Router did not produce a valid "
                "production decision"
            )

        if not decision.get(
            "eligible_for_v2"
        ):
            print()
            print(
                "ROUTE_RESULT: legacy-v1"
            )
            print(
                "No v1 ingestion was invoked. "
                "Use the existing legacy workflow "
                "for this document."
            )
            return

        print()
        print(
            "ROUTE_RESULT: multimodal-v2"
        )

        if (
            not args.prepare
            and not args.write
        ):
            print(
                "Route-only mode complete. "
                "No OCR, vision, embeddings, "
                "or DB writes performed."
            )
            return

        checksum = (
            phase_a_data.get(
                "source"
            )
            or {}
        ).get(
            "sha256"
        )

        if not checksum:
            raise RuntimeError(
                "Phase A source SHA256 missing"
            )

        existing = (
            read_existing_document(
                checksum,
                args.db_container,
            )
        )

        if existing:
            raise RuntimeError(
                "Document checksum already exists "
                f"as document_id={existing}. "
                "Stopped before OCR/vision."
            )

        if (
            (
                phase_a_data.get(
                    "document"
                )
                or {}
            ).get(
                "kind"
            )
            != "pdf"
        ):
            raise RuntimeError(
                "v2 augmentation currently "
                "requires a PDF source"
            )

        run_checked([
            python,
            str(
                script_path(
                    "augment_ocr_v2.py"
                )
            ),
            str(phase_a),
            str(source),
            "-o",
            str(phase_b),
        ])

        state["stages"].append(
            "phase-b-ocr"
        )

        write_state(
            state_path,
            state,
        )

        run_checked([
            python,
            str(
                script_path(
                    "augment_vision_v2.py"
                )
            ),
            str(phase_b),
            str(source),
            "-o",
            str(phase_c),
        ])

        state["stages"].append(
            "phase-c-vision"
        )

        write_state(
            state_path,
            state,
        )

        run_checked([
            python,
            str(
                script_path(
                    "build_multimodal_chunks_v2.py"
                )
            ),
            str(phase_c),
            "-o",
            str(chunks),
        ])

        state["stages"].append(
            "phase-d1-chunks"
        )

        write_state(
            state_path,
            state,
        )

        ingest_command = [
            python,
            str(
                script_path(
                    "ingest_manifest_v2.py"
                )
            ),
            str(chunks),
            *build_metadata_args(
                args
            ),
            "--db-container",
            args.db_container,
            "--check-db",
        ]

        if args.synthetic:
            ingest_command.append(
                "--synthetic"
            )

        if args.prepare:
            ingest_command.append(
                "--prepare-write"
            )

        else:
            ingest_command.append(
                "--write"
            )

            if args.confirm_live_write:
                ingest_command.append(
                    "--confirm-live-write"
                )

        run_checked(
            ingest_command
        )

        state["stages"].append(
            (
                "phase-d3-write"
                if args.write
                else
                "phase-d3-write-preparation"
            )
        )

        state[
            "database_write_performed"
        ] = bool(
            args.write
        )

        write_state(
            state_path,
            state,
        )

        print()
        print("=" * 72)
        print(
            "V2 ORCHESTRATION COMPLETE"
        )
        print("=" * 72)

        print(
            "Mode:",
            state["mode"],
        )

        print(
            "Stages:",
            ", ".join(
                state["stages"]
            ),
        )

        print(
            "Database write performed:",
            state[
                "database_write_performed"
            ],
        )

        if args.workdir:
            print(
                "Artifacts retained at:",
                workdir,
            )

        else:
            print(
                "Temporary artifacts: "
                "deleted automatically"
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

        if args.workdir:
            print(
                "Failure artifacts retained at:",
                workdir,
                file=sys.stderr,
            )

        raise SystemExit(
            "v2 orchestration failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
