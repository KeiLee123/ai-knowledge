#!/usr/bin/env python3
"""M10B-2C offline-only lexical versus fabricated-vector comparison tests."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from m10b2b0_offline_semantic_v1 import EXPECTED_MODEL_CONTRACT
from m10b2c_offline_comparison_v1 import (
    ComparisonContractError, compare_synthetic_retrieval,
)
from test_m10b2b0_offline_semantic_v1 import (
    FIXTURE, SOURCE, materials, one_hot,
)


def compare(data, *, suite=None, vectors=None, predictions=None,
            model_contract=None, source_id=SOURCE, fixture_id=FIXTURE,
            candidate_sha=None, top_k=3):
    _, manifest, chunks, original_suite, sha, original_vecs, original_pred = data
    return compare_synthetic_retrieval(
        manifest, chunks, original_suite if suite is None else suite,
        source_id=source_id, fixture_id=fixture_id,
        candidate_sha=sha if candidate_sha is None else candidate_sha,
        vectors=original_vecs if vectors is None else vectors,
        predictions=(original_pred if predictions is None else predictions),
        model_contract=(EXPECTED_MODEL_CONTRACT if model_contract is None
                        else model_contract),
        top_k=top_k,
    )


def rejects(callback):
    try:
        callback()
    except (ComparisonContractError, ValueError, KeyError, TypeError):
        return
    raise AssertionError("unsafe comparison was not blocked")


def by_id(report, case_id):
    return next(r for r in report["cases"] if r["case_id"] == case_id)


def test_baseline_comparison_is_properly_scoped():
    with tempfile.TemporaryDirectory() as tmp:
        output = compare(materials(Path(tmp)))
    assert output["status"] == "OFFLINE_SYNTHETIC_COMPARISON_COMPLETE"
    assert output["lexical_contract_status"] == "SYNTHETIC_GOLD_CASES_FAILED"
    assert (output["fixture_vector_contract_status"]
            == "OFFLINE_SYNTHETIC_SEMANTIC_PASSED")
    assert output["counts"] == {
        "synthetic_cases": 5,
        "positive_cases": 3,
        "negative_cases": 2,
        "lexical_positive_pass": 2,
        "fixture_vector_positive_pass": 3,
        "lexical_negative_false_positive": 1,
        "fixture_vector_negative_false_positive": 0,
        "lexical_miss_fixture_vector_found": 1,
        "lexical_false_positive_fixture_abstained": 1,
        "fixture_vector_failure_cases": 0,
    }
    assert output["scope"] == "synthetic_comparison_only"
    assert len(output["report_sha256"]) == 64
    assert output["synthetic_vector_model_contract"] == EXPECTED_MODEL_CONTRACT


def test_paraphrase_case_lexical_miss_is_not_real_semantic_gain():
    with tempfile.TemporaryDirectory() as tmp:
        output = compare(materials(Path(tmp)))
    case = by_id(output, "SYN_GOLD_P1_PARAPHRASE")
    assert case["lexical_retrieved_pages"] == []
    assert case["fixture_vector_retrieved_pages"][0] == 1
    assert case["difference"] == "lexical_miss_fixture_vector_found"
    assert output["semantic_verified"] is False
    assert output["real_embedding_service_called"] is False


def test_near_miss_negative_flags_lexical_false_positive():
    with tempfile.TemporaryDirectory() as tmp:
        output = compare(materials(Path(tmp)))
    case = by_id(output, "SYN_GOLD_NEGATIVE_NEAR_MISS")
    assert case["lexical_status"] == "FAIL"
    assert case["lexical_retrieved_pages"]
    assert case["fixture_vector_status"] == "PASS"
    assert case["fixture_vector_retrieved_pages"] == []
    assert case["difference"] == "lexical_false_positive_fixture_abstained"


def test_unrelated_negative_both_abstain():
    with tempfile.TemporaryDirectory() as tmp:
        output = compare(materials(Path(tmp)))
    case = by_id(output, "SYN_GOLD_NEGATIVE_ABSENT")
    assert case["lexical_status"] == "PASS"
    assert case["fixture_vector_status"] == "PASS"
    assert case["difference"] == "both_synthetic_tests_abstained"


def test_fixture_negative_false_positive_is_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        pred = copy.deepcopy(data[6])
        pred["SYN_GOLD_NEGATIVE_NEAR_MISS"]["abstain"] = False
        output = compare(data, predictions=pred)
    assert output["status"] == "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"
    assert output["counts"]["fixture_vector_failure_cases"] == 1
    assert output["counts"]["fixture_vector_negative_false_positive"] == 1
    assert by_id(output, "SYN_GOLD_NEGATIVE_NEAR_MISS")["fixture_vector_status"] == "FAIL"


def test_wrong_positive_fixture_page_is_not_self_certified():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        pred = copy.deepcopy(data[6])
        pred["SYN_GOLD_P1_APPOINTMENT"]["query_vector"] = one_hot(1)
        output = compare(data, predictions=pred, top_k=1)
    assert output["status"] == "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"
    case = by_id(output, "SYN_GOLD_P1_APPOINTMENT")
    assert case["lexical_status"] == "PASS"
    assert case["fixture_vector_status"] == "FAIL"
    assert case["difference"] == "lexical_found_fixture_vector_miss"


def test_wrong_gold_page_or_excerpt_never_claims_success():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        wrong = copy.deepcopy(data[3])
        wrong["cases"][0]["expected_page_numbers"] = [2]
        result = compare(data, suite=wrong)
        assert result["counts"]["fixture_vector_failure_cases"] >= 1
        assert result["gold_page_verified"] is None
        wrong = copy.deepcopy(data[3])
        wrong["cases"][0]["expected_excerpt"] = "fabricated phrase that is absent"
        result = compare(data, suite=wrong)
        assert result["status"] == "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"


def test_official_gold_or_human_review_forgery_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        for name, value in (("scope", "official"),
                            ("review_status", "human_verified"),
                            ("gold_provenance", "ai_approved")):
            invalid = copy.deepcopy(data[3])
            invalid[name] = value
            rejects(lambda s=invalid: compare(data, suite=s))


def test_source_candidate_and_fixture_crossing_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        rejects(lambda: compare(data, source_id="BD_PNAP_APP145"))
        rejects(lambda: compare(data, fixture_id="unrelated_fixture"))
        rejects(lambda: compare(data, candidate_sha="f" * 64))


def test_vector_missing_extra_and_tamper_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        wrong = copy.deepcopy(data[5])
        wrong.pop(next(iter(wrong)))
        rejects(lambda: compare(data, vectors=wrong))
        wrong = copy.deepcopy(data[5])
        wrong["9999"] = one_hot(0)
        rejects(lambda: compare(data, vectors=wrong))
        altered = list(data)
        altered[2] = copy.deepcopy(data[2])
        altered[2][0]["content"] = "untrusted injected page content"
        rejects(lambda: compare(tuple(altered)))


def test_fake_model_cannot_impersonate_live_service():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        for field, value in (("mode", "real-embedding"),
                             ("model_id", "intfloat/multilingual-e5-small"),
                             ("model_revision", "614241f622f53c4eeff9890bdc4f31cfecc418b3"),
                             ("dimension", 768)):
            contract = dict(EXPECTED_MODEL_CONTRACT, **{field: value})
            rejects(lambda c=contract: compare(data, model_contract=c))


def test_invalid_top_k_and_missing_negative_cases_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        rejects(lambda: compare(data, top_k=0))
        rejects(lambda: compare(data, top_k=11))
        positives_only = copy.deepcopy(data[3])
        positives_only["cases"] = [c for c in positives_only["cases"]
                                   if c["should_find"]]
        preds = {k: v for k, v in data[6].items()
                 if k in {c["case_id"] for c in positives_only["cases"]}}
        rejects(lambda: compare(data, suite=positives_only, predictions=preds))


def test_report_contains_no_raw_document_queries_or_vectors():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        result = compare(data)
        packed = json.dumps(result, ensure_ascii=False, sort_keys=True)
        for secret_or_claim in (
            "Who supervises small building jobs?",
            "authorized signatory jellyfish",
            "SYNTHETIC DOCUMENT - NOT AN OFFICIAL PUBLICATION",
            '"query_vector"', '"vector":', '"_full_content":',
            '"semantic_verified": true', '"gold_page_verified": true',
            '"real_embedding_service_called": true',
        ):
            assert secret_or_claim not in packed, secret_or_claim
        assert result["official_document_verified"] is False
        assert result["gold_page_verified"] is None
        assert result["answer_verified"] is False
        assert result["production_access"] is False
        assert result["production_write"] is False
        assert result["write_authorized"] is False
        assert result["shared_db_access"] is False
        assert result["artifact_written"] is False


def test_deterministic_report_no_file_mutation():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        pdf = data[0]
        before = (hashlib.sha256(pdf.read_bytes()).hexdigest(),
                  pdf.stat().st_mtime_ns)
        suite, vectors, preds = (
            copy.deepcopy(data[3]), copy.deepcopy(data[5]),
            copy.deepcopy(data[6]),
        )
        first = compare(data)
        second = compare(data)
        assert first == second
        assert data[3] == suite and data[5] == vectors and data[6] == preds
        assert before == (hashlib.sha256(pdf.read_bytes()).hexdigest(),
                          pdf.stat().st_mtime_ns)


def test_comparison_has_no_network_db_or_subprocess_dependency():
    with tempfile.TemporaryDirectory() as tmp:
        data = materials(Path(tmp))
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("HTTP blocked")), \
             patch("socket.create_connection",
                   side_effect=AssertionError("network blocked")), \
             patch("subprocess.run",
                   side_effect=AssertionError("subprocess blocked")):
            report = compare(data)
        assert report["status"] == "OFFLINE_SYNTHETIC_COMPARISON_COMPLETE"


def main():
    tests = [
        test_baseline_comparison_is_properly_scoped,
        test_paraphrase_case_lexical_miss_is_not_real_semantic_gain,
        test_near_miss_negative_flags_lexical_false_positive,
        test_unrelated_negative_both_abstain,
        test_fixture_negative_false_positive_is_not_a_pass,
        test_wrong_positive_fixture_page_is_not_self_certified,
        test_wrong_gold_page_or_excerpt_never_claims_success,
        test_official_gold_or_human_review_forgery_blocked,
        test_source_candidate_and_fixture_crossing_blocked,
        test_vector_missing_extra_and_tamper_blocked,
        test_fake_model_cannot_impersonate_live_service,
        test_invalid_top_k_and_missing_negative_cases_fail_closed,
        test_report_contains_no_raw_document_queries_or_vectors,
        test_deterministic_report_no_file_mutation,
        test_comparison_has_no_network_db_or_subprocess_dependency,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2C offline synthetic retrieval comparison regression: PASS")


if __name__ == "__main__":
    main()
