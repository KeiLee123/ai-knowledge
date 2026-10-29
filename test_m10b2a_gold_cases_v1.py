#!/usr/bin/env python3
"""M10B-2A synthetic Gold Case evaluator regressions. Never official gold."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

from build_multimodal_chunks_v2 import build_chunks
from extract_document_v2 import build_manifest
from m10b2a_gold_cases_v1 import (
    GoldContractError, evaluate_synthetic_suite, read_gold_suite,
)
from m10b2a_candidate_lexical_v1 import rank_lexical

SOURCE = "BD_PNAP_APP149"
FIXTURE = "m10b2a-two-page-test-pdf-v1"
SUITE_FILE = Path(__file__).resolve().parent / "tests/fixtures/m10b2a_gold_synthetic_v1.json"

PAGE_ONE = (
    "SYNTHETIC DOCUMENT - NOT AN OFFICIAL PUBLICATION. "
    "BD PNAP APP-149 is a fabricated test case. "
    "An authorized signatory for minor works submits an appointment record. "
    "The authorized signatory must notify the office and maintain contractor "
    "records for this invented scenario. All procedural rules are fictional. "
    "These assertions must not be used as regulatory advice."
)
PAGE_TWO = (
    "SYNTHETIC DOCUMENT - NOT AN OFFICIAL PUBLICATION. "
    "This fabricated emergency guidance establishes a muster point for evacuation. "
    "The fictional evacuation coordinator informs the local team during "
    "emergency drills. The muster point is a rehearsal location only. "
    "No statements on this page describe actual APP-149 official requirements."
)


def make_pdf(path):
    pdf = pymupdf.open()
    for body in (PAGE_ONE, PAGE_TWO):
        page = pdf.new_page()
        result = page.insert_textbox(pymupdf.Rect(40, 45, 560, 700), body,
                                     fontsize=10, fontname="helv")
        assert result >= 0, "synthetic test page truncated"
    pdf.save(path)
    pdf.close()


def materials(folder):
    pdf = folder / "synthetic_not_official.pdf"
    make_pdf(pdf)
    manifest = build_manifest(pdf)
    chunks = build_chunks(manifest, target_chars=1800, overlap_chars=0)
    suite = read_gold_suite(SUITE_FILE)
    sha = manifest["source"]["sha256"]
    return pdf, manifest, chunks, suite, sha


def check(manifest, chunks, suite, sha, **kwargs):
    return evaluate_synthetic_suite(
        manifest, chunks, suite, source_id=kwargs.get("source_id", SOURCE),
        candidate_sha=kwargs.get("candidate_sha", sha),
        fixture_id=kwargs.get("fixture_id", FIXTURE),
        top_k=kwargs.get("top_k", 5),
    )


def must_reject(callback):
    try:
        callback()
    except GoldContractError:
        return
    raise AssertionError("expected gold contract to fail closed")


def test_two_page_synthetic_gold_passes_without_io():
    with tempfile.TemporaryDirectory() as tmp:
        pdf, manifest, chunks, suite, sha = materials(Path(tmp))
        before = (pdf.read_bytes(), pdf.stat().st_mtime_ns)
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("network forbidden")), \
             patch("subprocess.run",
                   side_effect=AssertionError("subprocess forbidden")):
            output = check(manifest, chunks, suite, sha)
        assert output["status"] == "SYNTHETIC_GOLD_CASES_PASSED", output
        assert [c["status"] for c in output["cases"]] == ["PASS"] * 3
        assert output["cases"][0]["retrieved_page_numbers"][0] == 1
        assert output["cases"][1]["retrieved_page_numbers"][0] == 2
        assert output["cases"][2]["retrieved_page_numbers"] == []
        assert output["gold_page_verified"] is None
        assert output["official_document_verified"] is False
        assert output["answer_verified"] is False
        assert output["shared_db_access"] is False
        assert output["write_authorized"] is False
        assert before == (pdf.read_bytes(), pdf.stat().st_mtime_ns)
        assert check(manifest, chunks, suite, sha) == output


def test_near_miss_negative_is_detected_as_failure():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        near = copy.deepcopy(suite)
        negative = near["cases"][2]
        negative["query"] = "authorized signatory jellyfish"
        output = check(manifest, chunks, near, sha)
        assert output["status"] == "SYNTHETIC_GOLD_CASES_FAILED", output
        assert output["cases"][2]["status"] == "FAIL"
        assert output["cases"][2]["reason"] == "negative_query_false_positive"


def test_wrong_gold_page_does_not_self_certify():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        suite["cases"][0]["expected_page_numbers"] = [2]
        output = check(manifest, chunks, suite, sha)
        assert output["status"] == "SYNTHETIC_GOLD_CASES_FAILED"
        assert output["cases"][0]["status"] == "FAIL"
        assert output["gold_page_verified"] is None


def test_wrong_gold_excerpt_causes_failure():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        suite["cases"][0]["expected_excerpt"] = "this fabricated gold does not exist"
        output = check(manifest, chunks, suite, sha)
        assert output["status"] == "SYNTHETIC_GOLD_CASES_FAILED"


def test_duplicate_case_and_empty_gold_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        invalid = copy.deepcopy(suite)
        invalid["cases"][1]["case_id"] = invalid["cases"][0]["case_id"]
        must_reject(lambda: check(manifest, chunks, invalid, sha))
        invalid = copy.deepcopy(suite)
        invalid["cases"][0]["expected_page_numbers"] = []
        must_reject(lambda: check(manifest, chunks, invalid, sha))
        invalid = copy.deepcopy(suite)
        invalid["cases"][2]["expected_excerpt"] = "fake positive"
        must_reject(lambda: check(manifest, chunks, invalid, sha))


def test_synthetic_cannot_be_upgraded_to_real_gold():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        for mutation in (
            {"scope": "official"},
            {"review_status": "human_verified"},
            {"gold_provenance": "ai_generated"},
        ):
            forged = copy.deepcopy(suite)
            forged.update(mutation)
            must_reject(lambda: check(manifest, chunks, forged, sha))
        forged = copy.deepcopy(suite)
        forged["cases"][0]["review_status"] = "human_verified"
        must_reject(lambda: check(manifest, chunks, forged, sha))


def test_wrong_candidate_sha_fixture_and_source_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        must_reject(lambda: check(manifest, chunks, suite, sha,
                                  candidate_sha="f" * 64))
        must_reject(lambda: check(manifest, chunks, suite, sha,
                                  fixture_id="another-fixture"))
        must_reject(lambda: check(manifest, chunks, suite, sha,
                                  source_id="BD_PNAP_APP145"))


def test_tampered_pages_and_content_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        wrong_page = copy.deepcopy(chunks)
        wrong_page[0]["page_start"] = 2
        must_reject(lambda: check(manifest, wrong_page, suite, sha))
        wrong_origin = copy.deepcopy(chunks)
        wrong_origin[0]["metadata"]["evidence_origin"] = "visual_understanding"
        must_reject(lambda: check(manifest, wrong_origin, suite, sha))
        wrong_content = copy.deepcopy(chunks)
        wrong_content[0]["content"] = "unrelated fabricated data"
        must_reject(lambda: check(manifest, wrong_content, suite, sha))


def test_out_of_range_gold_page_and_invalid_k_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest, chunks, suite, sha = materials(Path(tmp))
        wrong = copy.deepcopy(suite)
        wrong["cases"][0]["expected_page_numbers"] = [999]
        must_reject(lambda: check(manifest, chunks, wrong, sha))
        must_reject(lambda: check(manifest, chunks, suite, sha, top_k=0))


def test_fixture_read_and_synthetic_scope():
    suite = read_gold_suite(SUITE_FILE)
    assert suite["scope"] == "synthetic"
    assert "not official" in suite["notes"].lower()
    assert len(suite["cases"]) == 3
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.json"
        src.write_text(json.dumps(suite), encoding="utf-8")
        symlink = Path(tmp) / "symlink.json"
        symlink.symlink_to(src)
        must_reject(lambda: read_gold_suite(symlink))


def main():
    tests = [
        test_two_page_synthetic_gold_passes_without_io,
        test_near_miss_negative_is_detected_as_failure,
        test_wrong_gold_page_does_not_self_certify,
        test_wrong_gold_excerpt_causes_failure,
        test_duplicate_case_and_empty_gold_blocked,
        test_synthetic_cannot_be_upgraded_to_real_gold,
        test_wrong_candidate_sha_fixture_and_source_blocked,
        test_tampered_pages_and_content_blocked,
        test_out_of_range_gold_page_and_invalid_k_rejected,
        test_fixture_read_and_synthetic_scope,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2A synthetic gold contract regression: PASS")


if __name__ == "__main__":
    main()
