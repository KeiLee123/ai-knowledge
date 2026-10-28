#!/usr/bin/env python3
"""M10A: read-only intake of frozen M9 Staging monitor artifacts.

No scheduler, networking, database, Drive, baseline, reference or filesystem writes.
A READY_FOR_STAGING_VALIDATION result is NOT a release qualification.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

VERSION = "m10a-candidate-intake-v1"
BATCH_VERSION = "source-monitor-batch-v1"
MONITOR_VERSION = "official-source-monitor-v1"
STATE_ROOT = Path("/var/lib/jason-os/source-monitor-staging")
SOURCE_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")
STAMP = re.compile(r"\d{8}T\d{6}Z\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
DECISIONS = {
    "NO_CHANGE": ("NONE", "NO_CHANGE"),
    "CANDIDATE_NEW_VERSION": (
        "STAGING_VALIDATION_REQUIRED", "READY_FOR_STAGING_VALIDATION"
    ),
    "REVIEW_REQUIRED": ("EXCEPTION_REVIEW", "REVIEW_REQUIRED"),
    "BLOCKED": ("STOP", "BLOCKED"),
}


class IntakeError(ValueError):
    """Unsafe or inconsistent M9 evidence; refuse to stage."""


def require(condition, reason):
    if not condition:
        raise IntakeError(reason)


def valid_sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def read_json(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), "expected a JSON object")
    return payload


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_root(value):
    raw = Path(value).expanduser()
    require(raw.is_absolute(), "state root must be absolute")
    # A specifically named staging fixture root is supported by --state-root.
    # This option never permits a Production state root by mistake.
    require(raw.name == "source-monitor-staging", "Staging-only state root required")
    require(not raw.is_symlink(), "state root symlink forbidden")
    root = raw.resolve(strict=True)
    require(root.is_dir(), "state root must be a directory")
    return root


def contained_file(path, parent, *, suffix=None):
    path = Path(path)
    require(path.is_absolute(), "artifact path must be absolute")
    require(not path.is_symlink(), "artifact symlink forbidden")
    actual = path.resolve(strict=True)
    require(actual.is_relative_to(parent.resolve(strict=True)), "artifact escapes Staging scope")
    require(actual.is_file(), "artifact is not a file")
    if suffix:
        require(actual.name == suffix, "unexpected artifact filename")
    return actual


def monitor_json(path):
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    found = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("version") == MONITOR_VERSION:
            found.append(value)
    require(len(found) == 1, "expected exactly one monitor JSON result")
    return found[0]


def validate_summary(summary_path, root):
    summary = contained_file(summary_path, root / "batches", suffix="summary.json")
    require(STAMP.fullmatch(summary.parent.name) is not None, "invalid M9 batch timestamp path")
    require(summary.parent.parent == root / "batches", "batch summary must be a direct child")
    payload = read_json(summary)
    require(payload.get("version") == BATCH_VERSION, "unexpected batch version")
    require(payload.get("git_branch") == "staging", "batch is not from Staging")
    require(isinstance(payload.get("git_commit"), str)
            and re.fullmatch(r"[0-9a-f]{40}", payload["git_commit"]),
            "invalid monitor git commit")
    require(payload.get("batch_timestamp") == summary.parent.name, "batch timestamp mismatch")
    require(payload.get("overall_status") in {"SUCCESS", "PARTIAL_FAILURE"},
            "invalid batch status")
    require(payload.get("production_access") is False and
            payload.get("production_write") is False, "unsafe batch Production flags")
    sources = payload.get("source_ids")
    results = payload.get("results")
    require(isinstance(sources, list) and sources, "empty source allowlist")
    require(all(isinstance(s, str) and SOURCE_ID.fullmatch(s) for s in sources),
            "unsafe source id")
    require(len(set(sources)) == len(sources), "duplicate source ids")
    require(isinstance(results, list) and len(results) == len(sources),
            "batch result list mismatch")
    require(all(isinstance(r, dict) for r in results), "invalid batch result")
    require([r.get("source_id") for r in results] == sources,
            "batch results do not match allowlist order")
    return payload, summary


def intake_one(batch, row, root):
    source_id = row["source_id"]
    require(row.get("production_access") is False and
            row.get("production_write") is False, "unsafe source Production flags")
    status = row.get("execution_status")
    require(status in {"EXECUTION_SUCCESS", "EXECUTION_FAILED", "SKIPPED_ALREADY_RUNNING"},
            "invalid source execution status")
    result = {
        "version": VERSION,
        "source_id": source_id,
        "batch_timestamp": batch["batch_timestamp"],
        "monitor_git_commit": batch["git_commit"],
        "status": None,
        "candidate_id": None,
        "candidate": None,
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
    }
    if status != "EXECUTION_SUCCESS":
        require(status == "EXECUTION_FAILED" or row.get("return_code") == 0,
                "invalid skipped run")
        result["status"] = "EXECUTION_FAILED" if status == "EXECUTION_FAILED" else "SKIPPED"
        return result
    require(row.get("return_code") == 0, "successful execution with nonzero return code")
    run_dir = row.get("run_dir")
    require(isinstance(run_dir, str), "missing M9 per-source run directory")
    run_path = Path(run_dir)
    require(run_path.is_absolute() and STAMP.fullmatch(run_path.name),
            "invalid M9 source run path")
    expected_parent = root / "runs" / source_id
    require(run_path.parent == expected_parent, "run path/source mismatch")
    require(not run_path.is_symlink() and run_path.resolve(strict=True).is_relative_to(expected_parent),
            "unsafe run directory")
    output_path = contained_file(run_path / "monitor-output.txt", run_path,
                                 suffix="monitor-output.txt")
    monitor = monitor_json(output_path)
    require(monitor.get("source_id") == source_id, "monitor source mismatch")
    require(monitor.get("production_access") is False and
            monitor.get("production_write") is False, "unsafe monitor Production flags")
    decision = monitor.get("decision")
    require(decision in DECISIONS, "unknown monitor decision")
    action, translated_status = DECISIONS[decision]
    require(monitor.get("action") == action, "monitor decision/action mismatch")
    require(row.get("decision") == decision and row.get("action") == action,
            "batch/monitor decision mismatch")
    require(row.get("candidate_downloaded") is monitor.get("candidate_downloaded"),
            "batch/monitor download mismatch")
    result.update({
        "status": translated_status,
        "monitor_decision": decision,
        "monitor_output_sha256": sha_file(output_path),
        "monitor_run_id": run_path.name,
    })
    if decision != "CANDIDATE_NEW_VERSION":
        if decision == "NO_CHANGE":
            require(monitor.get("candidate_downloaded") is False, "NO_CHANGE downloaded candidate")
            require(monitor.get("baseline_status") in {"UNCHANGED", "INDEX_CHANGED"},
                    "NO_CHANGE with changed document")
        return result

    require(monitor.get("baseline_status") == "DOCUMENT_CHANGED",
            "new candidate without document change")
    require(monitor.get("candidate_downloaded") is True, "missing candidate download")
    require(valid_sha(monitor.get("candidate_sha256")), "invalid candidate SHA-256")
    signals = monitor.get("signals")
    require(isinstance(signals, dict), "missing version signals")
    for key in (
        "authority_match", "document_code_match", "official_host_match",
        "checksum_changed", "normalized_content_changed", "metadata_changed",
    ):
        require(signals.get(key) is True, f"invalid candidate signal: {key}")
    require(signals.get("staging_validation_verified") is False and
            signals.get("deterministic_release") is False,
            "candidate cannot already be Staging-validated")
    qualification = monitor.get("qualification")
    require(isinstance(qualification, dict) and
            qualification.get("method") == "policy" and
            qualification.get("policy_version") == "official-source-version-policy-v1" and
            qualification.get("mode") == "version_candidate" and
            qualification.get("decision") == decision,
            "candidate qualification mismatch")
    candidate = contained_file(monitor.get("candidate_path"), run_path)
    require(candidate.parent == run_path, "candidate must be directly in M9 run directory")
    require(candidate.suffix.lower() == ".pdf", "candidate must be PDF")
    require(sha_file(candidate) == monitor["candidate_sha256"], "candidate checksum mismatch")
    reference_expected = root / "version-snapshots" / "current" / f"{source_id}.json"
    require(monitor.get("reference_path") == str(reference_expected),
            "unexpected accepted-reference path")
    reference = contained_file(reference_expected, root / "version-snapshots" / "current")
    record = read_json(reference)
    require(record.get("version_snapshot_store_version") == 1 and
            record.get("source_id") == source_id and
            isinstance(record.get("snapshot"), dict), "invalid accepted reference")
    accepted = record["snapshot"].get("document_sha256")
    require(valid_sha(accepted) and accepted != monitor["candidate_sha256"],
            "candidate already accepted or invalid reference")
    signals = monitor["signals"]
    for key in ("issue_date", "revision_date"):
        require(signals.get("previous_" + key) == record["snapshot"].get(key),
                "accepted reference changed since monitor")
    result["candidate_id"] = f"{source_id}:{monitor['candidate_sha256']}"
    result["candidate"] = {
        "path": str(candidate),
        "sha256": monitor["candidate_sha256"],
        "size_bytes": candidate.stat().st_size,
        "accepted_reference_sha256": accepted,
        "accepted_reference_record_sha256": sha_file(reference),
        "staging_validation_verified": False,
    }
    return result


def inspect_batch(summary_path, *, state_root=STATE_ROOT, source_id=None):
    root = validate_root(state_root)
    batch, _summary = validate_summary(summary_path, root)
    if source_id is not None:
        require(source_id in batch["source_ids"], "source not present in batch")
    results = []
    for row in batch["results"]:
        if source_id is None or row["source_id"] == source_id:
            try:
                results.append(intake_one(batch, row, root))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                results.append({
                    "version": VERSION,
                    "source_id": row["source_id"],
                    "status": "BLOCKED",
                    "reason": f"evidence_invalid: {exc}",
                    "candidate_id": None,
                    "production_access": False,
                    "production_write": False,
                    "write_authorized": False,
                })
    return {
        "version": VERSION,
        "batch_timestamp": batch["batch_timestamp"],
        "results": results,
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True,
                        help="M9 batch summary.json (read-only)")
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT,
                        help="M9 Staging state root; fixture roots must use same basename")
    parser.add_argument("--source", help="optional source id from the M9 allowlist")
    args = parser.parse_args(argv)
    try:
        report = inspect_batch(args.summary, state_root=args.state_root,
                               source_id=args.source)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"M10A REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if all(item["status"] not in {"BLOCKED", "EXECUTION_FAILED"}
                    for item in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
