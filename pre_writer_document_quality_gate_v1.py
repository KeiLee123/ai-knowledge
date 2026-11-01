#!/usr/bin/env python3
"""Source-scoped, fail-closed pre-side-effect document quality gate.

Applies to the existing official-source controller BEFORE it may initialize a
baseline, write Drive staging/canonical bytes, or invoke any database writer.
Existing unconfigured sources retain their historical behavior. No pass/
promotion decision is implemented: current evidence contracts always hold.
"""
import json
from pathlib import Path

MAX_REPORT_BYTES = 300_000


class DocumentQualityHold(RuntimeError):
    """Fail-closed condition; error text contains no document content."""


def enforce_pre_writer_quality_gate(source, report_path=None):
    """Block opted-in ingestion before ANY controller-side mutation.

    Source profile: document_quality_gate: {enabled: true}
    A report supplied explicitly also opts in and must never be ignored.
    Current reconciliation results do not contain a valid write-approval
    contract. Even matched mechanical evidence remains AUTO_HOLD.
    """
    if not isinstance(source, dict):
        raise DocumentQualityHold("QUALITY_GATE_SOURCE_INVALID")

    policy = source.get("document_quality_gate")
    if policy is None:
        enabled = False
    elif isinstance(policy, dict) and type(policy.get("enabled")) is bool:
        enabled = policy["enabled"]
    else:
        raise DocumentQualityHold("QUALITY_GATE_POLICY_INVALID")

    if not enabled and report_path is None:
        return "QUALITY_GATE_NOT_APPLICABLE_TO_LEGACY_SOURCE"

    if report_path is None:
        raise DocumentQualityHold("QUALITY_GATE_REPORT_REQUIRED_AUTO_HOLD")

    report_file = Path(report_path)
    if (not report_file.is_file() or report_file.is_symlink()
            or not 0 < report_file.stat().st_size <= MAX_REPORT_BYTES):
        raise DocumentQualityHold("QUALITY_GATE_REPORT_PATH_REFUSED")
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise DocumentQualityHold("QUALITY_GATE_REPORT_JSON_INVALID") from exc

    if not isinstance(report, dict):
        raise DocumentQualityHold("QUALITY_GATE_REPORT_SHAPE_INVALID")
    if report.get("version") != "document-ingest-evidence-reconciliation-v1":
        raise DocumentQualityHold("QUALITY_GATE_REPORT_CONTRACT_INVALID")
    if (report.get("staging_database_write_authorized") is not False
            or report.get("production_write_authorized") is not False):
        raise DocumentQualityHold("QUALITY_GATE_UNAUTHORIZED_PERMISSION_CLAIM")
    if (report.get("status") == "AUTO_HOLD_UNVERIFIED"
            and report.get("reconciliation") == "EVIDENCE_MATCHED_LIMITED"
            and report.get("reason_codes") == []):
        raise DocumentQualityHold("QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD")
    raise DocumentQualityHold("QUALITY_GATE_EVIDENCE_NOT_APPROVED")
