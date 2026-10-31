#!/usr/bin/env python3
"""M10B-2D: pure, bounded Markdown view of a synthetic comparison report.

Never accesses files, endpoints, models, databases, subprocesses or network.
Renders already validated M10B-2C in-memory comparison, never real Gold.
The report SHA is a reproducibility checksum, NOT an authenticity signature.
"""
import hashlib
import json
import re

from m10b2c_offline_comparison_v1 import LABELS, SCOPE, VERSION

VIEW_VERSION = "m10b2d-offline-retrieval-markdown-v1"
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
SAFE_SHA = re.compile(r"[a-f0-9]{64}\Z")
COUNTERS = frozenset({
    "synthetic_cases", "positive_cases", "negative_cases",
    "lexical_positive_pass", "fixture_vector_positive_pass",
    "lexical_negative_false_positive",
    "fixture_vector_negative_false_positive",
    "lexical_miss_fixture_vector_found",
    "lexical_false_positive_fixture_abstained",
    "fixture_vector_failure_cases",
})
FIELDS = frozenset({
    "version", "scope", "status", "source_id", "candidate_id",
    "candidate_sha256", "fixture_id", "suite_id", "top_k",
    "lexical_contract_status", "fixture_vector_contract_status",
    "synthetic_vector_model_contract", "counts", "cases", "notice",
    "gold_page_verified", "official_document_verified",
    "real_embedding_service_called", "semantic_verified", "answer_verified",
    "retrieval_verified", "production_access", "production_write",
    "write_authorized", "canonical_promoted", "accepted_reference_advanced",
    "shared_db_access", "external_vision_api_used", "artifact_written",
    "environment", "report_sha256",
})
CASE_FIELDS = frozenset({
    "case_id", "case_type", "lexical_status", "fixture_vector_status",
    "difference", "lexical_reason", "fixture_vector_reason",
    "lexical_retrieved_pages", "fixture_vector_retrieved_pages",
    "synthetic_expected_pages", "official_gold_page_verified",
})
MODEL_CONTRACT = {
    "mode": "offline-synthetic",
    "model_id": "synthetic-orthogonal-vectors-v1",
    "model_revision": "fixed-test-fixture-v1",
    "dimension": 384,
    "adapter_version": "offline-fixture-only-v1",
}
NOTICE = (
    "Comparison of lexical evidence and manually fabricated synthetic "
    "vectors/abstention only; not measured real embedding performance."
)
REASONS = {
    "positive": {
        "lexical": {
            "PASS": "expected_page_and_excerpt_found",
            "FAIL": "expected_page_excerpt_or_terms_missing",
        },
        "fixture": {
            "PASS": "synthetic_expected_page_retrieved",
            "FAIL": "synthetic_gold_page_not_retrieved_or_abstained",
        },
    },
    "negative": {
        "lexical": {
            "PASS": "negative_query_abstained",
            "FAIL": "negative_query_false_positive",
        },
        "fixture": {
            "PASS": "synthetic_explicit_abstention",
            "FAIL": "negative_answerability_failure",
        },
    },
}
FINDINGS = {
    "both_synthetic_tests_found": "兩種合成檢索均找到預期頁",
    "lexical_miss_fixture_vector_found": "關鍵字漏找；手工向量找到",
    "lexical_found_fixture_vector_miss": "關鍵字找到；手工向量漏找",
    "both_synthetic_tests_missed": "兩種合成檢索均漏找",
    "both_synthetic_tests_abstained": "兩者均拒答",
    "lexical_false_positive_fixture_abstained": "關鍵字誤命中；手工向量拒答",
    "lexical_abstained_fixture_false_positive": "關鍵字拒答；手工向量誤命中",
    "both_synthetic_tests_false_positive": "兩者均誤命中",
}


class OfflineReportError(ValueError):
    """Malformed, tampered or untrusted synthetic comparison input."""


def need(ok, reason):
    if not ok:
        raise OfflineReportError(reason)


def safe_id(value):
    return type(value) is str and SAFE_ID.fullmatch(value) is not None


def page_list(value):
    return (type(value) is list and len(value) <= 50 and
            all(type(v) is int and 1 <= v <= 500 for v in value)
            and len(set(value)) == len(value))


def display_pages(value):
    return ", ".join(str(p) for p in value) if value else "—"


def validate_comparison(report):
    """Validate exact M10B-2C schema, checksum, labels, flags and counts."""
    need(type(report) is dict and set(report) == FIELDS,
         "unexpected_comparison_schema")
    need(report["version"] == VERSION and report["scope"] == SCOPE,
         "wrong_comparison_contract")
    need(report["synthetic_vector_model_contract"] == MODEL_CONTRACT
         and type(report["synthetic_vector_model_contract"]) is dict,
         "real_or_unknown_model_contract")
    need(report["notice"] == NOTICE, "missing_synthetic_disclaimer")
    need(report["environment"] == "staging", "not_staging")
    need(report["gold_page_verified"] is None, "fake_gold_claim")
    for key in (
        "official_document_verified", "real_embedding_service_called",
        "semantic_verified", "answer_verified", "retrieval_verified",
        "production_access", "production_write", "write_authorized",
        "canonical_promoted", "accepted_reference_advanced",
        "shared_db_access", "external_vision_api_used", "artifact_written",
    ):
        need(report[key] is False, "unsafe_status_" + key)
    for key in ("source_id", "fixture_id", "suite_id"):
        need(safe_id(report[key]), "unsafe_identifier_" + key)
    sha = report["candidate_sha256"]
    need(type(sha) is str and SAFE_SHA.fullmatch(sha) is not None,
         "invalid_candidate_sha")
    need(report["candidate_id"] == report["source_id"] + ":" + sha,
         "candidate_identity_mismatch")
    need(type(report["top_k"]) is int and 1 <= report["top_k"] <= 10,
         "invalid_top_k")
    report_sha = report["report_sha256"]
    need(type(report_sha) is str
         and SAFE_SHA.fullmatch(report_sha) is not None,
         "invalid_report_sha")
    payload = {k: v for k, v in report.items() if k != "report_sha256"}
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OfflineReportError("invalid_report_payload") from exc
    need(hashlib.sha256(canonical.encode("utf-8")).hexdigest() == report_sha,
         "report_checksum_mismatch")
    need(type(report["counts"]) is dict
         and set(report["counts"]) == COUNTERS
         and all(type(n) is int and 0 <= n <= 50
                 for n in report["counts"].values()),
         "invalid_comparison_counts")
    rows = report["cases"]
    need(type(rows) is list and 2 <= len(rows) <= 50,
         "invalid_case_list")
    seen = set()
    calculated = {name: 0 for name in COUNTERS}
    for row in rows:
        need(type(row) is dict and set(row) == CASE_FIELDS,
             "unexpected_case_fields")
        case_id = row["case_id"]
        need(safe_id(case_id) and case_id not in seen,
             "unsafe_or_duplicate_case_id")
        seen.add(case_id)
        need(row["official_gold_page_verified"] is None, "fake_case_gold")
        kind = row["case_type"]
        ls, fs = row["lexical_status"], row["fixture_vector_status"]
        need(kind in ("positive", "negative")
             and ls in ("PASS", "FAIL") and fs in ("PASS", "FAIL"),
             "invalid_case_status")
        need(row["lexical_reason"] == REASONS[kind]["lexical"][ls]
             and row["fixture_vector_reason"] == REASONS[kind]["fixture"][fs],
             "inconsistent_result_reason")
        diff = LABELS[(kind == "positive", ls == "PASS", fs == "PASS")]
        need(row["difference"] == diff, "inconsistent_difference")
        for field in ("synthetic_expected_pages",
                      "lexical_retrieved_pages",
                      "fixture_vector_retrieved_pages"):
            need(page_list(row[field]), "invalid_case_page_list")
        expected = row["synthetic_expected_pages"]
        lpages = row["lexical_retrieved_pages"]
        fpages = row["fixture_vector_retrieved_pages"]
        need(len(lpages) <= report["top_k"] and
             len(fpages) <= report["top_k"], "top_k_page_overflow")
        need((kind == "positive" and bool(expected))
             or (kind == "negative" and not expected),
             "invalid_expected_pages")
        if kind == "positive":
            if ls == "PASS":
                need(bool(set(expected) & set(lpages)),
                     "lexical_page_without_expected")
            if fs == "PASS":
                need(bool(set(expected) & set(fpages)),
                     "fixture_page_without_expected")
        else:
            if ls == "PASS":
                need(not lpages, "negative_lexical_nonabstention")
            if fs == "PASS":
                need(not fpages, "negative_fixture_nonabstention")
        calculated["synthetic_cases"] += 1
        calculated[kind + "_cases"] += 1
        if kind == "positive":
            calculated["lexical_positive_pass"] += (ls == "PASS")
            calculated["fixture_vector_positive_pass"] += (fs == "PASS")
        else:
            calculated["lexical_negative_false_positive"] += (ls == "FAIL")
            calculated["fixture_vector_negative_false_positive"] += (
                fs == "FAIL")
        calculated["lexical_miss_fixture_vector_found"] += (
            diff == "lexical_miss_fixture_vector_found")
        calculated["lexical_false_positive_fixture_abstained"] += (
            diff == "lexical_false_positive_fixture_abstained")
        calculated["fixture_vector_failure_cases"] += (fs == "FAIL")
    need(calculated == report["counts"], "tampered_summary_counters")
    need(calculated["positive_cases"] > 0 and
         calculated["negative_cases"] > 0, "missing_case_type")
    expected_lex = ("SYNTHETIC_GOLD_CASES_PASSED"
                    if all(x["lexical_status"] == "PASS" for x in rows)
                    else "SYNTHETIC_GOLD_CASES_FAILED")
    expected_fixture = (
        "OFFLINE_SYNTHETIC_SEMANTIC_PASSED"
        if calculated["fixture_vector_failure_cases"] == 0
        else "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
    )
    expected_status = (
        "OFFLINE_SYNTHETIC_COMPARISON_COMPLETE"
        if calculated["fixture_vector_failure_cases"] == 0
        else "OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES"
    )
    need(report["lexical_contract_status"] == expected_lex
         and report["fixture_vector_contract_status"] == expected_fixture
         and report["status"] == expected_status,
         "wrong_comparison_status")


def render_offline_markdown(report):
    """Return a human-readable Markdown string. No write or export side effect."""
    validate_comparison(report)
    q = chr(96)  # Markdown inline code marker.
    n = report["counts"]
    lines = [
        "# M10B-2D — Offline Retrieval Comparison",
        "",
        "**SYNTHETIC ONLY — 非真實 AI 語意能力測試。**",
        "手工產生的 384D 向量及拒答旗標，並非 Embedding 模型輸出。",
        "沒有官方 APP145 / APP149 人工 Gold Page 驗證。",
        "",
        "## 測試身份",
        "",
        "- Environment: " + q + "staging" + q + "（純離線測試）",
        "- Source ID: " + q + report["source_id"] + q + "（模擬測試）",
        "- Fixture: " + q + report["fixture_id"] + q,
        "- Suite: " + q + report["suite_id"] + q,
        "- Candidate SHA256: " + q + report["candidate_sha256"] + q,
        "- Comparison SHA256: " + q + report["report_sha256"] + q,
        "- Top-K: " + str(report["top_k"]),
        "",
        "## 模擬案例摘要",
        "",
        "| 項目 | Lexical Search | 手工向量 Fixture |",
        "| --- | ---: | ---: |",
        "| 正向測試找到預期頁 | " +
        str(n["lexical_positive_pass"]) + "/" + str(n["positive_cases"]) +
        " | " + str(n["fixture_vector_positive_pass"]) + "/" +
        str(n["positive_cases"]) + " |",
        "| 負向測試誤命中 | " +
        str(n["lexical_negative_false_positive"]) + "/" +
        str(n["negative_cases"]) + " | " +
        str(n["fixture_vector_negative_false_positive"]) + "/" +
        str(n["negative_cases"]) + " |",
        "",
        "## 逐案例結果（均為模擬）",
        "",
        "| Case ID | 類型 | Lexical | 手工向量 | 預期頁 | Lexical 頁 | 向量頁 | 差異與原因 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["cases"]:
        lines.append(
            "| " + q + row["case_id"] + q + " | " + row["case_type"] +
            " | " + row["lexical_status"] + " | " +
            row["fixture_vector_status"] + " | " +
            display_pages(row["synthetic_expected_pages"]) + " | " +
            display_pages(row["lexical_retrieved_pages"]) + " | " +
            display_pages(row["fixture_vector_retrieved_pages"]) + " | " +
            FINDINGS[row["difference"]] + " |"
        )
    lines.extend([
        "",
        "## 驗收邊界",
        "",
        "- 測試狀態：" + q + report["status"] + q + "（僅合約測試）",
        "- 有 " + str(n["fixture_vector_failure_cases"]) +
        " 個手工向量 Fixture 失敗案例；不會被隱藏。",
        "- 以上 PASS / FAIL 不是模型準確率，也不是法律文件內容正確性。",
        "- " + q + "real_embedding_service_called=false" + q + "；" +
        q + "semantic_verified=false" + q + "；" +
        q + "gold_page_verified=null" + q + "。",
        "- 不讀寫 Production / Shared DB / Google Drive Current，不觸發 Live Embedding。",
        "- SHA256 只供同一報告內容比對，不是可信簽章或官方來源認證。",
        "",
    ])
    result = "\n".join(lines)
    need(len(result) <= 30_000, "rendered_markdown_too_large")
    return result
