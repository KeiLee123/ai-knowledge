#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)


VERSION = "canonical-ingestion-v1"
REGISTRY_VERSION = 1
ALLOWED_REMOTE = "gdrive-bd-write:"
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_STATE_ROOT = Path("/var/lib/jason-os/source-monitor-staging")


def run_checked(command):
    result = subprocess.run(command, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + " ".join(str(part) for part in command)
        )

    return result


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def load_registry(path):
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError("Registry must be a mapping")

    if payload.get("source_registry_version") != REGISTRY_VERSION:
        raise RuntimeError("Unsupported source registry version")

    return payload


def validate_source_id(source_id):
    if not SAFE_SOURCE_ID.fullmatch(source_id):
        raise RuntimeError("Unsafe source id")

    return source_id


def validate_ingestion_config(ingestion):
    errors = []

    if ingestion.get("enabled") is not True:
        errors.append("canonical_ingestion must be enabled")

    if ingestion.get("controller_environment") != "staging":
        errors.append("controller_environment must be staging")

    if ingestion.get("remote") != ALLOWED_REMOTE:
        errors.append("remote must be the isolated BD writer")

    source_path = ingestion.get("source")

    if (
        not isinstance(source_path, str)
        or source_path.startswith("/")
        or not source_path.startswith("Current/")
        or not source_path.lower().endswith(".pdf")
    ):
        errors.append("source must be a PDF under Current/")

    if ingestion.get("db_container") != STAGING_DB_CONTAINER:
        errors.append("db_container must be the fixed staging DB")

    if ingestion.get("db_container") == PRODUCTION_DB_CONTAINER:
        errors.append("Production DB container is forbidden")

    if ingestion.get("pipeline") != "multimodal-v2":
        errors.append("pipeline must be multimodal-v2")

    if ingestion.get("allow_production_write", False) is not False:
        errors.append("allow_production_write must be false")

    if errors:
        raise RuntimeError("; ".join(errors))


def resolve_source(registry, source_id):
    validate_source_id(source_id)

    source = (registry.get("sources") or {}).get(source_id)

    if not isinstance(source, dict):
        raise RuntimeError(f"Unknown source: {source_id}")

    if source.get("enabled") is not True:
        raise RuntimeError("Source is not enabled")

    ingestion = source.get("canonical_ingestion")

    if not isinstance(ingestion, dict):
        raise RuntimeError("canonical_ingestion config missing")

    validate_ingestion_config(ingestion)

    return source, ingestion, (registry.get("defaults") or {})


def baseline_path(state_root, source_id):
    validate_source_id(source_id)
    return state_root / "baselines" / f"{source_id}.json"


def load_expected_baseline(state_root, source_id):
    path = baseline_path(state_root, source_id)
    payload = json.loads(path.read_text(encoding="utf-8"))

    if payload.get("source_id") != source_id:
        raise RuntimeError("Baseline source_id mismatch")

    document = ((payload.get("observation") or {}).get("document") or {})
    checksum = (document.get("sha256") or "").lower()

    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise RuntimeError("Baseline document SHA-256 missing or invalid")

    content_length = document.get("content_length")

    if content_length is not None:
        content_length = int(content_length)

    return {
        "baseline_path": str(path),
        "sha256": checksum,
        "content_length": content_length,
    }


def canonical_remote_path(ingestion):
    return ingestion["remote"] + ingestion["source"]


def download_canonical(ingestion, destination):
    run_checked([
        "rclone",
        "copyto",
        canonical_remote_path(ingestion),
        str(destination),
    ])


def verify_download(path, expected):
    actual_sha256 = sha256_file(path)
    actual_size = path.stat().st_size

    if actual_sha256 != expected["sha256"]:
        raise RuntimeError(
            "Canonical SHA-256 does not match approved baseline"
        )

    expected_size = expected.get("content_length")

    if expected_size is not None and actual_size != expected_size:
        raise RuntimeError(
            "Canonical byte size does not match approved baseline"
        )

    return {
        "sha256": actual_sha256,
        "size_bytes": actual_size,
        "verified": True,
    }


def build_canary_command(
    *,
    repo_root,
    python,
    source_file,
    source,
    ingestion,
    defaults,
    workdir,
    write,
):
    command = [
        python,
        str(repo_root / "run_multimodal_canary_v2.py"),
        str(source_file),
        "--title",
        str(
            source.get("title")
            or source.get("document_code")
            or "Canonical document"
        ),
        "--domain",
        str(source.get("domain") or "unknown"),
        "--topic",
        str(source.get("topic") or ""),
        "--document-type",
        str(
            ingestion.get("document_type")
            or source.get("source_type")
            or "official-document"
        ),
        "--authority",
        str(source.get("authority_code") or ""),
        "--jurisdiction",
        str(defaults.get("jurisdiction") or "HK"),
        "--language",
        str(ingestion.get("language") or "en"),
    ]

    source_url = source.get("canonical_url") or ""

    if source_url:
        command.extend(["--source-url", str(source_url)])

    if workdir:
        command.extend(["--workdir", workdir])

    if write:
        command.extend(["--write", "--confirm-staging-write"])

    return command


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only canonical document ingestion gate. "
            "Verifies a Google Drive Current document against "
            "the approved source-monitor baseline before "
            "optionally invoking the existing multimodal v2 "
            "staging canary pipeline."
        )
    )
    parser.add_argument("source_id")
    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--state-root",
        default=str(DEFAULT_STATE_ROOT),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--prepare",
        action="store_true",
        help="Run the existing multimodal pipeline in prepare-only mode.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write only to the isolated staging Knowledge DB.",
    )

    parser.add_argument(
        "--confirm-staging-write",
        action="store_true",
        help="Required together with --write.",
    )
    parser.add_argument(
        "--workdir",
        default="",
        help="Optional persistent multimodal workdir.",
    )

    args = parser.parse_args()

    if args.confirm_staging_write and not args.write:
        raise SystemExit("--confirm-staging-write requires --write")

    if args.write and not args.confirm_staging_write:
        raise SystemExit("--write requires --confirm-staging-write")

    repo_root = Path(__file__).resolve().parent

    try:
        guard = verify_runtime(repo_root)
        registry = load_registry(Path(args.registry).expanduser().resolve())

        source, ingestion, defaults = resolve_source(
            registry,
            args.source_id,
        )

        expected = load_expected_baseline(
            Path(args.state_root).expanduser().resolve(),
            args.source_id,
        )

        with tempfile.TemporaryDirectory(
            prefix="jason-os-canonical-ingestion-"
        ) as temp_dir:
            local_file = Path(temp_dir) / Path(ingestion["source"]).name

            download_canonical(ingestion, local_file)
            verified = verify_download(local_file, expected)

            summary = {
                "version": VERSION,
                "source_id": args.source_id,
                "mode": (
                    "write"
                    if args.write
                    else "prepare"
                    if args.prepare
                    else "dry-run"
                ),
                "guard_ok": guard["guard_ok"],
                "branch": guard["branch"],
                "db_container": ingestion["db_container"],
                "remote": ingestion["remote"],
                "canonical_source": ingestion["source"],
                "baseline_path": expected["baseline_path"],
                "sha256": verified["sha256"],
                "size_bytes": verified["size_bytes"],
                "verified": True,
                "production_write": False,
                "database_write_requested": bool(args.write),
            }

            print(json.dumps(summary, ensure_ascii=False, indent=2))

            if not args.prepare and not args.write:
                print()
                print("STATUS: READY_TO_PREPARE")
                print(
                    "No OCR, vision, embeddings, or database writes "
                    "were invoked."
                )
                return

            command = build_canary_command(
                repo_root=repo_root,
                python=sys.executable,
                source_file=local_file,
                source=source,
                ingestion=ingestion,
                defaults=defaults,
                workdir=args.workdir,
                write=bool(args.write),
            )

            print()
            print(
                "PIPELINE MODE:",
                "STAGING WRITE" if args.write else "PREPARE ONLY",
            )
            print()

            run_checked(command)

            print()
            print(
                "STATUS:",
                "INGESTED_TO_STAGING"
                if args.write
                else "PREPARED_FOR_STAGING",
            )

    except Exception as exc:
        raise SystemExit(
            "CANONICAL INGESTION FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
