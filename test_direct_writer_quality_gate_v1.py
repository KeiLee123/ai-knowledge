#!/usr/bin/env python3
"""Mocked, synthetic direct writer guards; no network, file ingest or DB I/O."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import ingest_canonical_text_staging_v1 as text_writer
import run_multimodal_canary_v2 as multimodal
from pre_writer_document_quality_gate_v1 import (
    DocumentQualityHold, registry_has_quality_gated_sources,
)


class BaselineReached(RuntimeError):
    pass


def fake_registry(opted):
    return {
        "source_registry_version": 1,
        "sources": {
            "SYNTHETIC_SOURCE": {
                "enabled": True,
                "document_quality_gate": {"enabled": opted},
            },
        },
    }


def test_policy_reader():
    assert registry_has_quality_gated_sources(fake_registry(False)) is False
    assert registry_has_quality_gated_sources(fake_registry(True)) is True
    bad = fake_registry(False)
    bad["sources"]["SYNTHETIC_SOURCE"]["document_quality_gate"]["enabled"] = "yes"
    try:
        registry_has_quality_gated_sources(bad)
    except DocumentQualityHold as exc:
        assert str(exc) == "QUALITY_GATE_POLICY_INVALID"
    else:
        raise AssertionError("invalid registry accepted")


def run_text_writer(opted, extra_args=None, evidence=None):
    source = fake_registry(opted)["sources"]["SYNTHETIC_SOURCE"]
    with tempfile.TemporaryDirectory(prefix="direct-text-test-") as folder:
        args = [
            "ingest_canonical_text_staging_v1.py", "SYNTHETIC_SOURCE",
            "--write", "--confirm-staging-write",
        ] + (extra_args or [])
        if evidence is not None:
            report = Path(folder) / "report.json"
            report.write_text(json.dumps(evidence), encoding="utf-8")
            args.extend(["--document-quality-report-json", str(report)])

        with patch.object(sys, "argv", args), patch.object(
            text_writer, "verify_runtime", return_value={"guard_ok": True}
        ), patch.object(
            text_writer, "load_registry", return_value=fake_registry(opted)
        ), patch.object(
            text_writer, "resolve_text_source", return_value=(source, {}, {})
        ), patch.object(
            text_writer, "load_expected_baseline", side_effect=BaselineReached
        ) as baseline, patch.object(
            text_writer, "download_canonical"
        ) as download, patch.object(
            text_writer, "execute_transaction"
        ) as sql, patch.object(
            text_writer, "precompute_embeddings"
        ) as embedding:
            try:
                text_writer.main()
            except SystemExit as exc:
                result = str(exc)
            else:
                raise AssertionError("synthetic text writer did not stop")
            for op in (download, sql, embedding):
                assert not op.called, "Writer reached a side-effecting step"
            if opted or evidence is not None:
                assert "QUALITY_GATE_" in result, result
                assert not baseline.called, "Writer read baseline before HOLD"
            else:
                assert baseline.called
            return result


def run_multimodal_writer(opted, *, verify_only=False):
    with tempfile.TemporaryDirectory(prefix="direct-multimodal-test-") as folder:
        source = Path(folder) / "synthetic.pdf"
        source.write_bytes(b"synthetic-test-input-not-a-real-pdf")
        argv = ["run_multimodal_canary_v2.py"]
        if verify_only:
            argv.append("--verify-only")
        else:
            argv.extend([
                str(source), "--title", "synthetic",
                "--domain", "testing", "--topic", "testing",
                "--document-type", "synthetic",
                "--write", "--confirm-staging-write",
            ])
        with patch.object(sys, "argv", argv), patch.object(
            multimodal, "verify_runtime", return_value={"guard_ok": True}
        ), patch.object(
            multimodal.registry_detector, "load_registry",
            return_value=fake_registry(opted)
        ) as registry, patch.object(
            multimodal, "build_orchestrator_command",
            return_value=["synthetic-orchestrator"]
        ) as command, patch.object(multimodal, "run_checked") as run:
            try:
                multimodal.main()
            except DocumentQualityHold as exc:
                blocked = str(exc)
            else:
                blocked = None

            if verify_only:
                assert blocked is None
                assert not registry.called
                assert not command.called and not run.called
            elif opted:
                assert blocked == (
                    "QUALITY_GATE_UNATTRIBUTABLE_DIRECT_MULTIMODAL_WRITE_AUTO_HOLD")
                assert registry.called
                assert not command.called and not run.called
            else:
                assert blocked is None
                assert registry.called
                assert command.called and run.call_count == 1


def test_direct_writers():
    test_policy_reader()
    absent = run_text_writer(True)
    assert "QUALITY_GATE_REPORT_REQUIRED_AUTO_HOLD" in absent
    matched = {
        "version": "document-ingest-evidence-reconciliation-v1",
        "status": "AUTO_HOLD_UNVERIFIED",
        "reconciliation": "EVIDENCE_MATCHED_LIMITED",
        "reason_codes": [],
        "staging_database_write_authorized": False,
        "production_write_authorized": False,
    }
    stopped = run_text_writer(True, evidence=matched)
    assert "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD" in stopped
    tampered = dict(matched, staging_database_write_authorized=True)
    assert "QUALITY_GATE_UNAUTHORIZED_PERMISSION_CLAIM" in (
        run_text_writer(True, evidence=tampered))
    assert "QUALITY_GATE_REGISTRY_OVERRIDE_REFUSED" in (
        run_text_writer(True, extra_args=["--registry", "/tmp/untrusted-registry.yaml"]))
    legacy = run_text_writer(False)
    assert "BaselineReached" in legacy, legacy
    assert "QUALITY_GATE_MECHANICAL_MATCH_STILL_AUTO_HOLD" in (
        run_text_writer(False, evidence=matched))

    run_multimodal_writer(True)
    run_multimodal_writer(False)
    run_multimodal_writer(True, verify_only=True)
    print("DIRECT TEXT + MULTIMODAL WRITER QUALITY-GATE SYNTHETIC: PASS")


if __name__ == "__main__":
    test_direct_writers()
