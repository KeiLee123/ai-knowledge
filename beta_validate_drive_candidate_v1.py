#!/usr/bin/env python3
"""Join an existing versioned Drive candidate to isolated parse/lexical evidence.

Default: local read-only plan. --verify-drive reads an EXISTING Drive object
into disposable scratch; never uploads. --validate additionally requires
--confirm-staging-candidate-write and reuses the M10B-1 workspace only.
No DB, embeddings, release qualification, scheduler or canonical promotion.
"""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from m10_candidate_intake_v1 import STATE_ROOT, inspect_batch, sha_file, validate_root
import m10b1_isolated_candidate_v1 as isolated
import m10b2a_candidate_lexical_v1 as lexical

VERSION = "beta-drive-isolated-candidate-validation-v1"
SOURCES = frozenset({"BD_PNAP_APP145", "BD_PNAP_APP149"})
BINDING_KEYS = ("candidate_id", "candidate_sha256", "reference_sha256_before",
                "monitor_output_sha256", "monitor_run_id", "batch_timestamp",
                "trusted_identity")


def binding(plan):
    return {key: plan[key] for key in BINDING_KEYS}


def read_existing_drive_candidate(plan):
    """Read only the fixed, hash-addressed remote object. No writer API calls."""
    import beta_stage_monitor_candidate_v1 as handoff
    source_id, expected = plan["source_id"], plan["candidate_sha256"]
    isolated.need(source_id in SOURCES and handoff.SHA.fullmatch(expected),
                  "unsafe_drive_candidate_identity")
    expected_path = handoff.PREFIX + source_id + "/" + expected + ".pdf"
    isolated.need(plan["drive_remote"] == handoff.REMOTE
                  and plan["drive_path"] == expected_path,
                  "unsafe_drive_candidate_destination")
    local = Path(plan["candidate_path"])
    before = handoff.file_sha(local)
    isolated.need(before == (plan["candidate_size_bytes"], expected),
                  "candidate_changed_before_drive_readback")
    try:
        with tempfile.TemporaryDirectory(prefix="jason-beta-candidate-readback-") as temp:
            copied = Path(temp) / "remote-copy.pdf"
            # --max-size prevents an unexpectedly huge remote object being copied.
            # A skipped/missing object yields no PDF and fails the checksum gate.
            subprocess.run([
                "rclone", "copyto", handoff.REMOTE + expected_path, str(copied),
                "--max-size", str(handoff.MAX_PDF_BYTES), "--retries", "1",
                "--low-level-retries", "1", "--contimeout", "10s", "--timeout", "20s",
            ], check=True, capture_output=True, timeout=60)
            actual = handoff.file_sha(copied)
    except (OSError, subprocess.SubprocessError):
        # Never echo raw rclone stderr (may contain private provider diagnostics).
        raise isolated.CandidateError("drive_readback_unavailable") from None
    isolated.need(actual == before, "drive_readback_sha_or_size_mismatch")
    isolated.need(handoff.file_sha(local) == before,
                  "candidate_changed_during_drive_readback")
    return {"sha256": actual[1], "bytes": actual[0],
            "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def run(summary, source_id, *, state_root=STATE_ROOT,
        workspace_root=isolated.WORKSPACE_ROOT, verify_drive=False, validate=False):
    report = {
        "version": VERSION, "source_id": source_id, "environment": "staging",
        "status": "BLOCKED", "reasons": [], "mode": (
            "validate" if validate else "verify-drive" if verify_drive else "plan"),
        "production_access": False, "production_write": False,
        "write_authorized": False, "canonical_promoted": False,
        "accepted_reference_advanced": False, "canonical_knowledge_updated": False,
        "shared_db_access": False, "model_api_used": False, "drive_write": False,
        "candidate_workspace_write_requested": validate,
        "proof_written": False, "drive_readback_verified": False,
        "retrieval_verified": False, "semantic_verified": False,
        "answer_verified": False, "gold_page_verified": None,
        "currentness": "NOT_VERIFIED",
    }
    try:
        isolated.need(source_id in SOURCES, "unsupported_beta_source")
        isolated.need(not validate or verify_drive, "validate_requires_drive_readback")
        root = validate_root(state_root)
        workspace = isolated.workspace_scope(workspace_root, root)
        summary = Path(summary)
        plan = isolated.process(summary, source_id, state_root=root,
                                workspace_root=workspace, validate=False)
        if plan["status"] == "NO_CHANGE":
            report["status"] = "NO_CHANGE"
            return report
        if plan["status"] != "READY_FOR_PARSE":
            report.update(status=plan["status"], reasons=plan["reasons"])
            return report
        locked = binding(plan)
        summary_sha = sha_file(summary)
        registry_sha = sha_file(isolated.REGISTRY)

        # Reuse the shipped handoff policy; no new source/version policy here.
        import beta_stage_monitor_candidate_v1 as handoff
        source = handoff.load_source(isolated.REGISTRY, source_id)
        item = inspect_batch(summary, state_root=root, source_id=source_id)["results"][0]
        isolated.need(item["status"] == "READY_FOR_STAGING_VALIDATION",
                      "candidate_intake_changed")
        candidate = Path(item["candidate"]["path"])
        drive_plan = handoff.plan_candidate(
            state_root=root, run_dir=candidate.parent, source_id=source_id, source=source)
        isolated.need(drive_plan["status"] == "READY_FOR_VERSIONED_DRIVE_STAGING"
                      and drive_plan["candidate_sha256"] == locked["candidate_sha256"]
                      and item["candidate_id"] == locked["candidate_id"]
                      and item["monitor_output_sha256"] == locked["monitor_output_sha256"]
                      and item["candidate"]["accepted_reference_record_sha256"]
                      == locked["reference_sha256_before"], "handoff_intake_mismatch")
        report.update(locked)
        report.update(summary_sha256=summary_sha, registry_sha256=registry_sha,
                      drive_remote=drive_plan["drive_remote"],
                      drive_path=drive_plan["drive_path"],
                      candidate_size_bytes=drive_plan["candidate_size_bytes"])

        def recheck():
            fresh = isolated.process(summary, source_id, state_root=root,
                                     workspace_root=workspace, validate=False)
            isolated.need(fresh["status"] == "READY_FOR_PARSE"
                          and binding(fresh) == locked
                          and sha_file(summary) == summary_sha
                          and sha_file(isolated.REGISTRY) == registry_sha,
                          "candidate_or_reference_changed_during_validation")

        recheck()
        if not verify_drive:
            report["status"] = "READY_FOR_DRIVE_READBACK"
            return report
        readback = read_existing_drive_candidate(drive_plan)
        isolated.need(readback["sha256"] == locked["candidate_sha256"]
                      and readback["bytes"] == drive_plan["candidate_size_bytes"],
                      "drive_readback_identity_mismatch")
        recheck()
        report.update(drive_readback=readback, drive_readback_verified=True)
        if not validate:
            report["status"] = "DRIVE_READBACK_VERIFIED_PARSE_PENDING"
            return report

        parsed = isolated.process(summary, source_id, state_root=root,
                                  workspace_root=workspace, validate=True)
        isolated.need(binding(parsed) == locked, "parse_binding_mismatch")
        if parsed["status"] != "PARSE_VERIFIED":
            report.update(status=parsed["status"], reasons=parsed["reasons"])
            recheck()
            return report
        result = lexical.run(source_id, locked["candidate_sha256"],
                             state_root=root, workspace_root=workspace)
        recheck()
        report.update(parse_status=parsed["status"], lexical_status=result["status"])
        if result["status"] == "BLOCKED":
            report.update(status="BLOCKED", reasons=result["reasons"])
            return report
        isolated.need(result.get("reference_sha256_before")
                      == result.get("reference_sha256_after")
                      == locked["reference_sha256_before"], "lexical_reference_mismatch")
        pdf, evidence_path = lexical.candidate_paths(
            workspace, source_id, locked["candidate_sha256"])
        evidence, evidence_sha = lexical.read_evidence(evidence_path)
        isolated.need(binding(evidence) == locked
                      and evidence_sha == result["m10b1_evidence_sha256"]
                      and sha_file(pdf) == locked["candidate_sha256"],
                      "parse_evidence_changed_or_from_another_monitor")
        report.update(
            status=("DRIVE_LINKED_LEXICAL_CANARY_PASSED"
                    if result["status"] == "LEXICAL_CANARY_PASSED"
                    else "LEXICAL_CANARY_FAILED"),
            reasons=result["reasons"], parse_status=parsed["status"],
            lexical_status=result["status"], m10b1_evidence_sha256=evidence_sha,
            manifest_sha256=result["manifest_sha256_actual"],
            reference_sha256_after=result["reference_sha256_after"],
            page_count=result["candidate_page_count"], chunk_count=result["chunk_count"],
            ranked_evidence=[{k: hit[k] for k in (
                "chunk_id", "page_number", "evidence_origin", "content_sha256")}
                for hit in result["ranked_evidence"]])
        return report
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        report.update(status="BLOCKED", reasons=["candidate_validation_failed:" + str(exc)])
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--verify-drive", action="store_true",
                        help="read existing versioned object only; no upload")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--confirm-staging-candidate-write", action="store_true")
    args = parser.parse_args(argv)
    if args.validate != args.confirm_staging_candidate_write or (
            args.validate and not args.verify_drive):
        parser.error("--validate requires --verify-drive and --confirm-staging-candidate-write")
    # CLI never accepts fixture roots, arbitrary registry, remote or DB endpoints.
    import beta_stage_monitor_candidate_v1 as handoff
    handoff.check_staging_checkout(Path(__file__).resolve().parent)
    result = run(args.summary, args.source, verify_drive=args.verify_drive,
                 validate=args.validate)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return (2 if result["status"] == "BLOCKED" else
            3 if result["status"] in {"REVIEW_REQUIRED", "LEXICAL_CANARY_FAILED"} else 0)


if __name__ == "__main__":
    sys.exit(main())
