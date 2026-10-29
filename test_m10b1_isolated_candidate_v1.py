#!/usr/bin/env python3
"""M10B-1 offline synthetic PDF regression. No DB, Drive, external calls."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

from m10b1_isolated_candidate_v1 import process, main
from test_m10_candidate_intake_v1 import make, SOURCE


PDF_TEXT = (
    "BD PNAP APP-149 - local synthetic candidate test. "
    "First issue January 2025. This revision October 2026. "
    "Appointment of authorized signatory for minor works. "
    "The amended section defines appointment records, notification "
    "requirements, registered contractor responsibilities, signatory "
    "availability and review responsibilities. "
    "This document is synthetic test evidence and is not an official update."
)


def save(path, payload):
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def fixture(base, *, revision="2026", old_host="www.bd.gov.hk",
            old_authority="BD", old_code="APP-149", include_code=True):
    root, summary, records = make(base)
    item = records[SOURCE]
    candidate = item["candidate"]
    document = pymupdf.open()
    page = document.new_page()
    text = PDF_TEXT.replace("October 2026", "October " + revision)
    if not include_code:
        text = text.replace("APP-149", "UNRELATED-900")
    page.insert_textbox(pymupdf.Rect(50, 45, 555, 680), text,
                        fontsize=11, fontname="helv")
    document.save(candidate)
    document.close()

    new_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    monitor = item["monitor"]
    monitor["candidate_sha256"] = new_sha
    item["log"].write_text("START\n" + json.dumps(monitor) +
                           "\nSTATUS: CANDIDATE_NEW_VERSION\n", encoding="utf-8")
    old = json.loads(item["ref"].read_text())
    old["snapshot"].update({
        "source_family": "PNAP",
        "authority_code": old_authority,
        "document_code": old_code,
        "canonical_host": old_host,
        "normalized_content_fingerprint": "b" * 64,
        "metadata_fingerprint": "c" * 64,
        "issue_date": "2020-01",
        "revision_date": "2020-01",
    })
    save(item["ref"], old)
    workspace = base / "source-update-validation-staging"
    return root, summary, records, workspace


def call(root, summary, workspace, *, validate=False):
    return process(summary, SOURCE, state_root=root,
                   workspace_root=workspace, validate=validate)


def assert_no_external_calls(fn):
    with patch("urllib.request.urlopen",
               side_effect=AssertionError("network forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("subprocess forbidden")):
        return fn()


def test_plan_without_writes():
    with tempfile.TemporaryDirectory() as d:
        root, summary, records, workspace = fixture(Path(d))
        before = {str(f): (f.read_bytes(), f.stat().st_mtime_ns)
                  for f in root.rglob("*") if f.is_file()}
        result = assert_no_external_calls(
            lambda: call(root, summary, workspace))
        assert result["status"] == "READY_FOR_PARSE", result
        assert result["write_authorized"] is False
        assert not workspace.exists()
        assert before == {str(f): (f.read_bytes(), f.stat().st_mtime_ns)
                          for f in root.rglob("*") if f.is_file()}


def test_parse_verified_with_immutable_evidence():
    with tempfile.TemporaryDirectory() as d:
        root, summary, records, workspace = fixture(Path(d))
        result = assert_no_external_calls(
            lambda: call(root, summary, workspace, validate=True))
        assert result["status"] == "PARSE_VERIFIED", result
        assert result["policy_decision"] == "CANDIDATE_NEW_VERSION", result
        assert result["route"] == "legacy-v1"
        assert result["document_code_in_text"] is True
        assert result["retrieval_verified"] is False
        assert result["reference_sha256_before"] == result["reference_sha256_after"]
        assert result["write_authorized"] is False
        folder = workspace / "candidates" / SOURCE / result["candidate_sha256"]
        assert (folder / "candidate.pdf").is_file()
        proof = folder / "evidence.json"
        assert proof.is_file()
        before = (proof.read_bytes(), proof.stat().st_mtime_ns)
        rerun = call(root, summary, workspace, validate=True)
        assert rerun == result
        assert (proof.read_bytes(), proof.stat().st_mtime_ns) == before
        assert not (folder / ".lock").exists()


def test_no_change_creates_nothing():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _ = make(Path(d), decision="NO_CHANGE")
        workspace = Path(d) / "source-update-validation-staging"
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "NO_CHANGE"
        assert not workspace.exists()


def test_identity_missing_or_wrong_fails_closed():
    for patch_fields in ({"old_host": None}, {"old_host": "evil.example"},
                         {"old_authority": ""}, {"old_code": "APP-999"}):
        with tempfile.TemporaryDirectory() as d:
            root, summary, _, workspace = fixture(Path(d), **patch_fields)
            result = call(root, summary, workspace, validate=True)
            assert result["status"] == "BLOCKED", result
            assert not workspace.exists()


def test_candidate_tamper_fails_before_workspace_write():
    with tempfile.TemporaryDirectory() as d:
        root, summary, records, workspace = fixture(Path(d))
        records[SOURCE]["candidate"].write_bytes(b"%PDF-tampered")
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "BLOCKED", result
        assert not workspace.exists()


def test_nonpdf_m9_fixture_rejected():
    with tempfile.TemporaryDirectory() as d:
        root, summary, records = make(Path(d))
        workspace = Path(d) / "source-update-validation-staging"
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "BLOCKED"
        folder = workspace / "candidates" / SOURCE
        if folder.exists():
            assert not list(folder.glob("*/evidence.json"))


def test_multimodal_not_silently_downgraded():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _, workspace = fixture(Path(d))
        import route_document_v2
        actual = route_document_v2.assess_manifest

        def multimodal(manifest, *, allow_partial=False):
            result = actual(manifest, allow_partial=allow_partial)
            result["decision"]["recommended_pipeline"] = "multimodal-v2"
            return result

        with patch("route_document_v2.assess_manifest", side_effect=multimodal):
            result = call(root, summary, workspace, validate=True)
        assert result["status"] == "REVIEW_REQUIRED", result
        assert "multimodal_requires_ocr_vision_provenance" in result["reasons"]


def test_reference_drift_fails_closed():
    with tempfile.TemporaryDirectory() as d:
        root, summary, items, workspace = fixture(Path(d))
        import extract_document_v2
        original = extract_document_v2.build_manifest

        def drifting(path):
            old = json.loads(items[SOURCE]["ref"].read_text())
            old["snapshot"]["metadata_fingerprint"] = "d" * 64
            save(items[SOURCE]["ref"], old)
            return original(path)

        with patch("extract_document_v2.build_manifest", side_effect=drifting):
            result = call(root, summary, workspace, validate=True)
        assert result["status"] == "REVIEW_REQUIRED", result
        assert result["reasons"] == ["accepted_reference_drift"]


def test_pdf_identity_must_appear_in_document_text():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _, workspace = fixture(Path(d), include_code=False)
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "REVIEW_REQUIRED", result
        assert result["document_code_in_text"] is False
        assert result["reasons"] == ["document_code_not_found_in_pdf_text"]


def test_reference_parent_symlink_rejected():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _, workspace = fixture(Path(d))
        current = root / "version-snapshots" / "current"
        moved = current.with_name("moved")
        current.rename(moved)
        current.symlink_to(moved, target_is_directory=True)
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "BLOCKED", result
        assert not workspace.exists()


def test_workspace_symlink_rejected():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _, workspace = fixture(Path(d))
        outside = Path(d) / "outside"
        outside.mkdir()
        workspace.symlink_to(outside, target_is_directory=True)
        result = call(root, summary, workspace, validate=True)
        assert result["status"] == "BLOCKED"
        assert not list(outside.iterdir())


def test_validate_requires_both_explicit_flags():
    with tempfile.TemporaryDirectory() as d:
        root, summary, _, workspace = fixture(Path(d))
        try:
            main(["--summary", str(summary), "--source", SOURCE,
                  "--state-root", str(root), "--workspace-root", str(workspace),
                  "--validate"])
            assert False, "expected rejected confirmation"
        except SystemExit as exc:
            assert exc.code == 2
        assert not workspace.exists()


def main_test():
    tests = [
        test_plan_without_writes,
        test_parse_verified_with_immutable_evidence,
        test_no_change_creates_nothing,
        test_identity_missing_or_wrong_fails_closed,
        test_candidate_tamper_fails_before_workspace_write,
        test_nonpdf_m9_fixture_rejected,
        test_multimodal_not_silently_downgraded,
        test_reference_drift_fails_closed,
        test_pdf_identity_must_appear_in_document_text,
        test_reference_parent_symlink_rejected,
        test_workspace_symlink_rejected,
        test_validate_requires_both_explicit_flags,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-1 isolated candidate regression: PASS")


if __name__ == "__main__":
    main_test()
