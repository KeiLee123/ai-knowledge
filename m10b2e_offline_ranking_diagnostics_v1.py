#!/usr/bin/env python3
"""M10B-2E: synthetic-only, page-level ranking diagnostics in memory.

This is NOT real Embedding evaluation and cannot establish answer correctness.
The single input is a redacted, checksum-verified M10B-2C comparison. No
filesystem, network, DB, model, subprocess or Production access.
"""
import hashlib
import json

from m10b2d_offline_report_v1 import validate_comparison

VERSION = "m10b2e-offline-ranking-diagnostics-v1"
SCOPE = "fabricated_synthetic_page_ranking_only"
WARNING = (
    "SYNTHETIC ONLY: page-ranked fixture outcomes, NOT actual "
    "embedding performance or independently verified official Gold."
)


def positive_metrics(retrieved, expected):
    """Measure page-ID ordering, NOT excerpt match or real relevance."""
    matches = [i for i, page in enumerate(retrieved, start=1)
               if page in expected]
    first_rank = matches[0] if matches else None
    relevant_count = len(matches)
    count = len(retrieved)
    return {
        "returned_page_count": count,
        "matched_expected_page_count": relevant_count,
        "off_target_page_count": count - relevant_count,
        "first_expected_page_rank": first_rank,
        "hit_at_1": int(first_rank == 1),
        "reciprocal_rank": (round(1.0 / first_rank, 6)
                            if first_rank is not None else 0.0),
        "precision_over_returned": (round(relevant_count / count, 6)
                                    if count else 0.0),
        "no_result": count == 0,
    }


def negative_metrics(retrieved):
    """No expected page exists for synthetic negative cases.

    Ranking metrics are not applicable, rather than silently counting
    abstentions as a 100% precision score.
    """
    return {
        "returned_page_count": len(retrieved),
        "false_positive_returned_page_count": len(retrieved),
        "abstained": not retrieved,
        "first_expected_page_rank": None,
        "precision_over_returned": None,
        "reciprocal_rank": None,
    }


def summarize(rows, side, positive_count, negative_count):
    """Macro summaries average over ALL positive cases including misses."""
    positives = [r[side] for r in rows if r["case_type"] == "positive"]
    negatives = [r[side] for r in rows if r["case_type"] == "negative"]
    assert len(positives) == positive_count
    assert len(negatives) == negative_count
    return {
        "positive_case_count": positive_count,
        "negative_case_count": negative_count,
        "positive_hit_at_1_count": sum(x["hit_at_1"] for x in positives),
        "positive_mean_reciprocal_rank": round(
            sum(x["reciprocal_rank"] for x in positives) / positive_count, 6),
        "positive_mean_precision_over_returned": round(
            sum(x["precision_over_returned"] for x in positives)
            / positive_count, 6),
        "positive_off_target_page_total": sum(
            x["off_target_page_count"] for x in positives),
        "positive_cases_with_off_target": sum(
            x["off_target_page_count"] > 0 for x in positives),
        "negative_cases_with_false_positive": sum(
            not x["abstained"] for x in negatives),
        "negative_false_positive_page_total": sum(
            x["false_positive_returned_page_count"] for x in negatives),
    }


def analyze_offline_ranking(comparison):
    """Return a deterministic in-memory object with page-order diagnostics.

    Verifies the existing strict M10B-2C input schema, SHA, synthetic-only
    model identity and flags before extracting any page ranking metrics.
    """
    validate_comparison(comparison)
    rows = []
    for case in comparison["cases"]:
        is_positive = case["case_type"] == "positive"
        pages = case["synthetic_expected_pages"]
        lpages = case["lexical_retrieved_pages"]
        fpages = case["fixture_vector_retrieved_pages"]
        rows.append({
            "case_id": case["case_id"],
            "case_type": case["case_type"],
            "synthetic_expected_pages": list(pages),
            "lexical_pages": list(lpages),
            "fabricated_vector_pages": list(fpages),
            "lexical_contract_status": case["lexical_status"],
            "fabricated_vector_contract_status": case["fixture_vector_status"],
            "lexical": (positive_metrics(lpages, pages) if is_positive
                        else negative_metrics(lpages)),
            "fabricated_vector": (
                positive_metrics(fpages, pages) if is_positive
                else negative_metrics(fpages)),
        })
    counts = comparison["counts"]
    positive_count = counts["positive_cases"]
    negative_count = counts["negative_cases"]
    summary = {
        "lexical": summarize(rows, "lexical", positive_count, negative_count),
        "fabricated_vector": summarize(
            rows, "fabricated_vector", positive_count, negative_count),
    }
    result = {
        "version": VERSION,
        "scope": SCOPE,
        "warning": WARNING,
        "source_id": comparison["source_id"],
        "fixture_id": comparison["fixture_id"],
        "suite_id": comparison["suite_id"],
        "candidate_sha256": comparison["candidate_sha256"],
        "comparison_sha256": comparison["report_sha256"],
        "top_k": comparison["top_k"],
        "case_count": len(rows),
        "summary": summary,
        "cases": rows,
        "metric_definitions": {
            "first_expected_page_rank": "1-based first expected page in returned page IDs",
            "positive_mean_reciprocal_rank": "mean 1/rank across ALL synthetic positive cases, 0 if missing",
            "positive_mean_precision_over_returned": (
                "macro mean of expected page IDs divided by actual returned "
                "page IDs per positive case; empty return scores 0; "
                "NOT standard precision@K"),
            "positive_off_target_page_total": (
                "number of returned pages outside authored synthetic expected-page set; "
                "does NOT establish real-world irrelevance"),
            "negative_false_positive_page_total": (
                "returned page IDs in synthetic negative cases; "
                "abstention is separately reported"),
        },
        "official_gold_page_verified": None,
        "real_embedding_service_called": False,
        "semantic_verified": False,
        "answer_verified": False,
        "retrieval_verified": False,
        "production_access": False,
        "production_write": False,
        "shared_db_access": False,
        "write_authorized": False,
        "artifact_written": False,
        "environment": "staging",
    }
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    result["diagnostics_sha256"] = hashlib.sha256(
        payload.encode("utf-8")).hexdigest()
    return result


def render_ranking_markdown(comparison):
    """Return a concise Traditional Chinese Markdown diagnostic; no writes."""
    result = analyze_offline_ranking(comparison)
    a = result["summary"]["lexical"]
    b = result["summary"]["fabricated_vector"]
    code = chr(96)
    lines = [
        "# M10B-2E — Offline Ranking Diagnostics",
        "",
        "**SYNTHETIC ONLY — 非真實 Embedding 模型評測。**",
        "頁碼及向量都來自模擬測試；沒有 APP145 / APP149 官方 Gold Page 驗證。",
        "",
        "## 測試身份",
        "",
        "- Fixture: " + code + result["fixture_id"] + code,
        "- Comparison SHA256: " + code + result["comparison_sha256"] + code,
        "- Top-K 上限: " + str(result["top_k"]),
        "",
        "## 正向測試排序品質（僅模擬）",
        "",
        "| 指標 | Lexical | 手工向量 |",
        "| --- | ---: | ---: |",
        "| 預期頁排第一（Hit@1） | " +
        str(a["positive_hit_at_1_count"]) + "/" +
        str(a["positive_case_count"]) + " | " +
        str(b["positive_hit_at_1_count"]) + "/" +
        str(b["positive_case_count"]) + " |",
        "| 平均倒數排名（MRR） | " +
        str(a["positive_mean_reciprocal_rank"]) + " | " +
        str(b["positive_mean_reciprocal_rank"]) + " |",
        "| 回傳頁碼精確度（平均） | " +
        str(a["positive_mean_precision_over_returned"]) + " | " +
        str(b["positive_mean_precision_over_returned"]) + " |",
        "| 非預期頁面總數 | " +
        str(a["positive_off_target_page_total"]) + " | " +
        str(b["positive_off_target_page_total"]) + " |",
        "| 負向案例誤回傳頁數 | " +
        str(a["negative_false_positive_page_total"]) + " | " +
        str(b["negative_false_positive_page_total"]) + " |",
        "",
        "## 正向案例明細",
        "",
        "| Case ID | 預期頁 | Lexical 排名 | 手工向量排名 | Lexical 非預期頁 | 向量非預期頁 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in result["cases"]:
        if row["case_type"] != "positive":
            continue
        l = row["lexical"]
        f = row["fabricated_vector"]
        expected = ", ".join(map(str, row["synthetic_expected_pages"]))
        lines.append(
            "| " + code + row["case_id"] + code + " | " + expected +
            " | " + str(l["first_expected_page_rank"] or "—") +
            " | " + str(f["first_expected_page_rank"] or "—") +
            " | " + str(l["off_target_page_count"]) +
            " | " + str(f["off_target_page_count"]) + " |"
        )
    lines.extend([
        "",
        "## 負向案例（沒有預期答案）",
        "",
        "| Case ID | Lexical 回傳頁數 | 手工向量回傳頁數 |",
        "| --- | ---: | ---: |",
    ])
    for row in result["cases"]:
        if row["case_type"] == "negative":
            lines.append(
                "| " + code + row["case_id"] + code + " | " +
                str(row["lexical"]["false_positive_returned_page_count"]) +
                " | " +
                str(row["fabricated_vector"]["false_positive_returned_page_count"]) +
                " |"
            )
    lines.extend([
        "",
        "## 解讀限制",
        "",
        "- 回傳頁碼精確度 = 預期頁命中數 / 實際回傳頁數，空結果計 0；這不是標準 Precision@K。",
        "- 非預期頁是相對於人工編寫的模擬預期頁，並不等於真實世界的無關頁。",
        "- 負向案例不計正向排序排名；直接檢查有沒有錯誤回傳。",
        "- MRR 只依模擬預期頁 ID 計算，不代表內容、引用或答案正確。",
        "- " + code + "real_embedding_service_called=false" + code +
        "；" + code + "semantic_verified=false" + code +
        "；" + code + "official_gold_page_verified=null" + code + "。",
        "- 完全離線、記憶體內產生；沒有寫入 Production、Shared DB 或 Google Drive Current。",
        "",
    ])
    output = "\n".join(lines)
    if len(output) > 30_000:
        raise ValueError("diagnostic_report_too_large")
    return output
