#!/usr/bin/env python3
"""M10B-2D: offline-only safe, readable Markdown report regression tests."""
import builtins
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from m10b2d_offline_report_v1 import (
    OfflineReportError, render_offline_markdown, validate_comparison,
)
from test_m10b2c_offline_comparison_v1 import compare, materials, one_hot


def make_report():
    with tempfile.TemporaryDirectory() as tmp:
        return compare(materials(Path(tmp)))


def resign(report):
    payload = {k: v for k, v in report.items() if k != "report_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    report["report_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    return report


def rejects(func):
    try:
        func()
    except OfflineReportError:
        return
    raise AssertionError("expected fail-closed report rejection")


def case(report, id_suffix):
    return next(c for c in report["cases"]
                if c["case_id"].endswith(id_suffix))


def test_human_readable_summary_and_5_case_table():
    report = make_report()
    text = render_offline_markdown(report)
    assert text.startswith("# M10B-2D — Offline Retrieval Comparison")
    assert "**SYNTHETIC ONLY" in text
    assert "非真實 AI 語意能力測試" in text
    assert "正向測試找到預期頁 | 2/3 | 3/3" in text
    assert "負向測試誤命中 | 1/2 | 0/2" in text
    assert text.count("| SYN_GOLD_") == 0
    q = chr(96)
    assert sum(line.startswith("| " + q + "SYN_GOLD_")
               for line in text.splitlines()) == 5
    assert "gold_page_verified=null" in text
    assert "real_embedding_service_called=false" in text
    assert len(text) < 10_000
    validate_comparison(report)


def test_paraphrase_miss_is_labeled_as_mock_not_semantic_win():
    text = render_offline_markdown(make_report())
    assert "SYN_GOLD_P1_PARAPHRASE" in text
    assert "關鍵字漏找；手工向量找到" in text
    assert "並非 Embedding 模型輸出" in text
    assert "不是模型準確率" in text


def test_near_miss_negative_and_unrelated_abstention_visible():
    text = render_offline_markdown(make_report())
    assert "SYN_GOLD_NEGATIVE_NEAR_MISS" in text
    assert "關鍵字誤命中；手工向量拒答" in text
    assert "SYN_GOLD_NEGATIVE_ABSENT" in text
    assert "兩者均拒答" in text


def test_incorrect_fixture_prediction_shown_as_failure():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        preds = copy.deepcopy(data[6])
        preds["SYN_GOLD_NEGATIVE_NEAR_MISS"]["abstain"] = False
        report = compare(data, predictions=preds)
    rendered = render_offline_markdown(report)
    assert "WITH_FIXTURE_FAILURES" in rendered
    assert "有 1 個手工向量 Fixture 失敗案例" in rendered
    assert "兩者均誤命中" in rendered


def test_wrong_page_prediction_visible_as_failure():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        preds = copy.deepcopy(data[6])
        preds["SYN_GOLD_P1_APPOINTMENT"]["query_vector"] = one_hot(1)
        report = compare(data, predictions=preds, top_k=1)
    txt = render_offline_markdown(report)
    assert "關鍵字找到；手工向量漏找" in txt
    assert "有 1 個手工向量 Fixture 失敗案例" in txt


def test_report_checksum_detects_mutation():
    r = make_report()
    r["cases"][0]["lexical_status"] = "FAIL"
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["report_sha256"] = "a" * 64
    rejects(lambda: render_offline_markdown(r))


def test_checksum_is_not_authentication_and_recalculated_forgery_is_rejected():
    r = make_report()
    r["official_document_verified"] = True
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["real_embedding_service_called"] = True
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["semantic_verified"] = True
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_unexpected_keys_or_payload_injection_rejected():
    r = make_report()
    r["internal_notes"] = "confidential content"
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][0]["query"] = "secret"
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["source_id"] = "unsafe|table"
    r["candidate_id"] = r["source_id"] + ":" + r["candidate_sha256"]
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][0]["case_id"] = "row\n|Injected|"
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_tampered_counters_and_status_rejected_even_with_new_hash():
    r = make_report()
    r["counts"]["lexical_positive_pass"] = 3
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["fixture_vector_contract_status"] = "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["status"] = "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_wrong_reason_difference_case_or_duplicate_rejected():
    r = make_report()
    r["cases"][0]["lexical_reason"] = "negative_query_false_positive"
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][0]["difference"] = "lexical_miss_fixture_vector_found"
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][1]["case_id"] = r["cases"][0]["case_id"]
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_unsafe_page_lists_or_false_positive_abstention_rejected():
    r = make_report()
    r["cases"][0]["synthetic_expected_pages"] = [0]
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][0]["lexical_retrieved_pages"] = [True]
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][2]["lexical_retrieved_pages"] = [1]
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["cases"][0]["fixture_vector_retrieved_pages"] = [2]
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_incorrect_model_identity_and_missing_disclaimer_rejected():
    r = make_report()
    r["synthetic_vector_model_contract"]["model_id"] = (
        "intfloat/multilingual-e5-small")
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["notice"] = "real semantic quality confirmed"
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_reference_and_candidate_provenance_must_match():
    r = make_report()
    r["candidate_id"] = "BD_PNAP_APP145:" + r["candidate_sha256"]
    resign(r)
    rejects(lambda: render_offline_markdown(r))
    r = make_report()
    r["fixture_id"] = "other|fixture"
    resign(r)
    rejects(lambda: render_offline_markdown(r))


def test_deterministic_render_without_input_mutation():
    report = make_report()
    before = copy.deepcopy(report)
    a = render_offline_markdown(report)
    b = render_offline_markdown(report)
    assert a == b
    assert report == before


def test_render_does_not_open_files_or_run_subprocesses_or_network():
    report = make_report()
    with patch.object(builtins, "open",
                      side_effect=AssertionError("filesystem forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("HTTP forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("network forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("subprocess forbidden")):
        txt = render_offline_markdown(report)
    assert "SYNTHETIC ONLY" in txt


def test_no_raw_pdf_gold_or_query_text_in_render():
    txt = render_offline_markdown(make_report())
    for forbidden in (
        "Who supervises small building jobs?",
        "authorized signatory jellyfish",
        "SYNTHETIC DOCUMENT - NOT AN OFFICIAL PUBLICATION.",
        "muster point for evacuation",
        "query_vector", "_full_content",
        "gold_page_verified=true", "real_embedding_service_called=true",
        "semantic_verified=true", "real embedding accuracy",
    ):
        assert forbidden not in txt, forbidden


def main():
    tests = [
        test_human_readable_summary_and_5_case_table,
        test_paraphrase_miss_is_labeled_as_mock_not_semantic_win,
        test_near_miss_negative_and_unrelated_abstention_visible,
        test_incorrect_fixture_prediction_shown_as_failure,
        test_wrong_page_prediction_visible_as_failure,
        test_report_checksum_detects_mutation,
        test_checksum_is_not_authentication_and_recalculated_forgery_is_rejected,
        test_unexpected_keys_or_payload_injection_rejected,
        test_tampered_counters_and_status_rejected_even_with_new_hash,
        test_wrong_reason_difference_case_or_duplicate_rejected,
        test_unsafe_page_lists_or_false_positive_abstention_rejected,
        test_incorrect_model_identity_and_missing_disclaimer_rejected,
        test_reference_and_candidate_provenance_must_match,
        test_deterministic_render_without_input_mutation,
        test_render_does_not_open_files_or_run_subprocesses_or_network,
        test_no_raw_pdf_gold_or_query_text_in_render,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2D offline Markdown report regression: PASS")


if __name__ == "__main__":
    main()
