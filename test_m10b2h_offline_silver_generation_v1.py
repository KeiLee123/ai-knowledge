#!/usr/bin/env python3
"""M10B-2H regression: entirely fictional PDFs; no live/official Gold."""
import builtins
import copy
import hashlib
import json
from unittest.mock import patch

import pymupdf

from m10b2f_offline_silver_evidence_v1 import (
    EvidenceContractError, verify_silver_candidate_suite,
)
from m10b2h_offline_silver_generation_v1 import (
    METHOD, REPORT_SCOPE, build_generated_silver_suite,
    run_offline_silver_generation,
)

P1 = (
    "SYNTHETIC NONOFFICIAL TRAINING TEXT. Inside the quiet archive room "
    "volunteers arrange colorful notebooks and gentle flowers near the "
    "wide wooden windows. Visitors enjoy the peaceful gallery while "
    "careful helpers organize shelves of bright pencils and folded paper. "
    "The yellow basket beside the garden doorway contains soft brushes "
    "and a small collection of handmade bookmarks. Friendly guides "
    "describe the room as a comfortable space for study and conversation."
)
P2 = (
    "SYNTHETIC NONOFFICIAL TRAINING TEXT. The acting clerk must submit "
    "the attendance form within seven days before any scheduled drill. "
    "The supervisor is required to approve the special report and retain "
    "the signed records for the training office. An unrelated display "
    "beside the hallway contains green pictures and ordinary notebooks "
    "for visitors to view during the afternoon exhibition."
)


def make_pdf(pages=(P1, P2)):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            assert page.insert_textbox(
                pymupdf.Rect(30, 40, 560, 790), text,
                fontsize=10, fontname="helv") >= 0
    pdf = doc.tobytes()
    doc.close()
    return pdf


def args_for(pdf, **changes):
    kw = {
        "source_id": "SYNTHETIC_NOT_OFFICIAL",
        "document_version": "fictional-v1",
        "suite_id": "m10b2h-source-cloze-v1",
        "expected_sha256": hashlib.sha256(pdf).hexdigest(),
    }
    kw.update(changes)
    return kw


def run(pdf=None, **changes):
    pdf = pdf if pdf is not None else make_pdf()
    return run_offline_silver_generation(pdf, **args_for(pdf, **changes))


def rejects(fn):
    try:
        fn()
    except EvidenceContractError:
        return
    raise AssertionError("invalid generation was not rejected")


def test_baseline_end_to_end_generation_and_queue():
    r = run()
    assert r["generation_method"] == METHOD
    assert r["scope"] == REPORT_SCOPE
    assert r["case_count"] == 4
    assert r["native_page_count"] == 2
    assert r["generated_case_type"] == "POSITIVE_CONTEXT_CLOZE_ONLY"
    assert r["verification_counts"]["MACHINE_EVIDENCE_CHECKED"] >= 1
    assert r["verification_counts"]["HUMAN_REVIEW_REQUIRED"] >= 1
    assert r["verification_counts"]["REJECTED_EVIDENCE_MISMATCH"] == 0
    assert r["review_queue_count"] == len(r["review_queue"])


def test_generator_produces_exact_m10b2f_suite():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    assert suite["scope"] == "machine_evidence_candidate_only"
    assert suite["original_pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert len(suite["cases"]) == 4
    assert all(c["case_type"] == "POSITIVE" for c in suite["cases"])
    assert all("What wording follows this passage:" in c["query"]
               for c in suite["cases"])
    report = verify_silver_candidate_suite(pdf, suite)
    assert report["case_count"] == 4
    assert all(c["native_text_evidence_matched"] for c in report["cases"])


def test_case_ids_are_stable_page_pinned_and_unique():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    assert [x["case_id"] for x in suite["cases"]] == [
        "GEN_P001_C01", "GEN_P001_C02",
        "GEN_P002_C01", "GEN_P002_C02",
    ]
    assert [x["expected_physical_pdf_page"] for x in suite["cases"]] == [
        1, 1, 2, 2,
    ]


def test_high_impact_sentence_routed_to_human():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    verifier = verify_silver_candidate_suite(pdf, suite)
    assert any(x["status"] == "HUMAN_REVIEW_REQUIRED"
               and x["reason"] == "HIGH_IMPACT_WORDING_NEEDS_REVIEW"
               for x in verifier["cases"])
    assert any(x["route"] == "REQUIRED_HUMAN_REVIEW"
               for x in run(pdf)["review_queue"])


def test_generated_cases_are_not_independent_semantic_gold():
    r = run()
    assert r["generated_from_same_pdf_as_evidence"] is True
    assert r["independent_answer_correctness_verified"] is False
    assert r["official_source_verified"] is False
    assert r["gold_page_verified"] is None
    assert r["human_gold_cases_approved"] == 0
    assert r["human_reviewed"] is False
    assert r["semantic_verified"] is False
    assert "NOT independent" in r["notice"]


def test_queue_sample_requires_human_review_not_auto_approval():
    r = run(sample_percent=10)
    assert r["sampled_human_qa_count"] >= 1
    sampled = [q for q in r["review_queue"]
               if q["route"] == "SAMPLED_HUMAN_QA"]
    assert len(sampled) == r["sampled_human_qa_count"]
    assert all(q["priority"] == 2 for q in sampled)
    assert r["sample_statistics_validated"] is False
    assert r["human_gold_cases_approved"] == 0


def test_zero_percent_sample_does_not_drop_high_risk_cases():
    r = run(sample_percent=0)
    assert r["sampled_human_qa_count"] == 0
    assert r["required_human_review_count"] >= 1
    assert all(q["route"] != "SAMPLED_HUMAN_QA" for q in r["review_queue"])


def test_review_queue_priority_and_no_duplicate_case():
    r = run()
    ids = [q["case_id"] for q in r["review_queue"]]
    assert len(ids) == len(set(ids))
    assert [q["priority"] for q in r["review_queue"]] == sorted(
        q["priority"] for q in r["review_queue"])
    assert set(q["route"] for q in r["review_queue"]) <= {
        "REQUIRED_HUMAN_REVIEW", "EVIDENCE_REMEDIATION",
        "SAMPLED_HUMAN_QA",
    }


def test_repeated_text_does_not_generate_false_unique_evidence():
    pdf = make_pdf((P1, P1))
    rejects(lambda: run(pdf))


def test_empty_native_text_pdf_no_candidates():
    pdf = make_pdf(("", ""))
    rejects(lambda: run(pdf))


def test_wrong_expected_raw_sha_fails_before_generation():
    pdf = make_pdf()
    rejects(lambda: run(pdf, expected_sha256="f" * 64))


def test_changed_pdf_binary_requires_new_sha():
    pdf = make_pdf()
    stale = hashlib.sha256(pdf).hexdigest()
    changed = pdf + b"\n%"
    rejects(lambda: run(changed, expected_sha256=stale))


def test_missing_or_invalid_source_identity_fails_closed():
    pdf = make_pdf()
    rejects(lambda: run(pdf, source_id="BD_PNAP/APP149"))
    rejects(lambda: run(pdf, suite_id="with|pipe"))
    rejects(lambda: run(pdf, document_version=""))
    rejects(lambda: run(pdf, sample_seed="danger|bad"))


def test_reject_invalid_generation_limits_and_sample():
    pdf = make_pdf()
    rejects(lambda: run(pdf, max_cases=51))
    rejects(lambda: run(pdf, max_cases=0))
    rejects(lambda: run(pdf, max_per_page=4))
    rejects(lambda: run(pdf, max_per_page=0))
    rejects(lambda: run(pdf, max_per_page=True))
    rejects(lambda: run(pdf, sample_percent=101))
    rejects(lambda: run(pdf, sample_percent=True))


def test_case_budget_and_per_page_budget():
    pdf = make_pdf()
    r = run(pdf, max_cases=1, max_per_page=1)
    assert r["case_count"] == 1
    r = run(pdf, max_cases=4, max_per_page=1)
    assert r["case_count"] == 2


def test_verifier_rejects_tampered_generated_quote():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    suite["cases"][0]["evidence_quote"] = (
        "This fabricated legal excerpt was not actually there."
    )
    result = verify_silver_candidate_suite(pdf, suite)
    assert result["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_verifier_rejects_wrong_generated_page_context():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    suite["cases"][0]["expected_physical_pdf_page"] = 2
    result = verify_silver_candidate_suite(pdf, suite)
    assert result["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    suite["cases"][0]["context_before"] = "context deliberately wrong"
    result = verify_silver_candidate_suite(pdf, suite)
    assert result["cases"][0]["status"] == "REJECTED_EVIDENCE_MISMATCH"


def test_deterministic_report_and_sampling_seed():
    pdf = make_pdf()
    a = run(pdf, sample_seed="test-a")
    b = run(pdf, sample_seed="test-a")
    assert a == b
    assert len(a["report_sha256"]) == 64
    assert a["verifier_report_sha256"]
    z = run(pdf, sample_seed="test-b")
    assert z["sample_seed"] == "test-b"
    assert z["case_count"] == a["case_count"]


def test_no_raw_query_quote_pdf_words_in_public_report():
    r = run()
    packed = json.dumps(r, ensure_ascii=False)
    for phrase in (
        "Inside the quiet archive room",
        "colorful notebooks and gentle flowers",
        "What wording follows this passage:",
        "The acting clerk must submit",
        "paper label on every storage shelf",
        "evidence_quote", "context_before",
        '"official_source_verified": true',
        '"human_gold_cases_approved": 4',
    ):
        assert phrase not in packed, phrase


def test_only_positive_cloze_no_negative_or_near_miss_autogenerated():
    pdf = make_pdf()
    suite = build_generated_silver_suite(pdf, **args_for(pdf))
    assert {x["case_type"] for x in suite["cases"]} == {"POSITIVE"}
    assert all(x["expected_physical_pdf_page"] is not None for x in suite["cases"])
    assert "Official Gold" in run(pdf)["notice"]


def test_no_disk_network_process_or_model_calls():
    pdf = make_pdf()
    a = args_for(pdf)
    with patch.object(builtins, "open",
                      side_effect=AssertionError("filesystem forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("HTTP forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("network forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("process forbidden")):
        r = run_offline_silver_generation(pdf, **a)
    assert r["case_count"] == 4
    assert r["real_embedding_service_called"] is False
    assert r["shared_db_access"] is False
    assert r["production_access"] is False
    assert r["write_authorized"] is False
    assert r["artifact_written"] is False


def main():
    tests = [
        test_baseline_end_to_end_generation_and_queue,
        test_generator_produces_exact_m10b2f_suite,
        test_case_ids_are_stable_page_pinned_and_unique,
        test_high_impact_sentence_routed_to_human,
        test_generated_cases_are_not_independent_semantic_gold,
        test_queue_sample_requires_human_review_not_auto_approval,
        test_zero_percent_sample_does_not_drop_high_risk_cases,
        test_review_queue_priority_and_no_duplicate_case,
        test_repeated_text_does_not_generate_false_unique_evidence,
        test_empty_native_text_pdf_no_candidates,
        test_wrong_expected_raw_sha_fails_before_generation,
        test_changed_pdf_binary_requires_new_sha,
        test_missing_or_invalid_source_identity_fails_closed,
        test_reject_invalid_generation_limits_and_sample,
        test_case_budget_and_per_page_budget,
        test_verifier_rejects_tampered_generated_quote,
        test_verifier_rejects_wrong_generated_page_context,
        test_deterministic_report_and_sampling_seed,
        test_no_raw_query_quote_pdf_words_in_public_report,
        test_only_positive_cloze_no_negative_or_near_miss_autogenerated,
        test_no_disk_network_process_or_model_calls,
    ]
    for case in tests:
        case()
        print(case.__name__ + ": PASS")
    print("M10B-2H OFFLINE GENERATED SILVER + REVIEW QUEUE: PASS")


if __name__ == "__main__":
    main()
