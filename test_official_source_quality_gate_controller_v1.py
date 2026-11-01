#!/usr/bin/env python3
"""Synthetic-only controller integration tests: no baseline, Drive or DB writes."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import process_official_source_staging_v1 as pipeline


class ReachedBaseline(Exception):
    pass


def run_isolated(source, evidence=None):
    """Exercise the REAL controller main, stopping at the first potential write."""
    with tempfile.TemporaryDirectory(prefix="quality-controller-test-") as temp:
        tmp = Path(temp)
        options = [
            "process_official_source_staging_v1.py",
            "SYNTHETIC_QUALITY_SOURCE",
            "--execute", "--confirm-staging-processing",
            "--registry", str(tmp / "synthetic-registry.yaml"),
            "--state-root", str(tmp / "state"),
            "--workdir", str(tmp / "work"),
        ]
        if evidence is not None:
            out = tmp / "evidence.json"
            out.write_text(json.dumps(evidence), encoding="utf-8")
            options += ["--document-quality-report-json", str(out)]

        with patch.object(sys, "argv", options), patch.object(
            pipeline, "verify_runtime", return_value={"environment": "synthetic"}
        ), patch.object(
            pipeline, "load_source", return_value=({}, source, {})
        ), patch.object(
            pipeline, "resolve_baseline", side_effect=ReachedBaseline
        ) as baseline, patch.object(
            pipeline, "download_and_route"
        ) as download, patch.object(
            pipeline, "ensure_remote_stage"
        ) as drive, patch.object(
            pipeline, "build_text_write_command"
        ) as text_writer, patch.object(
            pipeline, "build_multimodal_write_command"
        ) as mm_writer, patch.object(
            pipeline, "run_checked"
        ) as execute:
            try:
                pipeline.main()
            except SystemExit as exc:
                error = str(exc)
            except ReachedBaseline:
                error = "SYNTHETIC_LEGACY_BASELINE_REACHED"
            else:
                raise AssertionError("controller unexpectedly completed")

            if source.get("document_quality_gate", {}).get("enabled") is True or evidence is not None:
                assert not baseline.called, "AUTO_HOLD reached baseline write path"
                assert "QUALITY_GATE_" in error, error
                for operation in (download, drive, text_writer, mm_writer, execute):
                    assert not operation.called, "AUTO_HOLD reached downstream step"
            else:
                assert baseline.called, "historical ungated source did not reach its baseline"
            return error


def test_controller_gate():
    opted_in = {"document_quality_gate": {"enabled": True}}
    report = {
        "version": "document-ingest-evidence-reconciliation-v1",
        "status": "AUTO_HOLD_UNVERIFIED",
        "reconciliation": "EVIDENCE_MATCHED_LIMITED",
        "reason_codes": [],
        "staging_database_write_authorized": False,
        "production_write_authorized": False,
    }
    missing = run_isolated(opted_in)
    assert "QUALITY_GATE_REPORT_REQUIRED_AUTO_HOLD" in missing, missing
    matched = run_isolated(opted_in, report)
    assert "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD" in matched, matched

    forged = dict(report, staging_database_write_authorized=True)
    claimed = run_isolated(opted_in, forged)
    assert "QUALITY_GATE_UNAUTHORIZED_PERMISSION_CLAIM" in claimed, claimed

    unknown = dict(report, status="APPROVED")
    unknown_error = run_isolated(opted_in, unknown)
    assert "QUALITY_GATE_EVIDENCE_NOT_APPROVED" in unknown_error

    legacy = run_isolated({})
    assert legacy == "SYNTHETIC_LEGACY_BASELINE_REACHED", legacy

    # Even ungated source must not ignore explicitly provided evidence.
    legacy_with_report = run_isolated({}, report)
    assert "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD" in legacy_with_report

    # Prevent regression moving guard after the baseline entry point.
    import inspect
    source = inspect.getsource(pipeline.main)
    assert source.index("enforce_pre_writer_quality_gate(") < source.index(
        "baseline_state,") < source.index("ensure_remote_stage(")
    print("OFFICIAL SOURCE CONTROLLER PRE-WRITER GATE SYNTHETIC: PASS")


if __name__ == "__main__":
    test_controller_gate()
