#!/usr/bin/env python3
"""KB-03 / Issue #97: read-only, candidate-anchor APP149 ranking baseline.

Run explicitly on a clean Staging checkout. Calls the *existing* guarded
question-first Beta search; never changes ranking, answers, files or feedback.
Only source/chunk/page/rank metadata goes to stdout. Draft QA anchors != Gold.
"""

import argparse
import json

VERSION = "kb03-issue97-app149-ranking-baseline-v0.1"
SOURCE = "BD_PNAP_APP149"
BOTH = frozenset(("BD_PNAP_APP145", SOURCE))
FORM_CHUNKS = (124, 125)
# Candidate anchors taken from the existing Drive Natural-Language QA Baseline;
# they are NOT independently approved legal/professional Gold labels.
# id, ordinary user question, intent, primary chunk, physical PDF page, caveat
CASES = (
    ("Q09", "小型工程的 AS 突然病假，承建商可以怎樣處理？",
     "body", 121, 2, "candidate; supporting chunk122 may matter"),
    ("Q10", "做緊小型工程時冇 AS 在場，係咪可以繼續做？",
     "body", 121, 2, "ambiguous physical absence vs unable to act"),
    ("Q11", "臨時代替的 AS 要符合甚麼資格？",
     "body", 122, 2, "candidate"),
    ("Q12", "如果 AS 缺席超過三十日，承建商要怎樣安排？",
     "body", 123, 3, "candidate"),
    ("Q13", "同一份小型工程呈交可以同時有兩名 AS 負責嗎？",
     "body", 120, 1, "candidate"),
    ("Q14", "更換小型工程的 AS，需要用甚麼通知表格？",
     "form", 124, 4, "form query; body chunk120 also relevant"),
    ("Q15", "臨時代替 AS 的通知表格在哪裡？",
     "form", 125, 5, "form query; body chunk121 also relevant"),
    ("Q16", "If an authorized signatory is absent for over 30 days, what should the contractor do?",
     "body", 123, 3, "candidate"),
)
INDEX = {row[0]: row for row in CASES}
DEFAULT_CASES = ("Q09", "Q11", "Q14", "Q15")


class BaselineRefused(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise BaselineRefused(reason)


def validate_result(result):
    """Verify actual two-source, all-16 response before interpreting ranks."""
    require(isinstance(result, dict), "result_not_object")
    require(result.get("environment") == "staging", "not_staging")
    require(result.get("source", {}).get("source_id") == "AUTO_APPROVED",
            "not_question_first_both_sources")
    require(result.get("ai_answer_generated") is False
            and result.get("production_write") is False,
            "unexpected_model_or_production_write")
    require(result.get("status") in ("EVIDENCE_ONLY_REVIEW_REQUIRED",
                                    "CURRENTNESS_UNVERIFIED_ABSTAIN"),
            "unexpected_query_status")
    coverage = result.get("coverage")
    require(isinstance(coverage, dict)
            and coverage.get("indexed_chunks") == 16
            and coverage.get("retrieved_unique_chunks") == 16
            and coverage.get("complete_index_coverage") is True,
            "incomplete_approved_chunk_coverage")
    sources = result.get("sources")
    require(isinstance(sources, list) and len(sources) == 2
            and {s.get("source_id") for s in sources if isinstance(s, dict)} == BOTH,
            "source_set_invalid")
    for source in sources:
        cov = source.get("coverage", {})
        require(cov.get("indexed_chunks") == 8
                and cov.get("retrieved_unique_chunks") == 8
                and cov.get("complete_index_coverage") is True,
                "source_coverage_changed")
    evidence = result.get("evidence")
    require(isinstance(evidence, list) and len(evidence) == 16,
            "ranked_evidence_count_invalid")
    seen = set()
    for i, item in enumerate(evidence, 1):
        require(isinstance(item, dict)
                and item.get("id") == "S" + str(i),
                "display_ranking_invalid")
        sid, chunk, page = item.get("source_id"), item.get("chunk_id"), item.get("page")
        require(sid in BOTH and type(chunk) is int and chunk > 0
                and type(page) is int and page > 0,
                "evidence_identity_invalid")
        pair = (sid, chunk)
        require(pair not in seen, "duplicate_source_chunk")
        seen.add(pair)
        url = item.get("source_url")
        require(isinstance(url, str) and url.startswith("https://www.bd.gov.hk/")
                and url.endswith("/APP/" + sid.split("APP")[-1].join(("APP", ".pdf#page=")) + str(page)),
                "official_page_url_invalid")
    require(sum(sid == SOURCE for sid, _ in seen) == 8,
            "app149_chunk_count_invalid")
    return evidence


def observe(case_id, response):
    require(case_id in INDEX, "unknown_case_id")
    evidence = validate_result(response)
    _, _, intent, anchor, page, caveat = INDEX[case_id]
    matches = [(idx, item) for idx, item in enumerate(evidence, 1)
               if item["source_id"] == SOURCE and item["chunk_id"] == anchor]
    require(len(matches) == 1 and matches[0][1]["page"] == page,
            "candidate_anchor_missing_or_page_changed")
    rank = matches[0][0]
    form_ranks = [idx for idx, item in enumerate(evidence, 1)
                  if item["source_id"] == SOURCE
                  and item["chunk_id"] in FORM_CHUNKS]
    require(len(form_ranks) == 2, "app149_form_chunks_missing")
    first_form = min(form_ranks)
    return {
        "case_id": case_id,
        "anchor_intent": intent,
        "candidate_anchor_source": SOURCE,
        "candidate_anchor_chunk": anchor,
        "candidate_anchor_page": page,
        "first_anchor_rank": rank,
        "candidate_hit_top3": rank <= 3,
        "candidate_hit_top5": rank <= 5,
        "first_app149_form_rank": first_form,
        "form_before_body_anchor": (first_form < rank if intent == "body" else None),
        "review_note": caveat,
        "top5_source_chunk_page": [
            {"source_id": row["source_id"], "chunk_id": row["chunk_id"],
             "page": row["page"]}
            for row in evidence[:5]
        ],
        "observed_status": response["status"],
    }


def summarize(rows):
    body = [row for row in rows if row["anchor_intent"] == "body"]
    forms = [row for row in rows if row["anchor_intent"] == "form"]
    return {
        "cases": len(rows),
        "body_cases": len(body),
        "form_cases": len(forms),
        "body_candidate_top3_count": sum(row["candidate_hit_top3"] for row in body),
        "form_candidate_top3_count": sum(row["candidate_hit_top3"] for row in forms),
        "body_cases_with_form_above_anchor": sum(
            row["form_before_body_anchor"] for row in body),
        "candidate_misses_top5": sum(not row["candidate_hit_top5"] for row in rows),
    }


def capture(case_ids, ask):
    """Ask function injectable only for offline tests; live CLI uses actual UI."""
    require(isinstance(case_ids, (list, tuple)) and bool(case_ids)
            and all(isinstance(x, str) and x in INDEX for x in case_ids)
            and len(set(case_ids)) == len(case_ids),
            "invalid_case_selection")
    rows = []
    for case_id in case_ids:
        # Exact fixed questions; no operator-private feedback, token or question logs.
        response = ask({"question": INDEX[case_id][1]})
        rows.append(observe(case_id, response))
    return {
        "version": VERSION,
        "environment": "staging",
        "capture": "existing_question_first_private_beta_search",
        "candidate_anchors_not_professional_gold": True,
        "source_currentness_not_verified": True,
        "automated_reranking_performed": False,
        "answer_correctness_not_evaluated": True,
        "feedback_queue_accessed": False,
        "report_written_to_disk": False,
        "summary": summarize(rows),
        "cases": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Explicit, read-only APP149 ranking baseline; prints metadata only")
    parser.add_argument("--run-live", action="store_true",
                        help="actually query existing Staging DB and local embedding")
    parser.add_argument("--case-ids", default=",".join(DEFAULT_CASES),
                        help="comma-separated Q09..Q16 (default Q09,Q11,Q14,Q15)")
    args = parser.parse_args(argv)
    if not args.run_live:
        parser.error("explicit --run-live required; no implicit external calls")
    case_ids = args.case_ids.split(",")
    require(all(case_ids), "empty_case_id")
    # Import only for authorized live runs; existing QA integrity guard enforces
    # clean 'staging' checkout, source SHA and read-only Staging DB operations.
    import beta_private_ui_staging_v1 as ui
    output = capture(case_ids, ui.ask_evidence)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaselineRefused as exc:
        raise SystemExit("RANKING_BASELINE_REFUSED: " + str(exc)) from None
