#!/usr/bin/env python3
"""Synthetic-only regression for the isolated VPS read-only acceptance driver."""
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_pr88_staging_readonly_gate_v1 as gate


SHA = "c" * 40


def reports():
    pages = list(range(151, 299))
    audit = {
        "version": "document-ingest-quality-audit-v1",
        "audit_mode": "bounded_batches_full_document_coverage",
        "status": "MECHANICAL_CHECKS_PASS_LIMITED",
        "source": {
            "observed_sha256": gate.SOURCE_SHA256,
            "size_bytes": gate.SOURCE_SIZE,
            "expected_sha256_matched": True,
        },
        "document": {
            "physical_pages": gate.SOURCE_PAGES,
            "pages_covered": gate.SOURCE_PAGES,
            "coverage_complete": True,
            "extractor_blank_candidate_pages": pages,
            "no_native_text_class_counts": {"extractor_blank_candidate": len(pages)},
        },
        "issue_codes": [],
        "database_access": False,
        "production_write": False,
    }
    render = {
        "version": "pdf-blank-render-probe-v1",
        "status": "AUTO_HOLD_RENDERED_NONWHITE",
        "document": {
            "source_sha256": gate.SOURCE_SHA256,
            "source_size_bytes": gate.SOURCE_SIZE,
            "physical_pages": gate.SOURCE_PAGES,
            "first_page": 151, "last_page": 298,
            "pages_rendered": len(pages),
            "render_scale": 1.0, "render_dpi": 72,
            "grayscale": True, "annotations_rendered": True,
            "higher_resolution_render_verified": False,
            "independent_pdf_content_semantics_verified": False,
            "nonwhite_detected_pages": pages,
            "no_nonwhite_detected_count": 0,
            "all_rendered_pages_have_no_nonwhite": False,
        },
        "pages": [
            {"page": p, "nonwhite_pixels": 1, "pixel_count": 200}
            for p in pages
        ],
        "database_access": False,
        "production_write": False, "ocr_performed": False,
    }
    return audit, render


def fake_git(root, *args):
    if args == ("rev-parse", "--show-toplevel"):
        return str(root)
    if args == ("rev-parse", "HEAD"):
        return SHA
    if args == ("status", "--porcelain"):
        return ""
    raise AssertionError(args)


def test_guard_and_acceptance():
    with tempfile.TemporaryDirectory(prefix="pr88-test-") as tmp:
        base = Path(tmp)
        root = base / "detached-worktree"
        root.mkdir()
        output = base / "evidence"
        output.mkdir(mode=0o700)
        pdf = base / "test.pdf"
        pdf.write_bytes(b"synthetic")
        audit, render = reports()
        with patch.object(gate, "git_output", side_effect=fake_git), patch.object(
            gate.subprocess, "run", return_value=SimpleNamespace(returncode=1)
        ), patch.object(gate, "check_pdf"), patch.object(
            gate, "audit_pdf_batched", return_value=audit
        ), patch.object(gate, "inspect_rendered_pages", return_value=render):
            gate.run_gate(root, pdf, output, SHA)
        summary = json.loads((output / "summary.json").read_text())
        assert summary["status"] == (
            "STAGING_READONLY_MECHANICAL_EVIDENCE_MATCHED_AUTO_HOLD")
        assert summary["staging_database_write_authorized"] is False
        assert summary["production_write_authorized"] is False
        assert json.loads((output / "reconciliation.json").read_text())[
            "status"] == "AUTO_HOLD_UNVERIFIED"
        assert sorted(f.name for f in output.iterdir()) == [
            "audit.json", "reconciliation.json", "render.json", "summary.json",
        ]

        output2 = base / "tampered-evidence"
        output2.mkdir(mode=0o700)
        tampered = copy.deepcopy(render)
        tampered["document"]["source_sha256"] = "f" * 64
        with patch.object(gate, "git_output", side_effect=fake_git), patch.object(
            gate.subprocess, "run", return_value=SimpleNamespace(returncode=1)
        ), patch.object(gate, "check_pdf"), patch.object(
            gate, "audit_pdf_batched", return_value=audit
        ), patch.object(gate, "inspect_rendered_pages", return_value=tampered):
            try:
                gate.run_gate(root, pdf, output2, SHA)
            except gate.StagingGateRefused as exc:
                assert "mechanical_evidence_not_matched" in str(exc)
            else:
                raise AssertionError("mismatched PDF identity must not pass")
        bad = json.loads((output2 / "summary.json").read_text())
        assert bad["status"] == "AUTO_HOLD_UNVERIFIED"
        assert bad["staging_database_write_authorized"] is False

        try:
            gate.check_isolated_worktree(root, "0" * 40)
        except gate.StagingGateRefused as exc:
            assert "worktree_commit_mismatch" in str(exc)
        else:
            raise AssertionError("wrong PR head accepted")

        try:
            gate.check_pdf(pdf)
        except gate.StagingGateRefused as exc:
            assert "pdf_size_mismatch" in str(exc)
        else:
            raise AssertionError("wrong PDF accepted")

        public = base / "public"
        public.mkdir(mode=0o755)
        try:
            gate.check_report_dir(public, root)
        except gate.StagingGateRefused as exc:
            assert "report_dir_not_private" in str(exc)
        else:
            raise AssertionError("world-readable reports accepted")

    print("PR88 READONLY STAGING DRIVER SYNTHETIC CONTRACT: PASS")


if __name__ == "__main__":
    test_guard_and_acceptance()
