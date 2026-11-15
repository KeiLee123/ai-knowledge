#!/usr/bin/env python3
"""Issue #97: explicit, read-only 20-question Candidate QA baseline.

Reuse the guarded Private Beta question-first search and its existing complete
APP145/APP149 integrity checks. This is an OBSERVATION tool, not an answer
engine, automatic reranker, professional Gold set or deployed HTTP endpoint.
Never emit questions, source text, request IDs, feedback or Session Tokens.
"""
import argparse
import json

from kb03_issue97_app149_ranking_baseline_staging_v1 import (
    BaselineRefused, require, validate_result,
)

VERSION = "kb97-20case-observer-v0.1"
APP145 = "BD_PNAP_APP145"
APP149 = "BD_PNAP_APP149"
# Pinned historic approved PDFs, per 2026-11-08 Drive reviewer packet;
# this check is identity only, NOT a statement of present legal validity.
SOURCE_SHA = {
    APP145: "dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c",
    APP149: "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8",
}

# Exact DRAFT case wording from the Google Drive 20-question QA document.
# Candidate anchor IDs/pages are NOT independently signed-off legal Gold.
# For Q03, either of the draft building-scope paragraphs may be first.
CASES = {
    "Q01": ("舊樓消防改善究竟由屋宇署定消防處負責？", APP145, ((115, 3),)),
    "Q02": ("消防安全工程的建築部分同消防設備，分別邊個執法？", APP145, ((115, 3),)),
    "Q03": ("甚麼類型的舊樓會受消防安全（建築物）規定影響？", APP145, ((111, 1), (112, 1))),
    "Q04": ("商住大廈同純住宅樓，定義上有甚麼分別？", APP145, ((112, 1),)),
    "Q05": ("新界有些按舊條例興建的大廈，適用範圍是否不同？", APP145, ((113, 2),)),
    "Q06": ("如果業主做不到全部消防安全建築改善要求，有甚麼處理途徑？", APP145, ((116, 3),)),
    "Q07": ("做消防安全改善工程，甚麼時候要向屋宇署交建築圖則？", APP145, ((117, 4),)),
    "Q08": ("消防裝置同建築規劃方面，兩個部門權限點分？", APP145, ((115, 3),)),
    "Q09": ("小型工程的 AS 突然病假，承建商可以怎樣處理？", APP149, ((121, 2),)),
    "Q10": ("做緊小型工程時冇 AS 在場，係咪可以繼續做？", APP149, ((121, 2),)),
    "Q11": ("臨時代替的 AS 要符合甚麼資格？", APP149, ((122, 2),)),
    "Q12": ("如果 AS 缺席超過三十日，承建商要怎樣安排？", APP149, ((123, 3),)),
    "Q13": ("同一份小型工程呈交可以同時有兩名 AS 負責嗎？", APP149, ((120, 1),)),
    "Q14": ("更換小型工程的 AS，需要用甚麼通知表格？", APP149, ((124, 4),)),
    "Q15": ("臨時代替 AS 的通知表格在哪裡？", APP149, ((125, 5),)),
    "Q16": ("If an authorized signatory is absent for over 30 days, what should the contractor do?", APP149, ((123, 3),)),
    "Q17": ("AS 缺席超過30日，現行法例仍然准許照舊做嗎？", None, ()),
    "Q18": ("屋宇署同消防處的執法分工目前仍然有效嗎？", None, ()),
    "Q19": ("消防處最新的消防設施設計標準是甚麼版本？", None, ()),
    "Q20": ("外牆滲水的最新法律責任同申索時限係幾多？", None, ()),
    # Additional ambiguous negative candidate. NOT counted in Q01–Q20.
    "Q19b": ("消防處消防設施的設計規範包括哪些具體技術要求？", None, ()),
}
DEFAULT_IDS = ("Q01", "Q06", "Q09", "Q14", "Q15", "Q19", "Q19b")


def check_source_pins(result):
    sources = result["sources"]
    require({s.get("source_id") for s in sources} == set(SOURCE_SHA),
            "source_identity_changed")
    for source in sources:
        require(source.get("sha256") == SOURCE_SHA[source["source_id"]],
                "approved_source_sha_changed")
        require(source.get("revision_date") == "NOT_VERIFIED",
                "unreviewed_currentness_state")


def observe(case_id, result):
    require(case_id in CASES, "unknown_case_id")
    evidence = validate_result(result)
    check_source_pins(result)
    require("answer" not in result and "generated_answer" not in result,
            "unexpected_answer_payload")
    _question, source_id, anchors = CASES[case_id]
    row = {
        "case_id": case_id,
        "observed_status": result["status"],
        "candidate_gold_approved": False,
        "source_currentness_verified": False,
        "semantic_answer_support_evaluated": False,
        "top5_source_chunk_page": [
            {"source_id": e["source_id"], "chunk_id": e["chunk_id"],
             "page": e["page"]} for e in evidence[:5]
        ],
    }
    if source_id is not None:
        require(result["status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED",
                "unexpected_positive_case_status")
        matches = [
            (rank, e) for rank, e in enumerate(evidence, 1)
            if e["source_id"] == source_id
            and (e["chunk_id"], e["page"]) in anchors
        ]
        require(bool(matches), "draft_candidate_anchor_missing")
        rank, item = min(matches, key=lambda pair: pair[0])
        row.update({
            "intent_class": "AMBIGUOUS_REVIEW" if case_id == "Q10" else
                            "APPENDIX_FORM" if case_id in ("Q14", "Q15") else
                            "DRAFT_SOURCE_ANCHOR",
            "candidate_source_id": source_id,
            "candidate_anchor_chunk": item["chunk_id"],
            "candidate_anchor_page": item["page"],
            "candidate_first_rank": rank,
            "candidate_top3": rank <= 3,
            "candidate_top5": rank <= 5,
        })
    elif case_id == "Q19b":
        # Q19b is partially covered, not a reviewed negative Gold case.
        require(result["status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED",
                "unexpected_q19b_status")
        row["sufficiency_conclusion"] = "NOT_EVALUATED_AMBIGUOUS"
    else:
        require(result["status"] == "CURRENTNESS_UNVERIFIED_ABSTAIN",
                "currentness_guard_not_triggered")
        row["currentness_refusal_observed"] = True
        # Q19 / Q20 still do NOT prove a separate scope-sufficiency gate.
        row["scope_sufficiency_conclusion"] = "NOT_EVALUATED"
    return row


def capture(ids, ask):
    require(isinstance(ids, (list, tuple)) and bool(ids)
            and len(set(ids)) == len(ids)
            and all(isinstance(case_id, str) and case_id in CASES for case_id in ids),
            "invalid_case_selection")
    rows = []
    for case_id in ids:
        # Existing UI invokes Staging-only QA with source/DB checksum guards.
        # No raw question, excerpt or token is printed or written by this tool.
        rows.append(observe(case_id, ask({"question": CASES[case_id][0]})))
    in_scope = [r for r in rows if "candidate_first_rank" in r]
    currentness = [r for r in rows if "currentness_refusal_observed" in r]
    return {
        "version": VERSION,
        "environment": "staging",
        "status": "DRAFT_CANDIDATE_BASELINE_NOT_GOLD",
        "source_scope": list(SOURCE_SHA),
        "approved_source_sha256": dict(SOURCE_SHA),
        "all_evidence_preserved": True,
        "ranking_modified": False,
        "answer_generated": False,
        "professional_gold_approved": False,
        "feedback_or_file_written": False,
        "current_legal_applicability": "NOT_VERIFIED",
        "summary": {
            "cases_observed": len(rows),
            "draft_in_scope_count": len(in_scope),
            "draft_anchor_top3_count": sum(r["candidate_top3"] for r in in_scope),
            "draft_anchor_top5_count": sum(r["candidate_top5"] for r in in_scope),
            "currentness_guard_cases": len(currentness),
            "currentness_guard_pass": sum(r["currentness_refusal_observed"] for r in currentness),
            "ambiguous_sufficiency_cases_not_scored": sum(r["case_id"] == "Q19b" for r in rows),
        },
        "cases": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Explicit Staging-only 20-case candidate ranking and refusal observation")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--case-ids", default=",".join(DEFAULT_IDS),
                        help="comma-separated Q01..Q20,Q19b or 'all'")
    args = parser.parse_args(argv)
    if not args.run_live:
        parser.error("explicit --run-live required; offline tests never access VPS")
    ids = list(CASES)[:20] if args.case_ids == "all" else args.case_ids.split(",")
    require(all(ids), "empty_case_id")
    # Import only after explicit opt-in; UI reuses strict Staging QA guards.
    import beta_private_ui_staging_v1 as ui
    result = capture(ids, ui.ask_evidence)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaselineRefused as exc:
        raise SystemExit("KB97_QA_REFUSED: " + str(exc)) from None
