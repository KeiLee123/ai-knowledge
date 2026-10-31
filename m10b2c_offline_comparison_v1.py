#!/usr/bin/env python3
"""M10B-2C: in-memory synthetic lexical vs synthetic-vector comparison.

Pure report composer for candidate-only test fixtures. Uses existing provenance
and synthetic Gold validators, never a model endpoint, DB, network, filesystem
or Production. A fabricated vector fixture is NOT evidence of real semantics.
"""
import hashlib
import json

from m10b2a_gold_cases_v1 import evaluate_synthetic_suite
from m10b2b0_offline_semantic_v1 import evaluate_offline_synthetic

VERSION = "m10b2c-offline-comparison-v1"
SCOPE = "synthetic_comparison_only"
LABELS = {
    (True, True, True): "both_synthetic_tests_found",
    (True, False, True): "lexical_miss_fixture_vector_found",
    (True, True, False): "lexical_found_fixture_vector_miss",
    (True, False, False): "both_synthetic_tests_missed",
    (False, True, True): "both_synthetic_tests_abstained",
    (False, False, True): "lexical_false_positive_fixture_abstained",
    (False, True, False): "lexical_abstained_fixture_false_positive",
    (False, False, False): "both_synthetic_tests_false_positive",
}


class ComparisonContractError(ValueError):
    """Unsafe, mismatched, or inconsistent synthetic evaluation data."""


def require(test, reason):
    if not test:
        raise ComparisonContractError(reason)


def compare_synthetic_retrieval(
        manifest, chunks, suite, *, source_id, candidate_sha, fixture_id,
        vectors, predictions, model_contract, top_k=3):
    """Recompute both evaluators against the SAME source, suite and candidate.

    Semantic-side inputs are authored synthetic vectors and abstention flags;
    they must never be described as actual multilingual-e5-small outputs.
    Output contains only case IDs, pages, counts and reasons, never PDF text,
    Gold excerpts, raw queries or vectors. No external reads/writes.
    """
    lexical = evaluate_synthetic_suite(
        manifest, chunks, suite,
        source_id=source_id, candidate_sha=candidate_sha,
        fixture_id=fixture_id, top_k=top_k,
    )
    fixture = evaluate_offline_synthetic(
        manifest, chunks, suite,
        source_id=source_id, candidate_sha=candidate_sha,
        fixture_id=fixture_id, vectors=vectors, predictions=predictions,
        model_contract=model_contract, top_k=top_k,
    )
    expected_id = source_id + ":" + candidate_sha
    for report in (lexical, fixture):
        require(report["candidate_id"] == expected_id, "candidate_identity_drift")
        require(report["source_id"] == source_id, "source_identity_drift")
        require(report["fixture_id"] == fixture_id, "fixture_identity_drift")
        require(report["suite_id"] == suite["suite_id"], "suite_identity_drift")
        require(report["gold_page_verified"] is None, "official_gold_claim")
        require(report["official_document_verified"] is False,
                "official_document_claim")
        require(report["semantic_verified"] is False, "semantic_quality_claim")
        require(report["answer_verified"] is False, "answer_quality_claim")
        require(report["retrieval_verified"] is False, "retrieval_quality_claim")
        require(report["production_access"] is False, "production_access_claim")
        require(report["production_write"] is False, "production_write_claim")
        require(report["shared_db_access"] is False, "shared_db_claim")
        require(report["write_authorized"] is False, "write_permission_claim")
    require(fixture["real_embedding_service_called"] is False,
            "live_model_claim")
    require(lexical["status"] in (
        "SYNTHETIC_GOLD_CASES_PASSED", "SYNTHETIC_GOLD_CASES_FAILED"
    ), "unexpected_lexical_status")
    require(fixture["status"] in (
        "OFFLINE_SYNTHETIC_SEMANTIC_PASSED",
        "OFFLINE_SYNTHETIC_SEMANTIC_FAILED",
    ), "unexpected_fixture_status")

    lex_rows = lexical["cases"]
    fixture_rows = fixture["cases"]
    expected_cases = suite["cases"]
    require(len(lex_rows) == len(fixture_rows) == len(expected_cases),
            "case_count_mismatch")

    comparisons = []
    counters = {
        "synthetic_cases": 0,
        "positive_cases": 0,
        "negative_cases": 0,
        "lexical_positive_pass": 0,
        "fixture_vector_positive_pass": 0,
        "lexical_negative_false_positive": 0,
        "fixture_vector_negative_false_positive": 0,
        "lexical_miss_fixture_vector_found": 0,
        "lexical_false_positive_fixture_abstained": 0,
        "fixture_vector_failure_cases": 0,
    }
    for gold_case, lrow, frow in zip(expected_cases, lex_rows, fixture_rows):
        case_id = gold_case["case_id"]
        expected_kind = "positive" if gold_case["should_find"] else "negative"
        require(lrow["case_id"] == frow["case_id"] == case_id,
                "case_order_or_identity_drift")
        require(lrow["case_type"] == frow["case_type"] == expected_kind,
                "case_kind_drift")
        require(lrow["status"] in ("PASS", "FAIL") and
                frow["status"] in ("PASS", "FAIL"),
                "invalid_case_result")
        lp = lrow["status"] == "PASS"
        fp = frow["status"] == "PASS"
        expected_positive = gold_case["should_find"]
        label = LABELS[(expected_positive, lp, fp)]

        counters["synthetic_cases"] += 1
        if expected_positive:
            counters["positive_cases"] += 1
            counters["lexical_positive_pass"] += int(lp)
            counters["fixture_vector_positive_pass"] += int(fp)
        else:
            counters["negative_cases"] += 1
            counters["lexical_negative_false_positive"] += int(not lp)
            counters["fixture_vector_negative_false_positive"] += int(not fp)
        counters["lexical_miss_fixture_vector_found"] += int(
            label == "lexical_miss_fixture_vector_found")
        counters["lexical_false_positive_fixture_abstained"] += int(
            label == "lexical_false_positive_fixture_abstained")
        counters["fixture_vector_failure_cases"] += int(not fp)

        comparisons.append({
            "case_id": case_id,
            "case_type": expected_kind,
            "lexical_status": lrow["status"],
            "fixture_vector_status": frow["status"],
            "difference": label,
            "lexical_reason": lrow["reason"],
            "fixture_vector_reason": frow["reason"],
            "lexical_retrieved_pages": list(lrow["retrieved_page_numbers"]),
            "fixture_vector_retrieved_pages": list(frow["retrieved_pages"]),
            "synthetic_expected_pages": list(
                gold_case["expected_page_numbers"]),
            "official_gold_page_verified": None,
        })

    require(counters["synthetic_cases"] == (
        counters["positive_cases"] + counters["negative_cases"]),
        "broken_comparison_counts")
    require(counters["positive_cases"] > 0 and counters["negative_cases"] > 0,
            "must_include_positive_and_negative_cases")

    result = {
        "version": VERSION,
        "scope": SCOPE,
        "status": (
            "OFFLINE_SYNTHETIC_COMPARISON_COMPLETE"
            if counters["fixture_vector_failure_cases"] == 0
            else "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"
        ),
        "source_id": source_id,
        "candidate_id": expected_id,
        "candidate_sha256": candidate_sha,
        "fixture_id": fixture_id,
        "suite_id": suite["suite_id"],
        "top_k": top_k,
        "lexical_contract_status": lexical["status"],
        "fixture_vector_contract_status": fixture["status"],
        "synthetic_vector_model_contract": dict(model_contract),
        "counts": counters,
        "cases": comparisons,
        "notice": (
            "Comparison of lexical evidence and manually fabricated synthetic "
            "vectors/abstention only; not measured real embedding performance."
        ),
        "gold_page_verified": None,
        "official_document_verified": False,
        "real_embedding_service_called": False,
        "semantic_verified": False,
        "answer_verified": False,
        "retrieval_verified": False,
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
        "canonical_promoted": False,
        "accepted_reference_advanced": False,
        "shared_db_access": False,
        "external_vision_api_used": False,
        "artifact_written": False,
        "environment": "staging",
    }
    digestible = json.dumps(
        result, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    result["report_sha256"] = hashlib.sha256(
        digestible.encode("utf-8")).hexdigest()
    return result
