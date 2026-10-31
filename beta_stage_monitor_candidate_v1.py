#!/usr/bin/env python3
"""Beta Gate 1: stage an M9-verified changed PDF to versioned Drive Staging.

Standalone, explicitly confirmed operator handoff; NOT an automatic timer hook.
Read-only planning is default. Never touches Current, Source Registry,
reference snapshots, DB, Production, or M8/M9 frozen services.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import detect_source_changes_v1 as detector
import write_pnap_staging_v1 as writer
from run_source_monitor_batch_v1 import extract_monitor_result
from version_qualification_policy_v1 import UNCHANGED as MONITOR_NO_CHANGE

VERSION = "beta-source-drive-handoff-v1"
STATE_ROOT = Path("/var/lib/jason-os/source-monitor-staging")
STAGING_CHECKOUT = Path("/opt/ai-knowledge-staging")
MAX_PDF_BYTES = 30 * 1024 * 1024
REMOTE = "gdrive-bd-write:"
PREFIX = "_Staging_Incoming/APP/_versioned_candidates/"
STAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


class HandoffRefused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise HandoffRefused(message)


def inside(root, target):
    """Forbid path traversal and symlinks including any parent up to root."""
    root, target = Path(root), Path(target)
    require(root.is_absolute() and target.is_absolute(), "absolute_paths_required")
    require(".." not in target.parts and ".." not in root.parts,
            "path_traversal_refused")
    require(target != root and root in target.parents,
            "path_outside_staging_root")
    chain = [target, *list(target.parents)[:list(target.parents).index(root) + 1]]
    require(all(not part.is_symlink() for part in chain), "symlink_refused")
    require(root.is_dir() and target.exists(), "staging_artifact_missing")
    require(target.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
            "resolved_path_outside_staging")


def file_sha(path):
    size = 0
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        magic = handle.read(5)
        require(magic == b"%PDF-", "non_pdf_candidate_refused")
        digest.update(magic)
        size += len(magic)
        while True:
            part = handle.read(1024 * 1024)
            if not part:
                break
            size += len(part)
            require(size <= MAX_PDF_BYTES, "candidate_too_large")
            digest.update(part)
    require(size > 5, "empty_pdf_candidate")
    return size, digest.hexdigest()


def load_source(registry_path, source_id):
    registry = detector.load_registry(Path(registry_path))
    sources = detector.select_sources(registry, source_id=source_id)
    source = sources[source_id]
    detector.validate_source(source_id, source)
    config = source.get("drive_writer")
    require(isinstance(config, dict), "missing_staging_writer")
    writer.validate_writer_config(source_id, config)
    require(config.get("remote") == REMOTE, "unexpected_drive_remote")
    require(config.get("destination", "").startswith("_Staging_Incoming/APP/"),
            "unexpected_drive_staging_prefix")
    require(source_id.startswith("BD_PNAP_APP"), "beta_bd_pnap_scope_only")
    require(re.fullmatch(r"APP[0-9]{1,4}",
                         source.get("document_code", "").replace("-", "")) is not None,
            "invalid_document_code")
    return source


def plan_candidate(*, state_root, run_dir, source_id, source):
    """Validate actual M9 output and pinned local bytes; no network/writes."""
    root, run = Path(state_root), Path(run_dir)
    require(run.parent.parent == root / "runs", "invalid_monitor_run_location")
    require(run.parent.name == source_id and STAMP.fullmatch(run.name),
            "unexpected_source_or_run_stamp")
    inside(root, run)
    output = run / "monitor-output.txt"
    inside(root, output)
    require(output.is_file() and output.stat().st_size <= 2 * 1024 * 1024,
            "invalid_monitor_log")
    monitor = extract_monitor_result(output.read_text(encoding="utf-8"))
    require(isinstance(monitor, dict), "missing_monitor_result")
    require(monitor.get("version") == "official-source-monitor-v1" and
            monitor.get("source_id") == source_id, "monitor_identity_mismatch")
    require(monitor.get("production_access") is False and
            monitor.get("production_write") is False, "production_flag_refused")
    if (monitor.get("decision") == MONITOR_NO_CHANGE and
            monitor.get("baseline_status") in ("UNCHANGED", "INDEX_CHANGED") and
            monitor.get("action") == "NONE" and
            monitor.get("candidate_downloaded") is False and
            "candidate_path" not in monitor and
            "candidate_sha256" not in monitor):
        return {"version": VERSION, "source_id": source_id,
                "status": "NO_CHANGE", "write_authorized": False,
                "production_write": False}
    require(monitor.get("baseline_status") == "DOCUMENT_CHANGED",
            "not_a_document_change")
    require(monitor.get("decision") == "CANDIDATE_NEW_VERSION" and
            monitor.get("action") == "STAGING_VALIDATION_REQUIRED" and
            monitor.get("candidate_downloaded") is True,
            "candidate_requires_separate_review_or_is_blocked")
    expected = monitor.get("candidate_sha256")
    require(isinstance(expected, str) and SHA.fullmatch(expected),
            "missing_pinned_candidate_sha")
    code = source["document_code"]
    path = run / (code + "-candidate.pdf")
    require(monitor.get("candidate_path") == str(path),
            "candidate_location_mismatch")
    inside(root, path)
    require(path.is_file() and path.stat().st_size <= MAX_PDF_BYTES,
            "candidate_size_or_type_refused")
    size, actual = file_sha(path)
    require(actual == expected, "candidate_sha_mismatch")
    dest = PREFIX + source_id + "/" + expected + ".pdf"
    return {"version": VERSION, "source_id": source_id,
            "status": "READY_FOR_VERSIONED_DRIVE_STAGING",
            "candidate_path": str(path), "candidate_sha256": expected,
            "candidate_size_bytes": size, "drive_remote": REMOTE,
            "drive_path": dest, "source_canonical_url": source["canonical_url"],
            "staging_validation_completed": False,
            "canonical_current_updated": False, "reference_advanced": False,
            "production_write": False, "write_authorized": False}


def upload_candidate(plan):
    """Write only a content-addressed staging candidate; verify round-trip."""
    require(plan["status"] == "READY_FOR_VERSIONED_DRIVE_STAGING",
            "not_a_stageable_plan")
    source_id, expected = plan["source_id"], plan["candidate_sha256"]
    require(re.fullmatch(r"BD_PNAP_APP[0-9]{1,4}", source_id) is not None and
            isinstance(expected, str) and SHA.fullmatch(expected),
            "invalid_candidate_identity")
    require(plan["drive_remote"] == REMOTE and
            plan["drive_path"] == PREFIX + source_id + "/" + expected + ".pdf",
            "destination_out_of_scope")
    remote = REMOTE + plan["drive_path"]
    local = Path(plan["candidate_path"])
    size, digest = file_sha(local)
    require(size == plan["candidate_size_bytes"] and
            digest == plan["candidate_sha256"], "candidate_changed_before_upload")
    already = writer.remote_file_exists(REMOTE, plan["drive_path"])
    if not already:
        writer.ensure_remote_parent(REMOTE, plan["drive_path"])
        # rclone --immutable refuses overwriting different bytes in a race.
        writer.run_rclone(["copyto", str(local), remote, "--immutable"])
    with tempfile.TemporaryDirectory(prefix="jason-beta-stage-verify-") as temp:
        copied = Path(temp) / "remote-copy.pdf"
        writer.run_rclone(["copyto", remote, str(copied)])
        remote_size, remote_sha = file_sha(copied)
    require(remote_size == size and remote_sha == digest,
            "drive_roundtrip_mismatch_manual_inspection_required")
    require(file_sha(local) == (size, digest),
            "candidate_changed_during_upload")
    return {"version": VERSION, "source_id": plan["source_id"],
            "status": "ALREADY_STAGED_VERIFIED" if already else "STAGED_AND_VERIFIED",
            "drive_remote": REMOTE, "drive_path": plan["drive_path"],
            "sha256": digest, "bytes": size, "readback_verified": True,
            "canonical_current_updated": False, "reference_advanced": False,
            "staging_validation_completed": False, "production_write": False}


def check_staging_checkout(repo_root):
    repo_root = Path(repo_root)
    require(repo_root == STAGING_CHECKOUT, "not_the_staging_checkout")
    def git(*args):
        return subprocess.run(["git", "-C", str(repo_root), *args],
                              check=True, capture_output=True, text=True).stdout.strip()
    require(git("branch", "--show-current") == "staging", "not_staging_branch")
    require(not git("status", "--porcelain"), "dirty_staging_checkout")


def main():
    parser = argparse.ArgumentParser(description="Beta M9 source→Drive Staging candidate handoff")
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--registry", default=str(STAGING_CHECKOUT / "source_registry_v1.yaml"))
    parser.add_argument("--state-root", default=str(STATE_ROOT))
    parser.add_argument("--confirm-drive-staging-write", action="store_true")
    args = parser.parse_args()
    require(Path(args.state_root) == STATE_ROOT, "staging_state_root_only")
    require(Path(args.registry) == STAGING_CHECKOUT / "source_registry_v1.yaml",
            "staging_registry_only")
    check_staging_checkout(Path(__file__).resolve().parent)
    source = load_source(args.registry, args.source)
    plan = plan_candidate(state_root=STATE_ROOT, run_dir=Path(args.run_dir),
                          source_id=args.source, source=source)
    if not args.confirm_drive_staging_write or plan["status"] == "NO_CHANGE":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return
    result = upload_candidate(plan)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
