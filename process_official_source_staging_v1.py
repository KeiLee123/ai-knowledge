#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import detect_source_changes_v1 as detector
import source_monitor_baseline_v1 as baseline
import write_pnap_staging_v1 as staging_writer

from extract_document_v2 import build_manifest
from ingest_manifest_v2 import read_existing_document
from route_document_v2 import assess_manifest
from run_multimodal_canary_v2 import (
    STAGING_DB_CONTAINER,
    verify_runtime,
)


VERSION = "official-source-processing-staging-v1"
DEFAULT_STATE_ROOT = Path(
    "/var/lib/jason-os/source-monitor-staging"
)


def script_path(repo_root: Path, name: str) -> Path:
    path = repo_root / name

    if not path.is_file():
        raise RuntimeError(
            f"Required script missing: {path}"
        )

    return path


def run_checked(command: list[str]) -> None:
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
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + " ".join(
                str(part)
                for part in command
            )
        )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_source(
    registry_path: Path,
    source_id: str,
) -> tuple[dict, dict, dict]:
    registry = detector.load_registry(
        registry_path
    )

    selected = detector.select_sources(
        registry,
        source_id=source_id,
    )

    source = selected[source_id]

    detector.validate_source(
        source_id,
        source,
    )

    return (
        registry,
        source,
        registry.get("defaults") or {},
    )


def current_observation(
    source_id: str,
    source: dict,
    defaults: dict,
) -> dict:
    return detector.probe_source(
        source_id,
        source,
        defaults,
    )


def resolve_baseline(
    *,
    registry_path: Path,
    source_id: str,
    source: dict,
    defaults: dict,
    state_root: Path,
    execute: bool,
) -> tuple[dict, dict]:
    state_root = baseline.validate_state_root(
        state_root
    )

    path = baseline.baseline_path(
        state_root,
        source_id,
    )

    if path.exists():
        check = baseline.check_against_baseline(
            registry_path=registry_path,
            source_id=source_id,
            state_root=state_root,
        )

        stored = baseline.load_baseline(
            path
        )

        return check, stored

    if execute:
        created = baseline.initialize_baseline(
            registry_path=registry_path,
            source_id=source_id,
            state_root=state_root,
        )

        return created, created["baseline"]

    observation = current_observation(
        source_id,
        source,
        defaults,
    )

    return (
        {
            "mode": "plan",
            "status": "BASELINE_MISSING",
            "source_id": source_id,
            "baseline_path": str(path),
        },
        {
            "baseline_version": None,
            "source_id": source_id,
            "observation": observation,
        },
    )


def baseline_document(
    payload: dict,
) -> dict:
    try:
        document = payload[
            "observation"
        ]["document"]
    except KeyError as exc:
        raise RuntimeError(
            "Baseline document fingerprint missing"
        ) from exc

    sha = document.get("sha256")
    size = document.get("content_length")

    if (
        not isinstance(sha, str)
        or len(sha) != 64
    ):
        raise RuntimeError(
            "Baseline document SHA-256 invalid"
        )

    if (
        not isinstance(size, int)
        or size < 1
    ):
        raise RuntimeError(
            "Baseline document size invalid"
        )

    return {
        "sha256": sha,
        "size_bytes": size,
    }


def download_and_route(
    *,
    source: dict,
    expected: dict,
    workdir: Path,
) -> tuple[dict, dict, Path]:
    local = (
        workdir
        / (
            source["document_code"]
            .replace("-", "")
            + ".pdf"
        )
    )

    download = staging_writer.download_document(
        source,
        local,
    )

    if download["sha256"] != expected["sha256"]:
        raise RuntimeError(
            "Live document SHA-256 differs from "
            "the approved baseline"
        )

    if (
        download["content_length"]
        != expected["size_bytes"]
    ):
        raise RuntimeError(
            "Live document size differs from "
            "the approved baseline"
        )

    manifest = build_manifest(
        local
    )

    route = assess_manifest(
        manifest,
        allow_partial=False,
    )

    write_json(
        workdir / "phase-a.json",
        manifest,
    )

    write_json(
        workdir / "route.json",
        route,
    )

    return download, route, local


def choose_pipeline(
    route: dict,
    source: dict,
) -> str:
    decision = route.get("decision") or {}

    if (
        decision.get(
            "production_decision_valid"
        )
        is not True
    ):
        raise RuntimeError(
            "Router did not produce a valid "
            "full-document decision"
        )

    recommended = decision.get(
        "recommended_pipeline"
    )

    if recommended == "legacy-v1":
        text_config = source.get(
            "canonical_text_ingestion"
        )

        if (
            not isinstance(text_config, dict)
            or text_config.get("enabled")
            is not True
        ):
            raise RuntimeError(
                "Router selected legacy-v1 but "
                "canonical_text_ingestion is disabled"
            )

        return "legacy-v1"

    if recommended == "multimodal-v2":
        config = source.get(
            "canonical_ingestion"
        )

        if (
            not isinstance(config, dict)
            or config.get("enabled")
            is not True
            or config.get("pipeline")
            != "multimodal-v2"
        ):
            raise RuntimeError(
                "Router selected multimodal-v2 but "
                "canonical_ingestion is not configured "
                "for multimodal-v2"
            )

        return "multimodal-v2"

    raise RuntimeError(
        f"Unsupported router pipeline: {recommended!r}"
    )


def remote_fingerprint(
    *,
    remote: str,
    path: str,
    expected: dict,
    workdir: Path,
    label: str,
) -> dict:
    if not staging_writer.remote_file_exists(
        remote,
        path,
    ):
        return {
            "exists": False,
            "verified": False,
            "remote_file": remote + path,
        }

    local = workdir / f"{label}.pdf"

    staging_writer.run_rclone(
        [
            "copyto",
            remote + path,
            str(local),
        ]
    )

    sha = staging_writer.sha256_file(
        local
    )

    size = local.stat().st_size

    if sha != expected["sha256"]:
        raise RuntimeError(
            f"{label} remote SHA-256 mismatch"
        )

    if size != expected["size_bytes"]:
        raise RuntimeError(
            f"{label} remote size mismatch"
        )

    return {
        "exists": True,
        "verified": True,
        "remote_file": remote + path,
        "sha256": sha,
        "size_bytes": size,
    }


def build_writer_command(
    *,
    python: str,
    repo_root: Path,
    source_id: str,
    state_root: Path,
) -> list[str]:
    return [
        python,
        str(
            script_path(
                repo_root,
                "write_pnap_staging_v1.py",
            )
        ),
        "--source",
        source_id,
        "--state-root",
        str(state_root),
        "--execute",
    ]


def build_promotion_command(
    *,
    python: str,
    repo_root: Path,
    source_id: str,
    state_root: Path,
) -> list[str]:
    return [
        python,
        str(
            script_path(
                repo_root,
                "promote_pnap_canonical_v1.py",
            )
        ),
        "--source",
        source_id,
        "--state-root",
        str(state_root),
        "--execute",
    ]


def build_text_write_command(
    *,
    python: str,
    repo_root: Path,
    source_id: str,
    state_root: Path,
    workdir: Path,
) -> list[str]:
    return [
        python,
        str(
            script_path(
                repo_root,
                "ingest_canonical_text_staging_v1.py",
            )
        ),
        source_id,
        "--write",
        "--confirm-staging-write",
        "--state-root",
        str(state_root),
        "--workdir",
        str(workdir),
    ]


def validation_config(
    source: dict,
) -> dict:
    config = source.get(
        "staging_validation"
    )

    if not isinstance(config, dict):
        raise RuntimeError(
            "staging_validation config missing"
        )

    query = config.get("query")
    terms = config.get(
        "expect_terms"
    )

    if (
        not isinstance(query, str)
        or not query.strip()
    ):
        raise RuntimeError(
            "staging_validation.query is required"
        )

    if (
        not isinstance(terms, list)
        or not terms
        or not all(
            isinstance(term, str)
            and term.strip()
            for term in terms
        )
    ):
        raise RuntimeError(
            "staging_validation.expect_terms "
            "must be a non-empty string list"
        )

    return {
        "query": query.strip(),
        "expect_terms": [
            term.strip()
            for term in terms
        ],
    }


def build_text_validation_command(
    *,
    python: str,
    repo_root: Path,
    source_id: str,
    state_root: Path,
    source: dict,
) -> list[str]:
    config = validation_config(
        source
    )

    command = [
        python,
        str(
            script_path(
                repo_root,
                "validate_canonical_text_staging_milestone_v1.py",
            )
        ),
        source_id,
        "--state-root",
        str(state_root),
        "--query",
        config["query"],
    ]

    for term in config[
        "expect_terms"
    ]:
        command.extend([
            "--expect-term",
            term,
        ])

    return command


def ensure_remote_stage(
    *,
    stage_name: str,
    state: dict,
    command: list[str],
    remote: str,
    path: str,
    expected: dict,
    workdir: Path,
) -> dict:
    if state["exists"]:
        return {
            **state,
            "action":
                "already_verified",
        }

    run_checked(
        command
    )

    verified = remote_fingerprint(
        remote=remote,
        path=path,
        expected=expected,
        workdir=workdir,
        label=stage_name,
    )

    if (
        not verified["exists"]
        or not verified["verified"]
    ):
        raise RuntimeError(
            f"{stage_name} write did not "
            "produce a verified remote file"
        )

    return {
        **verified,
        "action":
            "created_and_verified",
    }


def build_summary(
    *,
    source_id: str,
    mode: str,
    guard: dict,
    baseline_state: dict,
    expected: dict,
    route: dict,
    pipeline: str,
    staged: dict,
    canonical: dict,
    existing_document_id: str,
) -> dict:
    decision = route.get(
        "decision"
    ) or {}

    return {
        "version": VERSION,
        "source_id": source_id,
        "mode": mode,
        "guard_ok": guard[
            "guard_ok"
        ],
        "branch": guard[
            "branch"
        ],
        "db_container":
            STAGING_DB_CONTAINER,
        "baseline_status":
            baseline_state.get(
                "status"
            ),
        "sha256":
            expected["sha256"],
        "size_bytes":
            expected["size_bytes"],
        "recommended_pipeline":
            decision.get(
                "recommended_pipeline"
            ),
        "pipeline":
            pipeline,
        "staging_drive":
            staged,
        "canonical_drive":
            canonical,
        "existing_document_id":
            existing_document_id
            or None,
        "production_write":
            False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only official source "
            "processing orchestrator. "
            "Default mode is read-only planning. "
            "Execution may initialize a missing "
            "baseline, stage and canonically promote "
            "approved bytes, and run the reusable "
            "text ingestion path. Multimodal sources "
            "stop at an explicit handoff in v1."
        )
    )

    parser.add_argument(
        "source_id"
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__)
            .resolve()
            .parent
            / "source_registry_v1.yaml"
        ),
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
            "Perform approved Staging-only "
            "writes. Without this flag all "
            "operations remain read-only."
        ),
    )

    parser.add_argument(
        "--confirm-staging-processing",
        action="store_true",
        help=(
            "Required together with --execute."
        ),
    )

    parser.add_argument(
        "--workdir",
        default="",
    )

    args = parser.parse_args()

    if (
        args.confirm_staging_processing
        and not args.execute
    ):
        raise SystemExit(
            "--confirm-staging-processing "
            "requires --execute"
        )

    if (
        args.execute
        and not args.confirm_staging_processing
    ):
        raise SystemExit(
            "--execute requires "
            "--confirm-staging-processing"
        )

    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    registry_path = (
        Path(args.registry)
        .expanduser()
        .resolve()
    )

    state_root = (
        Path(args.state_root)
        .expanduser()
        .resolve()
    )

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
                prefix=(
                    "jason-os-official-source-"
                )
            )
        )

        workdir = Path(
            temp_context.name
        )

    try:
        guard = verify_runtime(
            repo_root
        )

        (
            _registry,
            source,
            defaults,
        ) = load_source(
            registry_path,
            args.source_id,
        )

        (
            baseline_state,
            baseline_payload,
        ) = resolve_baseline(
            registry_path=registry_path,
            source_id=args.source_id,
            source=source,
            defaults=defaults,
            state_root=state_root,
            execute=args.execute,
        )

        if (
            baseline_state.get("status")
            == "DOCUMENT_CHANGED"
        ):
            raise RuntimeError(
                "SOURCE_CHANGED_REVIEW_REQUIRED: "
                "document bytes differ from the "
                "approved baseline"
            )

        expected = baseline_document(
            baseline_payload
        )

        (
            _download,
            route,
            _local_source,
        ) = download_and_route(
            source=source,
            expected=expected,
            workdir=workdir,
        )

        pipeline = choose_pipeline(
            route,
            source,
        )

        writer_config = source.get(
            "drive_writer"
        ) or {}

        promotion_config = source.get(
            "canonical_promotion"
        ) or {}

        staged = remote_fingerprint(
            remote=writer_config[
                "remote"
            ],
            path=writer_config[
                "destination"
            ],
            expected=expected,
            workdir=workdir,
            label="staging-drive",
        )

        canonical = remote_fingerprint(
            remote=promotion_config[
                "remote"
            ],
            path=promotion_config[
                "destination"
            ],
            expected=expected,
            workdir=workdir,
            label="canonical-drive",
        )

        existing_document_id = (
            read_existing_document(
                expected["sha256"],
                STAGING_DB_CONTAINER,
            )
        )

        summary = build_summary(
            source_id=args.source_id,
            mode=(
                "execute"
                if args.execute
                else "plan"
            ),
            guard=guard,
            baseline_state=baseline_state,
            expected=expected,
            route=route,
            pipeline=pipeline,
            staged=staged,
            canonical=canonical,
            existing_document_id=
                existing_document_id,
        )

        if not args.execute:
            summary[
                "database_write_requested"
            ] = False

            print(
                json.dumps(
                    summary,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            print()
            print(
                "STATUS: "
                "OFFICIAL_SOURCE_PLAN_READY"
            )

            return

        python = sys.executable

        staged = ensure_remote_stage(
            stage_name="staging-drive",
            state=staged,
            command=build_writer_command(
                python=python,
                repo_root=repo_root,
                source_id=args.source_id,
                state_root=state_root,
            ),
            remote=writer_config[
                "remote"
            ],
            path=writer_config[
                "destination"
            ],
            expected=expected,
            workdir=workdir,
        )

        canonical = ensure_remote_stage(
            stage_name="canonical-drive",
            state=canonical,
            command=build_promotion_command(
                python=python,
                repo_root=repo_root,
                source_id=args.source_id,
                state_root=state_root,
            ),
            remote=promotion_config[
                "remote"
            ],
            path=promotion_config[
                "destination"
            ],
            expected=expected,
            workdir=workdir,
        )

        database_write_performed = False

        if pipeline == "multimodal-v2":
            final = build_summary(
                source_id=args.source_id,
                mode="execute",
                guard=guard,
                baseline_state=baseline_state,
                expected=expected,
                route=route,
                pipeline=pipeline,
                staged=staged,
                canonical=canonical,
                existing_document_id=
                    existing_document_id,
            )

            final.update(
                {
                    "database_write_requested":
                        False,
                    "database_write_performed":
                        False,
                    "staging_status":
                        "MULTIMODAL_HANDOFF_REQUIRED",
                    "production_ready":
                        False,
                }
            )

            print(
                json.dumps(
                    final,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            print()
            print(
                "STATUS: "
                "MULTIMODAL_STAGING_HANDOFF_REQUIRED"
            )

            return

        if not existing_document_id:
            text_workdir = (
                workdir
                / "text-ingestion"
            )

            text_workdir.mkdir(
                parents=True,
                exist_ok=True,
            )

            run_checked(
                build_text_write_command(
                    python=python,
                    repo_root=repo_root,
                    source_id=args.source_id,
                    state_root=state_root,
                    workdir=text_workdir,
                )
            )

            database_write_performed = True

            existing_document_id = (
                read_existing_document(
                    expected["sha256"],
                    STAGING_DB_CONTAINER,
                )
            )

            if not existing_document_id:
                raise RuntimeError(
                    "Text ingestion completed but "
                    "the document is not present "
                    "in the Staging DB"
                )

        run_checked(
            build_text_validation_command(
                python=python,
                repo_root=repo_root,
                source_id=args.source_id,
                state_root=state_root,
                source=source,
            )
        )

        final = build_summary(
            source_id=args.source_id,
            mode="execute",
            guard=guard,
            baseline_state=baseline_state,
            expected=expected,
            route=route,
            pipeline=pipeline,
            staged=staged,
            canonical=canonical,
            existing_document_id=
                existing_document_id,
        )

        final.update(
            {
                "database_write_requested":
                    True,
                "database_write_performed":
                    database_write_performed,
                "staging_status":
                    "VALIDATED",
                "production_ready":
                    True,
            }
        )

        print(
            json.dumps(
                final,
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "STATUS: "
            "READY_FOR_PRODUCTION_REVIEW"
        )

    except Exception as exc:
        raise SystemExit(
            "OFFICIAL SOURCE PROCESSING FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
