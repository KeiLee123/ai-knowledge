#!/usr/bin/env python3
"""M10B-1: local-only validation of one M9 candidate on Staging.

Default is read-only admission planning. --validate requires an explicit
workspace-write confirmation. This tool never uses DB, Drive, network, or
existing canary/ingestion orchestrators. PARSE_VERIFIED != STAGING_VERIFIED.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from m10_candidate_intake_v1 import (
    STATE_ROOT, inspect_batch, read_json, sha_file, validate_root, valid_sha,
)

VERSION = "m10b1-local-candidate-validation-v1"
WORKSPACE_ROOT = Path("/var/lib/jason-os/source-update-validation-staging")
REGISTRY = Path(__file__).resolve().with_name("source_registry_v1.yaml")


class CandidateError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise CandidateError(reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def base_report(source_id, *, mode):
    return {
        "version": VERSION,
        "source_id": source_id,
        "mode": mode,
        "status": "BLOCKED",
        "reasons": [],
        "candidate_id": None,
        "environment": "staging",
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
        "canonical_promoted": False,
        "accepted_reference_advanced": False,
        "retrieval_verified": False,
    }


def trusted_source(source_id, *, registry_path=REGISTRY):
    # Import registry loader lazily. Its import does NOT perform HTTP probing.
    from detect_source_changes_v1 import load_registry
    payload = load_registry(registry_path)
    source = (payload.get("sources") or {}).get(source_id)
    need(isinstance(source, dict) and source.get("enabled") is True,
         "source_not_enabled_or_not_registered")
    required = ("authority_code", "document_code", "source_family", "canonical_url")
    for key in required:
        need(isinstance(source.get(key), str) and source[key].strip(),
             "missing_trusted_identity:" + key)
    allowed = source.get("allowed_hosts")
    need(isinstance(allowed, list) and bool(allowed), "missing_allowed_hosts")
    need(all(isinstance(h, str) and h and h == h.strip()
             and h == h.lower() for h in allowed), "invalid_allowed_hosts")
    url = urlsplit(source["canonical_url"])
    need(url.scheme == "https" and bool(url.hostname)
         and not url.username and not url.password and url.port is None
         and not url.fragment and not url.query,
         "unsafe_canonical_url")
    need(url.hostname in allowed, "canonical_host_not_allowlisted")
    need(url.path.lower().endswith(".pdf"), "canonical_source_not_pdf")
    return source, url.hostname


def locked_reference(state_root, source_id, expected_sha, source, host):
    path = state_root / "version-snapshots" / "current" / (source_id + ".json")
    need(path.is_file() and not path.is_symlink(), "missing_or_unsafe_reference")
    raw = path.read_bytes()
    need(digest(raw) == expected_sha, "reference_changed_since_intake")
    record = json.loads(raw)
    need(record.get("version_snapshot_store_version") == 1
         and record.get("source_id") == source_id
         and isinstance(record.get("snapshot"), dict),
         "invalid_accepted_reference")
    snap = record["snapshot"]
    for key, expected in (
        ("authority_code", source["authority_code"]),
        ("document_code", source["document_code"]),
        ("canonical_host", host),
        ("source_family", source["source_family"]),
    ):
        need(isinstance(snap.get(key), str) and bool(snap[key].strip()),
             "missing_accepted_identity:" + key)
        need(snap[key] == expected, "accepted_identity_mismatch:" + key)
    for key in ("document_sha256", "normalized_content_fingerprint",
                "metadata_fingerprint"):
        need(valid_sha(snap.get(key)), "missing_accepted_fingerprint:" + key)
    return path, snap, digest(raw)


def workspace_scope(workspace_root, state_root):
    root = Path(workspace_root).expanduser()
    need(root.is_absolute() and root.name == "source-update-validation-staging",
         "invalid_staging_workspace_root")
    need(not any("production" in part.lower() for part in root.parts),
         "production_workspace_forbidden")
    if state_root == STATE_ROOT:
        need(root == WORKSPACE_ROOT, "canonical_staging_workspace_required")
    else:
        need(root.parent == state_root.parent, "fixture_workspace_must_be_sibling")
    need(not root.is_symlink(), "workspace_root_symlink")
    return root


def safe_mkdir(path):
    if path.exists() or path.is_symlink():
        need(path.is_dir() and not path.is_symlink(),
             "workspace_path_not_real_directory")
        return
    path.mkdir(mode=0o700)
    need(path.is_dir() and not path.is_symlink(),
         "workspace_creation_failure")


def prepare_workspace(root, source_id, candidate_sha):
    # No writes to any location except this explicit Staging candidate root.
    safe_mkdir(root)
    croot = root / "candidates"
    safe_mkdir(croot)
    source_root = croot / source_id
    safe_mkdir(source_root)
    candidate_root = source_root / candidate_sha
    safe_mkdir(candidate_root)
    need(candidate_root.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
         "workspace_escape")
    return candidate_root


def write_candidate_copy(source, target, expected_sha):
    need(not target.is_symlink(), "candidate_copy_symlink")
    if target.exists():
        need(target.is_file() and sha_file(target) == expected_sha,
             "existing_candidate_copy_mismatch")
        return
    # Exclusive creation forbids overwriting any earlier candidate.
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    need(sha_file(target) == expected_sha, "candidate_copy_sha_mismatch")


def atomic_bundle(path, record):
    # A content-addressed candidate retains its first immutable result.
    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                      indent=2) + "\n").encode("utf-8")
    if path.exists():
        need(not path.is_symlink() and path.read_bytes() == raw,
             "existing_bundle_conflict")
        return
    fd, temp_name = tempfile.mkstemp(prefix=".bundle-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, path)  # Atomic create-if-absent; never replace.
    finally:
        Path(temp_name).unlink(missing_ok=True)


def process(summary, source_id, *, state_root=STATE_ROOT,
            workspace_root=WORKSPACE_ROOT, validate=False):
    mode = "validate" if validate else "plan"
    report = base_report(source_id, mode=mode)
    try:
        root = validate_root(state_root)
        workspace = workspace_scope(workspace_root, root)
        intake = inspect_batch(summary, state_root=root, source_id=source_id)
        item = intake["results"][0]
        report["m10a_status"] = item["status"]
        if item["status"] == "NO_CHANGE":
            report["status"] = "NO_CHANGE"
            return report
        if item["status"] != "READY_FOR_STAGING_VALIDATION":
            report["status"] = ("BLOCKED" if item["status"] in
                                ("BLOCKED", "EXECUTION_FAILED") else "REVIEW_REQUIRED")
            report["reasons"] = ["m10a_" + item["status"].lower()]
            return report

        source, host = trusted_source(source_id)
        candidate_info = item["candidate"]
        expected_sha = candidate_info["sha256"]
        need(item["candidate_id"] == source_id + ":" + expected_sha,
             "candidate_id_mismatch")
        candidate = Path(candidate_info["path"])
        need(candidate.is_file() and not candidate.is_symlink()
             and candidate.suffix.lower() == ".pdf"
             and sha_file(candidate) == expected_sha,
             "candidate_bytes_changed")
        ref_path, previous, before = locked_reference(
            root, source_id, candidate_info["accepted_reference_record_sha256"],
            source, host)
        report["candidate_id"] = item["candidate_id"]
        report["candidate_sha256"] = expected_sha
        report["reference_sha256_before"] = before
        report["monitor_output_sha256"] = item["monitor_output_sha256"]
        report["monitor_run_id"] = item["monitor_run_id"]
        report["batch_timestamp"] = item["batch_timestamp"]
        report["trusted_identity"] = {
            "authority_code": source["authority_code"],
            "document_code": source["document_code"],
            "canonical_host": host,
        }
        if not validate:
            report["status"] = "READY_FOR_PARSE"
            return report

        # Explicit validate writes only this isolated workspace.
        candidate_dir = prepare_workspace(workspace, source_id, expected_sha)
        lock_path = candidate_dir / ".lock"
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                          0o600)
        try:
            os.close(lock_fd)
            stored = candidate_dir / "candidate.pdf"
            bundle_path = candidate_dir / "evidence.json"
            write_candidate_copy(candidate, stored, expected_sha)
            if bundle_path.exists():
                existing = read_json(bundle_path)
                need(existing.get("candidate_id") == report["candidate_id"]
                     and existing.get("reference_sha256_before") == before
                     and existing.get("candidate_sha256") == expected_sha,
                     "cached_evidence_reference_mismatch")
                return existing

            need(stored.open("rb").read(5) == b"%PDF-", "not_pdf_header")
            from extract_document_v2 import build_manifest
            from route_document_v2 import assess_manifest
            from version_signal_extractor_v1 import (
                build_version_signal_snapshot, compare_version_snapshots,
            )
            from version_qualification_policy_v1 import evaluate_version_candidate
            manifest = build_manifest(stored)
            need(manifest.get("source", {}).get("sha256") == expected_sha,
                 "manifest_source_sha_mismatch")
            need(manifest.get("document", {}).get("kind") == "pdf"
                 and (manifest.get("document", {}).get("page_count") or 0) > 0,
                 "invalid_pdf_manifest")
            route = assess_manifest(manifest, allow_partial=False)
            need(route.get("decision", {}).get("production_decision_valid") is True
                 and route.get("document", {}).get("partial_manifest") is False,
                 "invalid_or_partial_route")
            current = build_version_signal_snapshot(
                source_file=stored, manifest=manifest, source=source)
            for key, expected in (
                ("authority_code", source["authority_code"]),
                ("document_code", source["document_code"]),
                ("canonical_host", host),
            ):
                need(current.get(key) == expected, "current_identity_mismatch:" + key)
            signals = compare_version_snapshots(
                previous, current,
                staging_validation_verified=False, deterministic_release=False)
            policy = evaluate_version_candidate(signals)
            need(sha_file(candidate) == expected_sha and sha_file(stored) == expected_sha,
                 "candidate_changed_during_validation")
            after = digest(ref_path.read_bytes())
            report["reference_sha256_after"] = after
            report["route"] = route["decision"]["recommended_pipeline"]
            report["router_version"] = route["router_version"]
            report["manifest_sha256"] = digest(json.dumps(
                manifest, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8"))
            report["page_count"] = manifest["document"]["page_count"]
            report["normalized_content_chars"] = current["normalized_content_chars"]
            report["normalized_content_fingerprint"] = current["normalized_content_fingerprint"]
            report["policy_decision"] = policy["decision"]
            report["policy_reasons"] = policy["reasons"]
            report["retrieval_verified"] = False

            if after != before:
                report["status"] = "REVIEW_REQUIRED"
                report["reasons"] = ["accepted_reference_drift"]
            elif policy["decision"] == "BLOCKED":
                report["status"] = "BLOCKED"
                report["reasons"] = ["candidate_policy_blocked"]
            elif policy["decision"] != "CANDIDATE_NEW_VERSION":
                report["status"] = "REVIEW_REQUIRED"
                report["reasons"] = ["candidate_policy_not_qualified"]
            elif report["route"] != "legacy-v1":
                report["status"] = "REVIEW_REQUIRED"
                report["reasons"] = ["multimodal_requires_ocr_vision_provenance"]
            elif current["normalized_content_chars"] < 100:
                report["status"] = "REVIEW_REQUIRED"
                report["reasons"] = ["insufficient_text_evidence"]
            else:
                report["status"] = "PARSE_VERIFIED"
                report["reasons"] = ["retrieval_not_verified"]
            atomic_bundle(bundle_path, report)
            return report
        finally:
            lock_path.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        report["status"] = "BLOCKED"
        report["reasons"] = [f"local_validation_failed:{type(exc).__name__}:{exc}"]
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--workspace-root", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--validate", action="store_true",
                        help="write candidate evidence only inside isolated Staging workspace")
    parser.add_argument("--confirm-staging-candidate-write", action="store_true")
    args = parser.parse_args(argv)
    if args.validate != args.confirm_staging_candidate_write:
        parser.error("--validate and --confirm-staging-candidate-write must be used together")
    report = process(args.summary, args.source,
                     state_root=args.state_root, workspace_root=args.workspace_root,
                     validate=args.validate)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
