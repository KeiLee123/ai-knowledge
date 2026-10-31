#!/usr/bin/env python3
"""M10B-2I synthetic-only 5-page PDF regressions; no APP149 in GitHub CI."""
import builtins
import copy
import hashlib
import json
from unittest.mock import patch

import pymupdf

from m10b2f_offline_silver_evidence_v1 import EvidenceContractError
from m10b2g_app149_readonly_silver_pilot_v1 import (
    PINNED_DOCUMENT_VERSION, PINNED_PDF_SHA256, PINNED_PHYSICAL_PAGE_COUNT,
    PINNED_SOURCE_ID,
)
from m10b2i_app149_readonly_generated_silver_v1 import (
    MAX_GENERATED_CASES, PER_PAGE_LIMIT, QA_SAMPLE_PERCENT, SAMPLE_SEED,
    SUITE_ID, run_app149_readonly_generated_silver,
    run_pinned_generated_profile,
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
P3 = (
    "SYNTHETIC NONOFFICIAL TRAINING TEXT. The west reading gallery holds "
    "a wooden miniature ship alongside a glass display of colored shells. "
    "Visitors discover beautiful postcards in drawers near the entrance "
    "and enjoy quiet conversations beneath the high skylight. The small "
    "garden has bright flowers and a winding path with several benches "
    "beside a painted stone fountain. These details are imaginary."
)
P4 = (
    "SYNTHETIC NONOFFICIAL TRAINING TEXT. A fictional museum catalog "
    "describes painted musical instruments in a peaceful side room. "
    "A friendly curator carries woven baskets for a creative workshop "
    "where visitors decorate paper lanterns with small colored designs. "
    "The family area contains a table covered with fabric samples "
    "and a shelf displaying sketches of trees and birds."
)
P5 = (
    "SYNTHETIC NONOFFICIAL TRAINING TEXT. In an imaginary research studio "
    "a cheerful volunteer labels glass jars with paper stickers. "
    "The nearby greenhouse contains several climbing vines beside "
    "a broad wooden staircase and quiet round benches. Visitors "
    "can examine handmade drawings at a bright exhibition wall "
    "while the summer sunlight fills this peaceful empty hall."
)
PAGES = (P1, P2, P3, P4, P5)
SOURCE = "SYNTHETIC_APP149_GENERATOR_NOT_OFFICIAL"


def make_pdf(pages=PAGES):
    pdf = pymupdf.open()
    for body in pages:
        page = pdf.new_page()
        if body:
            assert page.insert_textbox(
                pymupdf.Rect(40, 45, 560, 760), body,
                fontsize=10, fontname="helv") >= 0
    data = pdf.tobytes()
    pdf.close()
    return data


def args(pdf, **override):
    options = {
        "source_id": SOURCE, "document_version": "fictional-v1",
        "suite_id": "m10b2i-synthetic-profile-v1",
        "pinned_sha256": hashlib.sha256(pdf).hexdigest(),
        "expected_page_count": 5,
    }
    options.update(override)
    return options


def run(pdf=None, **override):
    pdf = make_pdf() if pdf is None else pdf
    return run_pinned_generated_profile(pdf, **args(pdf, **override))


def rejects(fn):
    try:
        fn()
    except EvidenceContractError:
        return
    raise AssertionError("Unsafe profile unexpectedly accepted")


def test_real_app149_constants_come_from_existing_pinned_adapter():
    assert len(PINNED_PDF_SHA256) == 64
    assert PINNED_SOURCE_ID == "BD_PNAP_APP149"
    assert PINNED_DOCUMENT_VERSION == "2010-12"
    assert PINNED_PHYSICAL_PAGE_COUNT == 5
    assert MAX_GENERATED_CASES == 10
    assert PER_PAGE_LIMIT == 2
    assert QA_SAMPLE_PERCENT == 10


def test_real_adapter_rejects_synthetic_pdf_before_generation():
    binary = make_pdf()
    rejects(lambda: run_app149_readonly_generated_silver(binary))
    assert hashlib.sha256(binary).hexdigest() != PINNED_PDF_SHA256


def test_synthetic_five_page_profile_generates_without_retrieval_model():
    result = run()
    assert result["case_count"] == 10
    assert result["native_page_count"] == 5
    assert result["source_id"] == SOURCE
    assert result["generated_case_type"] == "POSITIVE_CONTEXT_CLOZE_ONLY"
    assert sum(result["verification_counts"].values()) == 10


def test_m10b2f_verification_no_mismatches_for_source_derived_quotes():
    result = run()
    assert result["verification_counts"]["REJECTED_EVIDENCE_MISMATCH"] == 0
    assert result["verification_counts"]["MACHINE_EVIDENCE_CHECKED"] >= 1


def test_legal_wording_routes_to_human_in_synthetic_pdf():
    r = run()
    assert r["verification_counts"]["HUMAN_REVIEW_REQUIRED"] >= 1
    assert r["required_human_review_count"] >= 1
    assert any(x["route"] == "REQUIRED_HUMAN_REVIEW"
               for x in r["review_queue"])


def test_sampling_selects_machine_qa_not_human_gold():
    r = run()
    assert r["sample_percent"] == QA_SAMPLE_PERCENT
    assert r["sample_seed"] == SAMPLE_SEED
    assert r["sampled_human_qa_count"] >= 1
    assert any(x["route"] == "SAMPLED_HUMAN_QA" for x in r["review_queue"])
    assert r["sample_statistics_validated"] is False


def test_zero_percent_still_routes_risky_cases():
    r = run(sample_percent=0)
    assert r["sampled_human_qa_count"] == 0
    assert r["required_human_review_count"] >= 1
    assert r["review_queue_count"] == r["required_human_review_count"]


def test_report_has_only_unreviewed_non_gold_evidence():
    r = run()
    assert r["generated_from_same_pdf_as_evidence"] is True
    assert r["independent_answer_correctness_verified"] is False
    assert r["official_source_verified"] is False
    assert r["gold_page_verified"] is None
    assert r["human_gold_cases_approved"] == 0
    assert r["human_reviewed"] is False
    assert r["semantic_verified"] is False


def test_wrong_sha_rejected_before_pdf_extraction():
    b = make_pdf()
    rejects(lambda: run(b, pinned_sha256="f" * 64))


def test_changed_binary_with_stale_sha_is_rejected():
    a = make_pdf()
    changed = a + b"\n%"
    rejects(lambda: run(changed,
                        pinned_sha256=hashlib.sha256(a).hexdigest()))


def test_page_count_drift_fails_closed():
    rejects(lambda: run(expected_page_count=4))
    rejects(lambda: run(expected_page_count=6))
    rejects(lambda: run(expected_page_count=True))


def test_source_identity_and_scope_reject_invalid_values():
    rejects(lambda: run(source_id="APP|149"))
    rejects(lambda: run(suite_id="not a safe id"))
    rejects(lambda: run(document_version=""))
    rejects(lambda: run(sample_seed="bad|seed"))


def test_generation_budget_and_sampling_bounds():
    rejects(lambda: run(max_cases=51))
    rejects(lambda: run(max_cases=0))
    rejects(lambda: run(max_per_page=4))
    rejects(lambda: run(max_per_page=False))
    rejects(lambda: run(sample_percent=-1))
    rejects(lambda: run(sample_percent=21))
    rejects(lambda: run(sample_percent=True))


def test_one_case_cap_is_respected():
    r = run(max_cases=1, max_per_page=1)
    assert r["case_count"] == 1
    assert sum(r["verification_counts"].values()) == 1


def test_no_native_text_not_promoted_to_silver():
    pdf = make_pdf(("", "", "", "", ""))
    rejects(lambda: run(pdf))


def test_identical_page_duplication_no_unique_candidates():
    pdf = make_pdf((P1, P1, P1, P1, P1))
    rejects(lambda: run(pdf))


def test_deterministic_report_no_mutation():
    b = make_pdf()
    k = args(b)
    before = copy.deepcopy(k)
    a = run_pinned_generated_profile(b, **k)
    z = run_pinned_generated_profile(b, **k)
    assert a == z
    assert k == before
    assert len(a["report_sha256"]) == 64


def test_redacted_report_has_no_source_text_or_candidate_questions():
    raw = json.dumps(run(), ensure_ascii=False)
    for secret in (
        "Inside the quiet archive room",
        "The acting clerk must submit",
        "colorful notebooks and gentle flowers",
        "What wording follows this passage:",
        "evidence_quote", "context_before",
        '"human_gold_cases_approved": 10',
        '"official_source_verified": true',
    ):
        assert secret not in raw, secret


def test_wrapper_results_mark_metrics_as_unvalidated_not_time_saved():
    base = run()
    with patch(
        "m10b2i_app149_readonly_generated_silver_v1.run_pinned_generated_profile",
        return_value=base,
    ):
        result = run_app149_readonly_generated_silver(b"synthetic-for-structure-only")
    assert result["generated_case_count"] == 10
    assert result["source_bytes_match_known_drive_copy"] is True
    assert result["review_queue_count"] == base["review_queue_count"]
    assert result["not_queued_case_count"] == (
        result["generated_case_count"] - result["review_queue_count"])
    assert (result["not_queued_case_fraction"]
            + result["review_queue_fraction"]) == 1.0
    assert result["review_time_saved_measured"] is False
    assert result["question_usefulness_human_reviewed"] is False
    assert result["official_source_verified"] is False
    assert result["official_website_raw_pdf_byte_match_verified"] is False
    assert result["human_gold_cases_approved"] == 0
    assert result["gold_page_verified"] is None
    assert len(result["report_sha256"]) == 64
    assert "Inside the quiet archive room" not in json.dumps(result)
    assert SUITE_ID != base["suite_id"]


def test_wrapper_fail_closed_for_bad_counts_or_forged_gold():
    original = run()
    for bad_key, bad_value in (
        ("case_count", 99),
        ("gold_page_verified", True),
        ("official_source_verified", True),
        ("human_gold_cases_approved", 1),
    ):
        tampered = copy.deepcopy(original)
        tampered[bad_key] = bad_value
        with patch(
            "m10b2i_app149_readonly_generated_silver_v1.run_pinned_generated_profile",
            return_value=tampered,
        ):
            rejects(lambda: run_app149_readonly_generated_silver(b"structure-only"))


def test_no_files_network_processes_or_model_access():
    b = make_pdf()
    with patch.object(builtins, "open",
                      side_effect=AssertionError("disk I/O forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("network forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("socket forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("process forbidden")):
        report = run_pinned_generated_profile(b, **args(b))
        rejects(lambda: run_app149_readonly_generated_silver(b))
    assert report["real_embedding_service_called"] is False
    assert report["production_access"] is False
    assert report["shared_db_access"] is False
    assert report["artifact_written"] is False


def main():
    tests = [
        test_real_app149_constants_come_from_existing_pinned_adapter,
        test_real_adapter_rejects_synthetic_pdf_before_generation,
        test_synthetic_five_page_profile_generates_without_retrieval_model,
        test_m10b2f_verification_no_mismatches_for_source_derived_quotes,
        test_legal_wording_routes_to_human_in_synthetic_pdf,
        test_sampling_selects_machine_qa_not_human_gold,
        test_zero_percent_still_routes_risky_cases,
        test_report_has_only_unreviewed_non_gold_evidence,
        test_wrong_sha_rejected_before_pdf_extraction,
        test_changed_binary_with_stale_sha_is_rejected,
        test_page_count_drift_fails_closed,
        test_source_identity_and_scope_reject_invalid_values,
        test_generation_budget_and_sampling_bounds,
        test_one_case_cap_is_respected,
        test_no_native_text_not_promoted_to_silver,
        test_identical_page_duplication_no_unique_candidates,
        test_deterministic_report_no_mutation,
        test_redacted_report_has_no_source_text_or_candidate_questions,
        test_wrapper_results_mark_metrics_as_unvalidated_not_time_saved,
        test_wrapper_fail_closed_for_bad_counts_or_forged_gold,
        test_no_files_network_processes_or_model_access,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2I APP149 READ-ONLY GENERATED SILVER SYNTHETIC REGRESSION: PASS")


if __name__ == "__main__":
    main()
