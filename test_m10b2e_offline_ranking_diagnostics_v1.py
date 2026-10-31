#!/usr/bin/env python3
"""M10B-2E synthetic page ranking diagnostics regression; no live models."""
import builtins
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch

from m10b2d_offline_report_v1 import OfflineReportError
from m10b2e_offline_ranking_diagnostics_v1 import (
    analyze_offline_ranking, positive_metrics, negative_metrics,
    render_ranking_markdown,
)
from test_m10b2c_offline_comparison_v1 import compare, materials, one_hot
from test_m10b2d_offline_report_v1 import resign


def baseline():
    with tempfile.TemporaryDirectory() as tmp:
        return compare(materials(Path(tmp)))


def row(report, suffix):
    return next(x for x in report["cases"] if x["case_id"].endswith(suffix))


def reject(callback):
    try:
        callback()
    except (OfflineReportError, ValueError):
        return
    raise AssertionError("unsafe diagnostic input was not rejected")


def test_baseline_correct_rank_precision_and_distractors():
    d = analyze_offline_ranking(baseline())
    assert d["scope"] == "fabricated_synthetic_page_ranking_only"
    assert d["case_count"] == 5
    p1 = row(d, "P1_APPOINTMENT")
    assert p1["lexical_pages"] == [1]
    assert p1["fabricated_vector_pages"] == [1, 2]
    assert p1["lexical"]["first_expected_page_rank"] == 1
    assert p1["lexical"]["precision_over_returned"] == 1.0
    assert p1["lexical"]["off_target_page_count"] == 0
    assert p1["fabricated_vector"]["first_expected_page_rank"] == 1
    assert p1["fabricated_vector"]["precision_over_returned"] == 0.5
    assert p1["fabricated_vector"]["off_target_page_count"] == 1


def test_second_positive_has_non_expected_page():
    d = analyze_offline_ranking(baseline())
    p2 = row(d, "P2_EVACUATION")
    assert p2["fabricated_vector_pages"] == [2, 1]
    assert p2["fabricated_vector"]["returned_page_count"] == 2
    assert p2["fabricated_vector"]["matched_expected_page_count"] == 1
    assert p2["fabricated_vector"]["off_target_page_count"] == 1


def test_paraphrase_missing_lexical_is_scored_as_zero_not_hidden():
    d = analyze_offline_ranking(baseline())
    case = row(d, "P1_PARAPHRASE")
    assert case["lexical_contract_status"] == "FAIL"
    assert case["lexical"]["no_result"] is True
    assert case["lexical"]["first_expected_page_rank"] is None
    assert case["lexical"]["precision_over_returned"] == 0
    assert case["lexical"]["reciprocal_rank"] == 0
    assert case["fabricated_vector"]["first_expected_page_rank"] == 1


def test_aggregate_mrr_precision_and_off_target():
    totals = analyze_offline_ranking(baseline())["summary"]
    lex, vec = totals["lexical"], totals["fabricated_vector"]
    assert lex["positive_hit_at_1_count"] == 2
    assert vec["positive_hit_at_1_count"] == 3
    assert lex["positive_mean_reciprocal_rank"] == 0.666667
    assert vec["positive_mean_reciprocal_rank"] == 1.0
    assert lex["positive_mean_precision_over_returned"] == 0.666667
    assert vec["positive_mean_precision_over_returned"] == 0.5
    assert lex["positive_off_target_page_total"] == 0
    assert vec["positive_off_target_page_total"] == 3
    assert vec["positive_cases_with_off_target"] == 3
    assert lex["negative_cases_with_false_positive"] == 1
    assert lex["negative_false_positive_page_total"] == 1
    assert vec["negative_false_positive_page_total"] == 0


def test_expected_page_in_second_position_mrr_half():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        preds = copy.deepcopy(data[6])
        preds["SYN_GOLD_P1_APPOINTMENT"]["query_vector"] = one_hot(1)
        report = compare(data, predictions=preds, top_k=2)
    d = analyze_offline_ranking(report)
    p1 = row(d, "P1_APPOINTMENT")
    assert p1["fabricated_vector_contract_status"] == "PASS"
    assert p1["fabricated_vector_pages"] == [2, 1]
    assert p1["fabricated_vector"]["first_expected_page_rank"] == 2
    assert p1["fabricated_vector"]["reciprocal_rank"] == 0.5
    assert p1["fabricated_vector"]["hit_at_1"] == 0
    assert p1["fabricated_vector"]["precision_over_returned"] == 0.5


def test_wrong_page_top1_is_not_a_hit():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        preds = copy.deepcopy(data[6])
        preds["SYN_GOLD_P1_APPOINTMENT"]["query_vector"] = one_hot(1)
        d = analyze_offline_ranking(compare(data, predictions=preds, top_k=1))
    p1 = row(d, "P1_APPOINTMENT")
    assert p1["fabricated_vector_contract_status"] == "FAIL"
    assert p1["fabricated_vector_pages"] == [2]
    assert p1["fabricated_vector"]["first_expected_page_rank"] is None
    assert p1["fabricated_vector"]["precision_over_returned"] == 0
    assert p1["fabricated_vector"]["off_target_page_count"] == 1


def test_negative_cases_are_not_given_perfect_positive_precision():
    d = analyze_offline_ranking(baseline())
    n1 = row(d, "NEGATIVE_ABSENT")
    assert n1["lexical"]["abstained"] is True
    assert n1["fabricated_vector"]["abstained"] is True
    assert n1["lexical"]["precision_over_returned"] is None
    assert n1["fabricated_vector"]["reciprocal_rank"] is None
    near = row(d, "NEGATIVE_NEAR_MISS")
    assert near["lexical"]["false_positive_returned_page_count"] == 1
    assert near["fabricated_vector"]["abstained"] is True


def test_forced_negative_vector_response_is_counted():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        preds = copy.deepcopy(data[6])
        preds["SYN_GOLD_NEGATIVE_NEAR_MISS"]["abstain"] = False
        d = analyze_offline_ranking(compare(data, predictions=preds))
    near = row(d, "NEGATIVE_NEAR_MISS")
    assert near["fabricated_vector"]["abstained"] is False
    assert near["fabricated_vector"]["false_positive_returned_page_count"] == 2
    assert d["summary"]["fabricated_vector"]["negative_false_positive_page_total"] == 2


def test_positive_precision_denominator_is_returned_not_topk():
    p = positive_metrics([1, 2], [1])
    assert p["precision_over_returned"] == 0.5
    assert p["returned_page_count"] == 2
    assert positive_metrics([1], [1])["precision_over_returned"] == 1
    assert positive_metrics([], [1])["precision_over_returned"] == 0
    assert negative_metrics([])["precision_over_returned"] is None


def test_readable_markdown_has_all_sections_and_disclaimer():
    txt = render_ranking_markdown(baseline())
    assert txt.startswith("# M10B-2E — Offline Ranking Diagnostics")
    assert "**SYNTHETIC ONLY" in txt
    assert "正向測試排序品質" in txt
    assert "平均倒數排名（MRR）" in txt
    assert "回傳頁碼精確度（平均）" in txt
    assert "非預期頁面總數 | 0 | 3" in txt
    assert "負向案例誤回傳頁數 | 1 | 0" in txt
    assert "不是標準 Precision@K" in txt
    assert txt.count("SYN_GOLD_") == 5


def test_markdown_ranks_and_negative_are_separate():
    txt = render_ranking_markdown(baseline())
    positive_part = txt.split("## 正向案例明細")[1].split(
        "## 負向案例")[0]
    negative_part = txt.split("## 負向案例")[1].split(
        "## 解讀限制")[0]
    assert "SYN_GOLD_P1_APPOINTMENT" in positive_part
    assert "SYN_GOLD_NEGATIVE_ABSENT" not in positive_part
    assert "SYN_GOLD_NEGATIVE_ABSENT" in negative_part
    assert "SYN_GOLD_P1_PARAPHRASE" not in negative_part
    assert "MRR 只依模擬預期頁 ID" in txt


def test_disallows_tampered_comparison_checksum():
    r = baseline()
    r["cases"][0]["lexical_retrieved_pages"] = [2]
    reject(lambda: analyze_offline_ranking(r))
    r = baseline()
    r["report_sha256"] = "f" * 64
    reject(lambda: render_ranking_markdown(r))


def test_disallows_rehashed_false_official_gold_or_model():
    r = baseline()
    r["semantic_verified"] = True
    resign(r)
    reject(lambda: analyze_offline_ranking(r))
    r = baseline()
    r["gold_page_verified"] = True
    resign(r)
    reject(lambda: render_ranking_markdown(r))
    r = baseline()
    r["synthetic_vector_model_contract"]["mode"] = "live-embedding"
    resign(r)
    reject(lambda: analyze_offline_ranking(r))


def test_disallows_extra_data_and_markdown_injection():
    r = baseline()
    r["cases"][0]["query"] = "private text"
    resign(r)
    reject(lambda: render_ranking_markdown(r))
    r = baseline()
    r["cases"][0]["case_id"] = "x|fake table row"
    resign(r)
    reject(lambda: render_ranking_markdown(r))


def test_disallows_cross_candidate_tamper_and_wrong_counts():
    r = baseline()
    r["candidate_id"] = "wrong:" + r["candidate_sha256"]
    resign(r)
    reject(lambda: analyze_offline_ranking(r))
    r = baseline()
    r["counts"]["fixture_vector_positive_pass"] = 0
    resign(r)
    reject(lambda: render_ranking_markdown(r))


def test_input_immutability_and_deterministic_hash():
    r = baseline()
    original = copy.deepcopy(r)
    d1 = analyze_offline_ranking(r)
    d2 = analyze_offline_ranking(r)
    assert d1 == d2
    assert len(d1["diagnostics_sha256"]) == 64
    assert d1["comparison_sha256"] == r["report_sha256"]
    assert r == original
    assert render_ranking_markdown(r) == render_ranking_markdown(r)


def test_no_file_network_or_process_dependencies():
    r = baseline()
    with patch.object(builtins, "open",
                      side_effect=AssertionError("filesystem forbidden")), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("HTTP forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("network forbidden")), \
         patch("subprocess.run",
               side_effect=AssertionError("process forbidden")):
        result = analyze_offline_ranking(r)
        txt = render_ranking_markdown(r)
    assert result["case_count"] == 5
    assert "SYNTHETIC ONLY" in txt


def test_no_raw_query_vectors_or_pdf_text():
    txt = render_ranking_markdown(baseline())
    diag = analyze_offline_ranking(baseline())
    serialized = __import__("json").dumps(diag, ensure_ascii=False)
    for forbidden in (
        "Who supervises small building jobs?",
        "authorized signatory jellyfish",
        "SYNTHETIC DOCUMENT - NOT AN OFFICIAL PUBLICATION",
        "muster point for evacuation", "query_vector", "_full_content",
        '"semantic_verified": true', '"official_gold_page_verified": true',
    ):
        assert forbidden not in txt and forbidden not in serialized, forbidden
    assert diag["official_gold_page_verified"] is None
    assert diag["real_embedding_service_called"] is False


def main():
    tests = [
        test_baseline_correct_rank_precision_and_distractors,
        test_second_positive_has_non_expected_page,
        test_paraphrase_missing_lexical_is_scored_as_zero_not_hidden,
        test_aggregate_mrr_precision_and_off_target,
        test_expected_page_in_second_position_mrr_half,
        test_wrong_page_top1_is_not_a_hit,
        test_negative_cases_are_not_given_perfect_positive_precision,
        test_forced_negative_vector_response_is_counted,
        test_positive_precision_denominator_is_returned_not_topk,
        test_readable_markdown_has_all_sections_and_disclaimer,
        test_markdown_ranks_and_negative_are_separate,
        test_disallows_tampered_comparison_checksum,
        test_disallows_rehashed_false_official_gold_or_model,
        test_disallows_extra_data_and_markdown_injection,
        test_disallows_cross_candidate_tamper_and_wrong_counts,
        test_input_immutability_and_deterministic_hash,
        test_no_file_network_or_process_dependencies,
        test_no_raw_query_vectors_or_pdf_text,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2E OFFLINE SYNTHETIC RANKING DIAGNOSTICS: PASS")


if __name__ == "__main__":
    main()
