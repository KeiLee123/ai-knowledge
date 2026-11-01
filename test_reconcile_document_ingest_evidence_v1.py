#!/usr/bin/env python3
"""Offline, synthetic-only tests for fail-closed audit/render reconciliation."""
import copy
import json
import tempfile
from pathlib import Path

from reconcile_document_ingest_evidence_v1 import (
    EvidenceRefused, load_report, reconcile,
)


def fixtures():
    sha = "a" * 64
    audit = {
        "version": "document-ingest-quality-audit-v1",
        "audit_mode": "bounded_batches_full_document_coverage",
        "status": "MECHANICAL_CHECKS_PASS_LIMITED",
        "source": {
            "observed_sha256": sha, "size_bytes": 1024,
            "expected_sha256_matched": True,
        },
        "document": {
            "physical_pages": 5, "pages_covered": 5,
            "coverage_complete": True,
            "extractor_blank_candidate_pages": [3, 4, 5],
            "no_native_text_class_counts": {"extractor_blank_candidate": 3},
        },
        "issue_codes": [], "database_access": False, "production_write": False,
    }
    raster = {
        "version": "pdf-blank-render-probe-v1",
        "status": "AUTO_HOLD_RENDERED_NONWHITE",
        "document": {
            "source_sha256": sha, "source_size_bytes": 1024,
            "physical_pages": 5, "first_page": 3, "last_page": 5,
            "pages_rendered": 3, "render_scale": 1.0, "render_dpi": 72,
            "grayscale": True, "annotations_rendered": True,
            "higher_resolution_render_verified": False,
            "independent_pdf_content_semantics_verified": False,
            "nonwhite_detected_pages": [3, 5],
            "no_nonwhite_detected_count": 1,
            "all_rendered_pages_have_no_nonwhite": False,
        },
        "pages": [
            {"page": 3, "nonwhite_pixels": 23, "pixel_count": 100},
            {"page": 4, "nonwhite_pixels": 0, "pixel_count": 100},
            {"page": 5, "nonwhite_pixels": 6, "pixel_count": 100},
        ],
        "database_access": False, "production_write": False,
        "ocr_performed": False,
    }
    return audit, raster


def safe(report):
    assert report["status"] == "AUTO_HOLD_UNVERIFIED", report
    assert report["staging_database_write_authorized"] is False
    assert report["production_write_authorized"] is False
    assert report["semantic_blankness_verified"] is False
    assert report["database_roundtrip_verified"] is False


def mismatches(audit, raster, code):
    output = reconcile(audit, raster)
    safe(output)
    assert output["reconciliation"] == "EVIDENCE_MISMATCH_OR_MISSING", output
    assert code in output["reason_codes"], output


def test_reconciliation():
    audit, raster = fixtures()
    matched = reconcile(audit, raster)
    safe(matched)
    assert matched["reconciliation"] == "EVIDENCE_MATCHED_LIMITED", matched
    assert matched["reason_codes"] == []
    assert [p["diagnostic"] for p in matched["page_diagnostics"]] == [
        "RASTER_NONWHITE_AUTO_HOLD",
        "RASTER_WHITE_LIMITED_NOT_SEMANTIC_PROOF",
        "RASTER_NONWHITE_AUTO_HOLD",
    ]
    missing = reconcile(audit)
    mismatches(audit, None, "RASTER_REPORT_MISSING")
    safe(missing)

    def alter_render(edit, expected):
        changed = copy.deepcopy(raster)
        edit(changed)
        mismatches(audit, changed, expected)

    alter_render(lambda r: r["document"].update(source_sha256="b" * 64),
                 "RASTER_SOURCE_IDENTITY_MISMATCH")
    alter_render(lambda r: r["document"].update(first_page=2),
                 "RASTER_PAGE_COVERAGE_MISMATCH")
    alter_render(lambda r: r["pages"][0].update(page=2),
                 "RASTER_PAGE_COVERAGE_MISMATCH")
    alter_render(lambda r: r.update(status="RENDER_NO_NONWHITE_DETECTED_LIMITED"),
                 "RASTER_AGGREGATE_INCONSISTENT")
    alter_render(lambda r: r["pages"][0].update(nonwhite_pixels=-1),
                 "RASTER_PIXEL_METRICS_INVALID")
    alter_render(lambda r: r["document"].update(render_dpi=144),
                 "RASTER_METHOD_OR_SIDE_EFFECTS_INVALID")
    alter_render(lambda r: r.update(database_access=True),
                 "RASTER_METHOD_OR_SIDE_EFFECTS_INVALID")

    white = copy.deepcopy(raster)
    for page in white["pages"]:
        page["nonwhite_pixels"] = 0
    white["document"].update(
        nonwhite_detected_pages=[], no_nonwhite_detected_count=3,
        all_rendered_pages_have_no_nonwhite=True,
    )
    white["status"] = "RENDER_NO_NONWHITE_DETECTED_LIMITED"
    limited = reconcile(audit, white)
    safe(limited)
    assert limited["reconciliation"] == "EVIDENCE_MATCHED_LIMITED"
    assert all(p["diagnostic"] == "RASTER_WHITE_LIMITED_NOT_SEMANTIC_PROOF"
               for p in limited["page_diagnostics"])

    bad_audit = copy.deepcopy(audit)
    bad_audit["document"]["extractor_blank_candidate_pages"] = [2, 3, 5]
    mismatches(bad_audit, raster, "CANDIDATES_NONCONTIGUOUS_REQUIRE_SEPARATE_PROBES")
    bad_audit = copy.deepcopy(audit)
    bad_audit["document"]["extractor_blank_candidate_pages"] = [3, 3, 5]
    mismatches(bad_audit, raster, "CANDIDATE_PAGE_IDENTITIES_INVALID")
    bad_audit = copy.deepcopy(audit)
    bad_audit["document"]["pages_covered"] = 4
    mismatches(bad_audit, raster, "AUDIT_FULL_PAGE_COVERAGE_UNVERIFIED")
    print("test_reconciliation_matching_mismatch_and_permanent_auto_hold: PASS")


def test_bounded_json_io():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "synthetic.json"
        path.write_text(json.dumps(fixtures()[0]), encoding="utf-8")
        assert load_report(path)["version"] == "document-ingest-quality-audit-v1"
        for bad in ("[]", "{broken json"):
            path.write_text(bad, encoding="utf-8")
            try:
                load_report(path)
            except EvidenceRefused:
                pass
            else:
                raise AssertionError("invalid report accepted")
        path.write_bytes(b"x" * 300_001)
        try:
            load_report(path)
        except EvidenceRefused:
            pass
        else:
            raise AssertionError("oversized report accepted")
    print("test_bounded_json_io: PASS")


if __name__ == "__main__":
    test_reconciliation()
    test_bounded_json_io()
    print("DOCUMENT INGEST EVIDENCE RECONCILIATION OFFLINE CONTRACT: PASS")
