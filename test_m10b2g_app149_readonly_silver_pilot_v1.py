#!/usr/bin/env python3
"""M10B-2G: never use an official APP149 PDF as a CI fixture."""
import builtins
import copy
import hashlib
import json
from unittest.mock import patch

import pymupdf

from m10b2f_offline_silver_evidence_v1 import (
    EvidenceContractError, SCOPE, SUITE_VERSION,
)
from m10b2g_app149_readonly_silver_pilot_v1 import (
    CASE_RECORDS, EXPECTED_CASE_IDS, PINNED_DOCUMENT_VERSION,
    PINNED_PDF_SHA256, PINNED_PHYSICAL_PAGE_COUNT, PINNED_SOURCE_ID,
    build_app149_candidate_suite, run_app149_readonly_pilot,
    verify_pinned_silver_profile,
)


PAGES = (
    "SYNTHETIC DOCUMENT NOT OFFICIAL. A testing office keeps a green folder "
    "beside the cupboard for training exercises. The example room uses a "
    "paper label on every storage shelf.",
    "SYNTHETIC DOCUMENT NOT OFFICIAL. A test clerk must submit the record "
    "within 7 days. In this fictional training exercise the process does "
    "not create legal duties.",
    "SYNTHETIC DOCUMENT NOT OFFICIAL. In the training office a temporary "
    "helper cannot approve forms for filing. The helper may place the "
    "paper on a shelf.",
    "SYNTHETIC DOCUMENT NOT OFFICIAL. First training appendix has no "
    "official legal status.",
    "SYNTHETIC DOCUMENT NOT OFFICIAL. Second training appendix has no "
    "official legal status.",
)
SOURCE = "SYNTHETIC_APP149_NOT_OFFICIAL"


def make_pdf(pages=PAGES):
    pdf = pymupdf.open()
    for body in pages:
        page = pdf.new_page()
        if body:
            assert page.insert_textbox(
                pymupdf.Rect(40, 45, 560, 750),
                body, fontsize=10, fontname="helv") >= 0
    out = pdf.tobytes()
    pdf.close()
    return out


def synthetic_suite(pdf_bytes):
    sha = hashlib.sha256(pdf_bytes).hexdigest()

    def case(cid, typ, query, page, q, before, after):
        return {
            "case_id": cid, "case_type": typ, "query": query,
            "source_id": SOURCE, "original_pdf_sha256": sha,
            "expected_physical_pdf_page": page,
            "evidence_quote": q, "context_before": before,
            "context_after": after,
        }

    return {
        "version": SUITE_VERSION, "scope": SCOPE,
        "suite_id": "m10b2g-synthetic-pilot-v1",
        "source_id": SOURCE, "document_version": "synthetic-v1",
        "original_pdf_sha256": sha,
        "cases": [
            case("L01", "POSITIVE", "Where is the test folder?", 1,
                 "green folder beside the cupboard",
                 "A testing office keeps a", "for training exercises."),
            case("P01", "POSITIVE", "When must a test clerk submit a record?", 2,
                 "must submit the record within 7 days.",
                 "A test clerk", "In this fictional training exercise"),
            case("M01", "NEAR_MISS", "Can helper approve filing forms?", 3,
                 "cannot approve forms for filing.",
                 "In the training office a temporary helper",
                 "The helper may place the paper on a shelf."),
            case("N01", "NEGATIVE", "What fee applies for this legal filing?",
                 None, None, None, None),
        ],
    }


def run_synthetic(b=None, suite=None, expected_sha=None, pages=5):
    b = b if b is not None else make_pdf()
    suite = suite if suite is not None else synthetic_suite(b)
    return verify_pinned_silver_profile(
        b, suite,
        expected_sha=(hashlib.sha256(b).hexdigest()
                      if expected_sha is None else expected_sha),
        expected_page_count=pages, expected_source_id=SOURCE,
    )


def rejects(fn):
    try:
        fn()
    except EvidenceContractError:
        return
    raise AssertionError("expected validation failure")


def test_app149_identity_sha_and_inventory_are_pinned():
    suite = build_app149_candidate_suite()
    assert len(PINNED_PDF_SHA256) == 64
    assert PINNED_SOURCE_ID == "BD_PNAP_APP149"
    assert PINNED_DOCUMENT_VERSION == "2010-12"
    assert PINNED_PHYSICAL_PAGE_COUNT == 5
    assert suite["original_pdf_sha256"] == PINNED_PDF_SHA256
    assert len(suite["cases"]) == 5
    assert tuple(c["case_id"] for c in suite["cases"]) == EXPECTED_CASE_IDS
    assert suite["scope"] == SCOPE
    assert tuple(x[0] for x in CASE_RECORDS) == EXPECTED_CASE_IDS


def test_all_app149_cases_share_original_sha_and_source():
    s = build_app149_candidate_suite()
    for case in s["cases"]:
        assert case["source_id"] == PINNED_SOURCE_ID
        assert case["original_pdf_sha256"] == PINNED_PDF_SHA256
    assert [case["expected_physical_pdf_page"] for case in s["cases"]] == [
        1, 2, 2, 3, None
    ]


def test_app149_human_drafts_are_not_approved():
    s = build_app149_candidate_suite()
    assert {x["case_id"] for x in s["cases"][1:]} == {
        "APP149-DRAFT-P01", "APP149-DRAFT-P02",
        "APP149-DRAFT-M01", "APP149-DRAFT-N01",
    }
    assert s["cases"][-1]["case_type"] == "NEGATIVE"
    assert s["cases"][-1]["evidence_quote"] is None
    assert all("gold_approved" not in x and "review_status" not in x
               for x in s["cases"])


def test_real_app149_adapter_rejects_fictional_pdf():
    b = make_pdf()
    rejects(lambda: run_app149_readonly_pilot(b))
    assert hashlib.sha256(b).hexdigest() != PINNED_PDF_SHA256


def test_source_profile_baseline_synthetic_5_pages():
    r = run_synthetic()
    assert r["source_id"] == SOURCE
    assert r["native_text_page_count"] == 5
    assert r["counts"] == {
        "MACHINE_EVIDENCE_CHECKED": 1,
        "HUMAN_REVIEW_REQUIRED": 3,
        "REJECTED_EVIDENCE_MISMATCH": 0,
    }
    assert [x["status"] for x in r["cases"]] == [
        "MACHINE_EVIDENCE_CHECKED", "HUMAN_REVIEW_REQUIRED",
        "HUMAN_REVIEW_REQUIRED", "HUMAN_REVIEW_REQUIRED",
    ]


def test_synthetic_low_risk_match_not_official_gold():
    r = run_synthetic()
    assert r["cases"][0]["native_text_evidence_matched"]
    assert r["cases"][0]["status"] == "MACHINE_EVIDENCE_CHECKED"
    assert r["official_source_verified"] is False
    assert r["official_document_verified"] is False
    assert r["gold_page_verified"] is None
    assert r["real_embedding_service_called"] is False


def test_synthetic_deadline_routes_to_human():
    r = run_synthetic()
    assert r["cases"][1]["native_text_evidence_matched"]
    assert r["cases"][1]["reason"] == "HIGH_IMPACT_WORDING_NEEDS_REVIEW"


def test_synthetic_near_miss_and_negative_require_human():
    r = run_synthetic()
    assert r["cases"][2]["status"] == "HUMAN_REVIEW_REQUIRED"
    assert r["cases"][2]["reason"] == "NON_LITERAL_QUERY_SEMANTICS_NEED_REVIEW"
    assert r["cases"][3]["reason"] == "NEGATIVE_ABSENCE_NOT_PROVABLE"


def test_pdf_sha_mismatch_even_if_suite_is_self_consistent():
    a = make_pdf()
    b = make_pdf(tuple(reversed(PAGES)))
    suite = synthetic_suite(a)
    rejects(lambda: run_synthetic(b, suite, expected_sha=hashlib.sha256(a).hexdigest()))


def test_wrong_expected_page_count_fails_profile():
    rejects(lambda: run_synthetic(pages=4))
    rejects(lambda: run_synthetic(pages=6))


def test_source_id_profile_mismatch_is_blocked():
    b = make_pdf()
    s = synthetic_suite(b)
    s["source_id"] = "IMPERSONATED_SOURCE"
    rejects(lambda: run_synthetic(b, s))


def test_wrong_page_or_quote_do_not_machine_pass():
    b = make_pdf()
    s = synthetic_suite(b)
    s["cases"][0]["expected_physical_pdf_page"] = 2
    assert run_synthetic(b, s)["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"
    s = synthetic_suite(b)
    s["cases"][0]["evidence_quote"] = "fictional purple folder beside cupboard"
    assert run_synthetic(b, s)["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_wrong_context_or_quote_duplicate_fails():
    b = make_pdf()
    s = synthetic_suite(b)
    s["cases"][0]["context_after"] = "for other work."
    assert run_synthetic(b, s)["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"
    dup = make_pdf((PAGES[0], PAGES[0], *PAGES[2:]))
    s = synthetic_suite(dup)
    assert run_synthetic(dup, s)["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_cross_case_sha_and_gold_forgery_rejected():
    b = make_pdf()
    s = synthetic_suite(b)
    s["cases"][0]["original_pdf_sha256"] = "f" * 64
    rejects(lambda: run_synthetic(b, s))
    s = synthetic_suite(b)
    s["cases"][0]["official_gold_approved"] = True
    rejects(lambda: run_synthetic(b, s))


def test_negative_claiming_page_rejected():
    b = make_pdf()
    s = synthetic_suite(b)
    s["cases"][-1]["expected_physical_pdf_page"] = 5
    rejects(lambda: run_synthetic(b, s))


def test_missing_native_text_page_fails_case():
    b = make_pdf(("", *PAGES[1:]))
    s = synthetic_suite(b)
    assert run_synthetic(b, s)["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_deterministic_no_input_mutation():
    b = make_pdf()
    s = synthetic_suite(b)
    snapshot = copy.deepcopy(s)
    a = run_synthetic(b, s)
    z = run_synthetic(b, s)
    assert a == z
    assert s == snapshot
    assert len(a["report_sha256"]) == 64
    assert all(row["official_gold_approved"] is False for row in a["cases"])


def test_result_redacts_original_text():
    result = run_synthetic()
    text = json.dumps(result, ensure_ascii=False)
    for secret in (
        "green folder beside the cupboard", "test clerk",
        "Where is the test folder?", "SYNTHETIC DOCUMENT NOT OFFICIAL",
        "query_vector", '"gold_page_verified": true',
    ):
        assert secret not in text


def test_no_files_network_or_processes_in_verification():
    b = make_pdf()
    s = synthetic_suite(b)
    with patch.object(builtins, "open",
                      side_effect=AssertionError("disk forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("network forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("socket forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("process forbidden")):
        r = run_synthetic(b, s)
        rejects(lambda: run_app149_readonly_pilot(b))
    assert r["case_count"] == 4


def main():
    tests = [
        test_app149_identity_sha_and_inventory_are_pinned,
        test_all_app149_cases_share_original_sha_and_source,
        test_app149_human_drafts_are_not_approved,
        test_real_app149_adapter_rejects_fictional_pdf,
        test_source_profile_baseline_synthetic_5_pages,
        test_synthetic_low_risk_match_not_official_gold,
        test_synthetic_deadline_routes_to_human,
        test_synthetic_near_miss_and_negative_require_human,
        test_pdf_sha_mismatch_even_if_suite_is_self_consistent,
        test_wrong_expected_page_count_fails_profile,
        test_source_id_profile_mismatch_is_blocked,
        test_wrong_page_or_quote_do_not_machine_pass,
        test_wrong_context_or_quote_duplicate_fails,
        test_cross_case_sha_and_gold_forgery_rejected,
        test_negative_claiming_page_rejected,
        test_missing_native_text_page_fails_case,
        test_deterministic_no_input_mutation,
        test_result_redacts_original_text,
        test_no_files_network_or_processes_in_verification,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2G APP149 READ-ONLY SILVER PILOT SYNTHETIC REGRESSION: PASS")


if __name__ == "__main__":
    main()
