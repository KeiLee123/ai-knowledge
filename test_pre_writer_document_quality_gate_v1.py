#!/usr/bin/env python3
"""Synthetic pre-writer quality gate regression; does not invoke writers or DB."""
import json
import tempfile
from pathlib import Path

from pre_writer_document_quality_gate_v1 import (
    DocumentQualityHold, enforce_pre_writer_quality_gate,
)


def refuses(source, report, reason):
    try:
        enforce_pre_writer_quality_gate(source, report)
    except DocumentQualityHold as exc:
        assert str(exc) == reason, (reason, str(exc))
        return
    raise AssertionError("pre-writer gate unexpectedly accepted input")


def test_pre_writer_gate():
    historical = {}
    assert enforce_pre_writer_quality_gate(historical) == (
        "QUALITY_GATE_NOT_APPLICABLE_TO_LEGACY_SOURCE")
    assert enforce_pre_writer_quality_gate({
        "document_quality_gate": {"enabled": False},
    }) == "QUALITY_GATE_NOT_APPLICABLE_TO_LEGACY_SOURCE"

    source = {"document_quality_gate": {"enabled": True}}
    refuses(source, None, "QUALITY_GATE_REPORT_REQUIRED_AUTO_HOLD")
    refuses({"document_quality_gate": {"enabled": "true"}}, None,
            "QUALITY_GATE_POLICY_INVALID")
    refuses(source, "/tmp/this-should-not-exist-quality-report.json",
            "QUALITY_GATE_REPORT_PATH_REFUSED")

    evidence = {
        "version": "document-ingest-evidence-reconciliation-v1",
        "status": "AUTO_HOLD_UNVERIFIED",
        "reconciliation": "EVIDENCE_MATCHED_LIMITED",
        "reason_codes": [],
        "source_sha256": "a" * 64,
        "staging_database_write_authorized": False,
        "production_write_authorized": False,
    }
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "report.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        refuses(source, path, "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD")
        # Even a historically unconfigured source may not silently ignore a
        # report explicitly supplied by an operator.
        refuses(historical, path, "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD")

        changed = dict(evidence, status="UNRECOGNIZED_APPROVED")
        path.write_text(json.dumps(changed), encoding="utf-8")
        refuses(source, path, "QUALITY_GATE_EVIDENCE_NOT_APPROVED")

        changed = dict(evidence, staging_database_write_authorized=True)
        path.write_text(json.dumps(changed), encoding="utf-8")
        refuses(source, path, "QUALITY_GATE_UNAUTHORIZED_PERMISSION_CLAIM")

        path.write_text("{", encoding="utf-8")
        refuses(source, path, "QUALITY_GATE_REPORT_JSON_INVALID")

        path.write_bytes(b"x" * 300_001)
        refuses(source, path, "QUALITY_GATE_REPORT_PATH_REFUSED")

    print("PRE-WRITER QUALITY GATE SYNTHETIC CONTRACT: PASS")


if __name__ == "__main__":
    test_pre_writer_gate()
