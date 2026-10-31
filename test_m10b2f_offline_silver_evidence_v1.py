#!/usr/bin/env python3
"""M10B-2F isolated offline silver evidence regression tests."""
import builtins
import copy
import hashlib
import json
from unittest.mock import patch

import pymupdf

from m10b2f_offline_silver_evidence_v1 import (
    EvidenceContractError, SUITE_VERSION, SCOPE,
    verify_silver_candidate_suite,
)

PAGE1 = (
    "SYNTHETIC TEST DOCUMENT NOT OFFICIAL. "
    "The practice office keeps a blue notebook beside the printer "
    "for fictional inventory drills. Visitors can find a yellow sign "
    "near the entrance and a simple seating map on the back wall. "
    "These details exist only inside an invented test room."
)
PAGE2 = (
    "SYNTHETIC TEST DOCUMENT NOT OFFICIAL. "
    "The fictional drill guide states workers must report within 7 days "
    "during practice drills. The training visitor has a yellow sign "
    "near the exit for visual orientation. The practice office uses "
    "a blue notebook for all demo activities."
)


def pdf_bytes(pages=(PAGE1, PAGE2)):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        assert page.insert_textbox(
            pymupdf.Rect(40, 40, 560, 800),
            text, fontname="helv", fontsize=10) >= 0
    result = doc.tobytes()
    doc.close()
    return result


def make_suite(binary):
    sha = hashlib.sha256(binary).hexdigest()
    def candidate(cid, kind, page, quote, before, after, query):
        return {
            "case_id": cid, "case_type": kind,
            "source_id": "SYNTHETIC_APP149_NOT_OFFICIAL",
            "original_pdf_sha256": sha, "query": query,
            "expected_physical_pdf_page": page,
            "evidence_quote": quote,
            "context_before": before, "context_after": after,
        }
    return {
        "version": SUITE_VERSION,
        "scope": SCOPE,
        "suite_id": "m10b2f-fictional-pdf-v1",
        "source_id": "SYNTHETIC_APP149_NOT_OFFICIAL",
        "document_version": "synthetic-v1",
        "original_pdf_sha256": sha,
        "cases": [
            candidate(
                "SYN_LOW_P1", "POSITIVE", 1,
                "blue notebook beside the printer",
                "The practice office keeps a",
                "for fictional inventory drills.",
                "Where is the practice office notebook?"),
            candidate(
                "SYN_HIGH_P2", "POSITIVE", 2,
                "workers must report within 7 days",
                "The fictional drill guide states",
                "during practice drills.",
                "What must workers report within 7 days?"),
            candidate(
                "SYN_NEAR_MISS", "NEAR_MISS", 1,
                "yellow sign near the entrance",
                "Visitors can find a",
                "and a simple seating map on the back wall.",
                "Is this the same yellow sign as the training exit?"),
            candidate(
                "SYN_PARAPHRASE", "PARAPHRASE", 1,
                "blue notebook beside the printer",
                "The practice office keeps a",
                "for fictional inventory drills.",
                "Which colored recordbook is next to the copying device?"),
            candidate(
                "SYN_NEGATIVE", "NEGATIVE", None,
                None, None, None,
                "What is the official filing fee payable to the authority?"),
        ],
    }


def materials():
    binary = pdf_bytes()
    return binary, make_suite(binary)


def verify(binary, suite):
    return verify_silver_candidate_suite(binary, suite)


def by_id(result, cid):
    return next(r for r in result["cases"] if r["case_id"] == cid)


def rejects(call):
    try:
        call()
    except EvidenceContractError:
        return
    raise AssertionError("unsafe candidate was not blocked")


def test_baseline_risk_routing_and_counts():
    b, s = materials()
    r = verify(b, s)
    assert r["source_bytes_integrity_checked"] is True
    assert r["native_text_page_count"] == 2
    assert r["counts"] == {
        "MACHINE_EVIDENCE_CHECKED": 1,
        "HUMAN_REVIEW_REQUIRED": 4,
        "REJECTED_EVIDENCE_MISMATCH": 0,
    }
    assert by_id(r, "SYN_LOW_P1")["status"] == "MACHINE_EVIDENCE_CHECKED"
    assert by_id(r, "SYN_LOW_P1")["native_text_evidence_matched"]
    assert by_id(r, "SYN_HIGH_P2")["reason"] == "HIGH_IMPACT_WORDING_NEEDS_REVIEW"
    assert by_id(r, "SYN_NEAR_MISS")["reason"] == "NON_LITERAL_QUERY_SEMANTICS_NEED_REVIEW"
    assert by_id(r, "SYN_PARAPHRASE")["status"] == "HUMAN_REVIEW_REQUIRED"
    assert by_id(r, "SYN_NEGATIVE")["reason"] == "NEGATIVE_ABSENCE_NOT_PROVABLE"


def test_no_official_gold_or_ai_claim_even_on_machine_pass():
    r = verify(*materials())
    for row in r["cases"]:
        assert row["official_gold_approved"] is False
        assert row["human_reviewed"] is False
    assert r["official_source_verified"] is False
    assert r["official_document_verified"] is False
    assert r["gold_page_verified"] is None
    assert r["real_embedding_service_called"] is False
    assert r["semantic_verified"] is False
    assert r["answer_verified"] is False
    assert r["production_access"] is False
    assert r["production_write"] is False
    assert r["shared_db_access"] is False
    assert r["write_authorized"] is False
    assert r["artifact_written"] is False


def test_quote_mismatch_not_silent_pass():
    b, s = materials()
    s["cases"][0]["evidence_quote"] = "fictional golden notebook beside the printer"
    r = verify(b, s)
    assert by_id(r, "SYN_LOW_P1")["status"] == "REJECTED_EVIDENCE_MISMATCH"
    assert r["counts"]["REJECTED_EVIDENCE_MISMATCH"] == 1


def test_quote_on_wrong_page_is_rejected():
    b, s = materials()
    s["cases"][0]["expected_physical_pdf_page"] = 2
    r = verify(b, s)
    assert by_id(r, "SYN_LOW_P1")["reason"] == "QUOTE_PAGE_CONTEXT_MISSING_OR_AMBIGUOUS"


def test_wrong_adjacent_context_is_rejected():
    b, s = materials()
    s["cases"][0]["context_after"] = "for fictional banking drills."
    r = verify(b, s)
    assert by_id(r, "SYN_LOW_P1")["status"] == "REJECTED_EVIDENCE_MISMATCH"
    assert not by_id(r, "SYN_LOW_P1")["native_text_evidence_matched"]


def test_repeated_quote_on_two_pages_rejected_even_if_page_match():
    duplicate = PAGE1.replace("These details exist only inside an invented test room.",
                              "These details exist only inside an invented test room.")
    b = pdf_bytes((duplicate, duplicate))
    s = make_suite(b)
    s["cases"] = [s["cases"][0]]
    assert by_id(verify(b, s), "SYN_LOW_P1")["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_scanned_image_or_empty_native_page_not_qualified():
    b = pdf_bytes(("", PAGE2))
    s = make_suite(b)
    s["cases"] = [s["cases"][0]]
    r = verify(b, s)
    assert by_id(r, "SYN_LOW_P1")["reason"] == "PAGE_MISSING_OR_NO_NATIVE_TEXT"


def test_out_of_range_page_reported_not_gold():
    b, s = materials()
    s["cases"][0]["expected_physical_pdf_page"] = 3
    r = verify(b, s)
    assert by_id(r, "SYN_LOW_P1")["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_forged_human_review_approval_or_unexpected_fields_blocked():
    b, s = materials()
    s["cases"][0]["human_approved"] = True
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["review_status"] = "HUMAN_APPROVED_GOLD"
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["scope"] = "official_gold"
    rejects(lambda: verify(b, s))


def test_wrong_sha_or_binary_revision_blocked():
    b, s = materials()
    s["original_pdf_sha256"] = "f" * 64
    rejects(lambda: verify(b, s))
    b, s = materials()
    other_binary = b + b"\n%"
    rejects(lambda: verify(other_binary, s))


def test_cross_source_and_case_sha_blocked():
    b, s = materials()
    s["cases"][1]["source_id"] = "BD_PNAP_APP145"
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["cases"][1]["original_pdf_sha256"] = "f" * 64
    rejects(lambda: verify(b, s))


def test_duplicate_case_id_and_unsupported_case_type_blocked():
    b, s = materials()
    s["cases"][1]["case_id"] = s["cases"][0]["case_id"]
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["cases"][0]["case_type"] = "APPROVED"
    rejects(lambda: verify(b, s))


def test_negative_cannot_supply_evidence_or_claim_specific_page():
    b, s = materials()
    s["cases"][-1]["expected_physical_pdf_page"] = 2
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["cases"][-1]["evidence_quote"] = "There is no filing fee"
    rejects(lambda: verify(b, s))


def test_zero_based_page_and_string_number_rejected():
    b, s = materials()
    s["cases"][0]["expected_physical_pdf_page"] = 0
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["cases"][0]["expected_physical_pdf_page"] = "1"
    rejects(lambda: verify(b, s))


def test_no_pdfs_or_invalid_pdf_blob_rejected():
    _, suite = materials()
    rejects(lambda: verify(b"PDF header" * 100, suite))
    rejects(lambda: verify("not bytes", suite))


def test_not_allow_markup_in_source_identifiers_or_excerpt():
    b, s = materials()
    s["cases"][0]["case_id"] = "row|injection"
    rejects(lambda: verify(b, s))
    b, s = materials()
    s["cases"][0]["evidence_quote"] = "blue notebook | beside the printer"
    rejects(lambda: verify(b, s))


def test_deterministic_report_and_original_not_mutated():
    b, s = materials()
    prior = copy.deepcopy(s)
    a = verify(b, s)
    z = verify(b, s)
    assert a == z
    assert len(a["report_sha256"]) == 64
    assert prior == s
    assert a["pdf_sha256"] == hashlib.sha256(b).hexdigest()


def test_report_contains_no_raw_queries_quote_context_or_document_text():
    r = verify(*materials())
    packed = json.dumps(r, ensure_ascii=False)
    for secret in (
        "blue notebook beside the printer",
        "fictional inventory drills",
        "Where is the practice office notebook?",
        "SYNTHETIC TEST DOCUMENT NOT OFFICIAL",
        "The fictional drill guide states",
        '"official_gold_approved": true',
        '"semantic_verified": true',
    ):
        assert secret not in packed, secret


def test_no_disk_network_subprocess_io_during_verification():
    b, s = materials()
    with patch.object(builtins, "open",
                      side_effect=AssertionError("filesystem forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("network forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("socket forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("subprocess forbidden")):
        report = verify(b, s)
    assert report["case_count"] == 5


def main():
    tests = [
        test_baseline_risk_routing_and_counts,
        test_no_official_gold_or_ai_claim_even_on_machine_pass,
        test_quote_mismatch_not_silent_pass,
        test_quote_on_wrong_page_is_rejected,
        test_wrong_adjacent_context_is_rejected,
        test_repeated_quote_on_two_pages_rejected_even_if_page_match,
        test_scanned_image_or_empty_native_page_not_qualified,
        test_out_of_range_page_reported_not_gold,
        test_forged_human_review_approval_or_unexpected_fields_blocked,
        test_wrong_sha_or_binary_revision_blocked,
        test_cross_source_and_case_sha_blocked,
        test_duplicate_case_id_and_unsupported_case_type_blocked,
        test_negative_cannot_supply_evidence_or_claim_specific_page,
        test_zero_based_page_and_string_number_rejected,
        test_no_pdfs_or_invalid_pdf_blob_rejected,
        test_not_allow_markup_in_source_identifiers_or_excerpt,
        test_deterministic_report_and_original_not_mutated,
        test_report_contains_no_raw_queries_quote_context_or_document_text,
        test_no_disk_network_subprocess_io_during_verification,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2F OFFLINE SILVER EVIDENCE VERIFIER: PASS")


if __name__ == "__main__":
    main()
