#!/usr/bin/env python3
"""Gate 3D-D1: one-shot public-source Hermes reliability observation.

Each --run-once makes AT MOST ONE delegated 3D-C DeepSeek trial, with NO
automatic retry. No raw model answer, tool output, credentials, or transcripts
are printed or persisted by this driver. Its only output is safe JSON metadata.
The existing isolated Gate 3D-C enforces the actual evidence safety contract.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

REPO = Path("/opt/ai-knowledge-staging")
GATE_SHELL = REPO / "scripts" / "hermes_gate3dc_isolated_chat_staging.sh"
VERSION = "hermes-gate3dd1-observation-v0.1"
MAX_CAPTURE_CHARS = 100_000
MIN_SAMPLE = 3
REQUIRED = {
    "preflight": (
        "APP145/APP149 eight-chunk public canary: VERIFIED",
        "Non-root Hermes MCP Registry: PASS (1 direct tool, bridge off, no provider)",
        "GATE 3D-C PRE-FLIGHT PASS (NO MODEL CALL)",
        "Isolated test profile cleaned; existing Hermes config unchanged",
    ),
    "run_once": (
        "APP145/APP149 eight-chunk public canary: VERIFIED",
        "Non-root Hermes MCP Registry: PASS (1 direct tool, bridge off, no provider)",
        "Chat exit code: 0",
        "Evidence fingerprint: official_evidence_fingerprint_matched",
        "Actual MCP dispatch: mcp_tool_call_and_result_proven",
        "GATE 3D-C MCP CHAT: SOURCE FINGERPRINT AND TOOL DISPATCH PASS",
        "Legal accuracy and source currentness: HUMAN REVIEW REQUIRED",
        "Isolated test profile cleaned; existing Hermes config unchanged",
    ),
}
KNOWN_TRACE_FAILURES = frozenset((
    "hermes_session_db_missing", "hermes_session_trace_unavailable",
    "tool_calls_malformed", "unexpected_tool_invoked",
    "tool_arguments_invalid", "unexpected_tool_arguments",
    "tool_call_id_invalid", "no_unique_approved_mcp_call",
    "mcp_tool_result_missing_or_duplicate", "tool_result_name_mismatch",
    "mcp_tool_result_not_approved_snapshot",
))
KNOWN_REASONS = KNOWN_TRACE_FAILURES | frozenset((
    "preflight_failed", "gate_markers_missing", "gate_process_failed",
    "gate_stopped", "capture_oversize", "trial_timeout",
    "staging_revision_unavailable",
))


def evaluate_gate(mode, exit_code, stdout):
    """Fail closed: exact gate-owned markers, never trust a generic PASS substring."""
    if mode not in REQUIRED:
        raise ValueError("unsupported_mode")
    if not isinstance(stdout, str) or len(stdout) > MAX_CAPTURE_CHARS:
        return False, "capture_oversize"
    lines = [line.strip() for line in stdout.splitlines()]
    if any(line.startswith("GATE 3D-C STOPPED:") for line in lines):
        return False, "gate_stopped"
    if exit_code != 0:
        for line in lines:
            prefix = "Actual MCP dispatch: "
            if line.startswith(prefix):
                reason = line[len(prefix):]
                if reason in KNOWN_TRACE_FAILURES:
                    return False, reason
        return False, "gate_process_failed"
    if any(lines.count(marker) != 1 for marker in REQUIRED[mode]):
        return False, "gate_markers_missing"
    return True, "verified"


def short_record(mode, commit, succeeded, reason, elapsed_ms, *, trial_id=None, at=None):
    if reason != "verified" and reason not in KNOWN_REASONS:
        raise ValueError("unsafe_reason")
    return {
        "schema_version": VERSION,
        "environment": "staging",
        "mode": mode,
        "trial_id": trial_id or uuid.uuid4().hex,
        "observed_at_utc": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "staging_commit": commit,
        "status": "PASS" if succeeded else "FAIL",
        "reason_code": reason,
        "elapsed_ms": elapsed_ms,
        "human_legal_review": "REQUIRED",
    }


def validate_record(obj):
    """Schema contract for user-supplied metadata ledger; no arbitrary text."""
    if not isinstance(obj, dict) or set(obj) != {
        "schema_version", "environment", "mode", "trial_id",
        "observed_at_utc", "staging_commit", "status",
        "reason_code", "elapsed_ms", "human_legal_review",
    }:
        raise ValueError("invalid_record_shape")
    if obj["schema_version"] != VERSION or obj["environment"] != "staging":
        raise ValueError("unexpected_record_scope")
    if obj["mode"] != "run_once" or obj["human_legal_review"] != "REQUIRED":
        raise ValueError("non_live_or_review_record")
    if not isinstance(obj["trial_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", obj["trial_id"]):
        raise ValueError("invalid_trial_id")
    if not isinstance(obj["staging_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", obj["staging_commit"]):
        raise ValueError("invalid_commit")
    if not isinstance(obj["observed_at_utc"], str):
        raise ValueError("invalid_timestamp")
    try:
        timestamp = datetime.fromisoformat(obj["observed_at_utc"])
    except ValueError:
        raise ValueError("invalid_timestamp") from None
    if timestamp.tzinfo is None:
        raise ValueError("timestamp_timezone_missing")
    if type(obj["elapsed_ms"]) is not int or not 0 <= obj["elapsed_ms"] <= 600_000:
        raise ValueError("invalid_elapsed")
    if obj["status"] == "PASS":
        if obj["reason_code"] != "verified":
            raise ValueError("inconsistent_pass")
    elif obj["status"] == "FAIL":
        if obj["reason_code"] not in KNOWN_REASONS:
            raise ValueError("invalid_fail_reason")
    else:
        raise ValueError("invalid_status")
    return obj


def summarize_records(records):
    if not 1 <= len(records) <= 100:
        raise ValueError("invalid_record_count")
    seen = set()
    commits = set()
    reasons = Counter()
    passes = 0
    for item in records:
        obj = validate_record(item)
        if obj["trial_id"] in seen:
            raise ValueError("duplicate_trial")
        seen.add(obj["trial_id"])
        commits.add(obj["staging_commit"])
        if obj["status"] == "PASS":
            passes += 1
        else:
            reasons[obj["reason_code"]] += 1
    if len(commits) != 1:
        raise ValueError("mixed_staging_commits")
    return {
        "schema_version": VERSION,
        "environment": "staging",
        "sample_count": len(records),
        "passed": passes,
        "failed": len(records) - passes,
        "observed_pass_rate": round(passes / len(records), 4),
        "sample_sufficient_for_d1_mvp": len(records) >= MIN_SAMPLE,
        "all_samples_passed": passes == len(records),
        "failure_reason_counts": dict(sorted(reasons.items())),
        "human_legal_review": "REQUIRED",
        "production_promotion": "NOT_AUTHORIZED",
    }


def read_ledger(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 60_000:
        raise ValueError("ledger_missing_or_oversized")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or len(lines) > 100 or any(len(line) > 600 for line in lines):
        raise ValueError("invalid_ledger_lines")
    return [json.loads(line) for line in lines]


def staging_commit():
    # The actual 3D-C shell independently checks clean staging, ancestor and
    # origin/staging HEAD before it permits a provider call.
    p = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    sha = p.stdout.strip()
    if p.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("staging_revision_unavailable")
    return sha


def execute(mode, *, runner=subprocess.run, commit=None):
    """One subprocess for 3D-C; even a failed response is never retried."""
    revision = commit if commit is not None else staging_commit()
    started = time.monotonic()
    try:
        result = runner(
            ["bash", str(GATE_SHELL), "--preflight" if mode == "preflight" else "--run"],
            cwd=str(REPO), capture_output=True, text=True,
            timeout=240, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        succeeded, reason = evaluate_gate(mode, result.returncode, result.stdout)
    except subprocess.TimeoutExpired:
        succeeded, reason = False, "trial_timeout"
    elapsed_ms = min(600_000, max(0, int((time.monotonic() - started) * 1000)))
    return short_record(mode, revision, succeeded, reason, elapsed_ms)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--preflight", action="store_true",
                          help="run isolated Hermes preflight without model/provider call")
    commands.add_argument("--run-once", action="store_true",
                          help="make exactly one public APP149 DeepSeek trial, no retries")
    commands.add_argument("--report", metavar="JSONL", type=Path,
                          help="summarize operator-collected metadata JSON lines; no model call")
    parser.add_argument("--ack-public-api-call", action="store_true",
                        help="required only with --run-once; acknowledges one paid model call")
    args = parser.parse_args(argv)
    if args.run_once != args.ack_public_api_call:
        parser.error("--run-once requires --ack-public-api-call (and only --run-once accepts it)")
    if args.report is not None:
        try:
            summary = summarize_records(read_ledger(args.report))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            print(json.dumps({"status": "REFUSED", "reason_code": "invalid_metadata_ledger"}))
            return 1
        print(json.dumps(summary, sort_keys=True))
        return 0
    mode = "run_once" if args.run_once else "preflight"
    try:
        record = execute(mode)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        # A failed host precondition must not trigger a model call.
        print(json.dumps({"status": "REFUSED", "reason_code": "staging_revision_unavailable"}))
        return 1
    print(json.dumps(record, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
