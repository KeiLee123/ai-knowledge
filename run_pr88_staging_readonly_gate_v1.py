#!/usr/bin/env python3
"""PR #88 isolated VPS Staging read-only acceptance; NEVER authorizes ingestion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# Keep imported audit modules from writing __pycache__ into the Git worktree.
sys.dont_write_bytecode = True
from audit_document_ingest_quality_v1 import audit_pdf_batched
from verify_pdf_blank_pages_v1 import inspect_rendered_pages
from reconcile_document_ingest_evidence_v1 import reconcile

SOURCE_SHA256 = "6a506fb13e4c8f294268cdcb64aa89e4133dc26c63769b4b95b1a6b281c3c7ac"
SOURCE_SIZE = 1_016_489
SOURCE_PAGES = 298
RENDER_FIRST, RENDER_LAST = 151, 298


class StagingGateRefused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise StagingGateRefused(reason)


def git_output(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return result.stdout.strip()


def check_isolated_worktree(root, expected_head):
    root = root.resolve()
    require(root not in (Path("/opt/ai-knowledge"),
                         Path("/opt/ai-knowledge-staging")),
            "active_production_or_staging_checkout_refused")
    require(str(root).startswith(("/tmp/", "/var/tmp/")),
            "worktree_not_in_isolated_temp_root")
    require(re.fullmatch(r"[0-9a-f]{40}", expected_head) is not None,
            "head_pin_invalid")
    require(git_output(root, "rev-parse", "--show-toplevel") == str(root),
            "worktree_root_mismatch")
    require(git_output(root, "rev-parse", "HEAD") == expected_head,
            "worktree_commit_mismatch")
    branch = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "-q", "--short", "HEAD"],
        capture_output=True, text=True, check=False, timeout=15,
    )
    require(branch.returncode == 1, "active_branch_checkout_refused")
    require(git_output(root, "status", "--porcelain") == "",
            "worktree_not_clean")


def check_pdf(path):
    require(path.is_file() and not path.is_symlink(), "pdf_path_refused")
    require(path.stat().st_size == SOURCE_SIZE, "pdf_size_mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1_048_576), b""):
            digest.update(data)
    require(digest.hexdigest() == SOURCE_SHA256, "pdf_sha256_mismatch")


def check_report_dir(out, root):
    require(out.is_dir() and not out.is_symlink(), "report_dir_refused")
    real_out = out.resolve()
    require(str(real_out).startswith(("/tmp/", "/var/tmp/")),
            "report_dir_not_in_temp")
    require(not real_out.is_relative_to(root.resolve()),
            "report_dir_inside_worktree")
    require(real_out.stat().st_uid == os.geteuid(), "report_dir_owner_mismatch")
    require((real_out.stat().st_mode & 0o077) == 0, "report_dir_not_private")
    require(not any(real_out.iterdir()), "report_dir_not_empty")


def write_metadata(out, name, report):
    with (out / name).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def run_gate(root, pdf, out, expected_head):
    check_isolated_worktree(root, expected_head)
    check_report_dir(out, root)
    check_pdf(pdf)
    audit = audit_pdf_batched(
        pdf, drive_file_id="SHA_PINNED_READONLY_LOCAL_PDF",
        expected_size=SOURCE_SIZE, expected_sha256=SOURCE_SHA256,
    )
    write_metadata(out, "audit.json", audit)
    render = inspect_rendered_pages(
        pdf, expected_sha256=SOURCE_SHA256, expected_size=SOURCE_SIZE,
        expected_total_pages=SOURCE_PAGES,
        first_page=RENDER_FIRST, last_page=RENDER_LAST,
    )
    write_metadata(out, "render.json", render)
    combined = reconcile(audit, render)
    write_metadata(out, "reconciliation.json", combined)

    expected_pages = list(range(RENDER_FIRST, RENDER_LAST + 1))
    accepted = (
        audit.get("status") == "MECHANICAL_CHECKS_PASS_LIMITED"
        and audit.get("document", {}).get("physical_pages") == SOURCE_PAGES
        and audit.get("document", {}).get("extractor_blank_candidate_pages") == expected_pages
        and render.get("status") == "AUTO_HOLD_RENDERED_NONWHITE"
        and render.get("document", {}).get("nonwhite_detected_pages") == expected_pages
        and combined.get("reconciliation") == "EVIDENCE_MATCHED_LIMITED"
        and combined.get("status") == "AUTO_HOLD_UNVERIFIED"
        and combined.get("staging_database_write_authorized") is False
        and combined.get("production_write_authorized") is False
    )
    summary = {
        "status": ("STAGING_READONLY_MECHANICAL_EVIDENCE_MATCHED_AUTO_HOLD"
                   if accepted else "AUTO_HOLD_UNVERIFIED"),
        "repo_commit": expected_head, "source_sha256": SOURCE_SHA256,
        "physical_pages": SOURCE_PAGES,
        "extractor_blank_candidate_pages": len(expected_pages),
        "rendered_nonwhite_pages": len(render["document"]["nonwhite_detected_pages"]),
        "reconciliation": combined.get("reconciliation"),
        "reason_codes": combined.get("reason_codes"),
        "semantic_accuracy_verified": False,
        "database_roundtrip_verified": False,
        "staging_database_write_authorized": False,
        "production_write_authorized": False,
        "evidence_dir": str(out),
    }
    write_metadata(out, "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    require(accepted, "mechanical_evidence_not_matched_kept_on_hold")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    run_gate(Path(__file__).resolve().parent,
             args.pdf, args.report_dir, args.expected_head)


if __name__ == "__main__":
    try:
        main()
    except (StagingGateRefused, RuntimeError, OSError,
            ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit("PR88_STAGING_READONLY_REFUSED: " + str(exc)) from None
