#!/usr/bin/env python3
"""Operator-only read-only STAGING comparison from isolated review checkout.

The CLI can be run BEFORE a staging merge from an exact pinned feature clone,
while checking the untouched /opt/ai-knowledge-staging baseline independently.
No deployment, UI integration, DB/files writes, AI generation or text logs.
Original and candidate presentation ranks use DRAFT (non-Gold) anchors ONLY.
"""
import os

import beta_private_ui_staging_v1 as ui
from gate_c1_rank_experiment_v1 import (
    POLICIES, candidate_anchor_rank, propose_order,
)

A, B = "BD_PNAP_APP145", "BD_PNAP_APP149"
CASES = (
    ("Q01", "舊樓消防改善究竟由屋宇署定消防處負責？", A, (115,)),
    ("Q02", "消防安全工程的建築部分同消防設備，分別邊個執法？", A, (115,)),
    ("Q03", "甚麼類型的舊樓會受消防安全（建築物）規定影響？", A, (111, 112)),
    ("Q04", "商住大廈同純住宅樓，定義上有甚麼分別？", A, (112,)),
    ("Q05", "新界有些按舊條例興建的大廈，適用範圍是否不同？", A, (113,)),
    ("Q06", "如果業主做不到全部消防安全建築改善要求，有甚麼處理途徑？", A, (116,)),
    ("Q07", "做消防安全改善工程，甚麼時候要向屋宇署交建築圖則？", A, (117,)),
    ("Q08", "消防裝置同建築規劃方面，兩個部門權限點分？", A, (115,)),
    ("Q09", "小型工程的 AS 突然病假，承建商可以怎樣處理？", B, (121,)),
    ("Q10", "做緊小型工程時冇 AS 在場，係咪可以繼續做？", B, (121,)),
    ("Q11", "臨時代替的 AS 要符合甚麼資格？", B, (122,)),
    ("Q12", "如果 AS 缺席超過三十日，承建商要怎樣安排？", B, (123,)),
    ("Q13", "同一份小型工程呈交可以同時有兩名 AS 負責嗎？", B, (120,)),
    ("Q14", "更換小型工程的 AS，需要用甚麼通知表格？", B, (124,)),
    ("Q15", "臨時代替 AS 的通知表格在哪裡？", B, (125,)),
    ("Q16", "If an authorized signatory is absent for over 30 days, what should the contractor do?", B, (123,)),
)
SAFETY = (
    ("Q17", "AS 缺席超過30日，現行法例仍然准許照舊做嗎？"),
    ("Q18", "屋宇署同消防處的執法分工目前仍然有效嗎？"),
    ("Q19", "消防處最新的消防設施設計標準是甚麼版本？"),
    ("Q20", "外牆滲水的最新法律責任同申索時限係幾多？"),
)


def checked(question):
    value = ui.ask_evidence({"question": question})
    if (value["environment"] != "staging"
            or value["ai_answer_generated"] is not False
            or value["production_write"] is not False
            or value["coverage"]["indexed_chunks"] != 16
            or value["coverage"]["retrieved_unique_chunks"] != 16
            or {s["source_id"] for s in value["sources"]} != {A, B}
            or any(s["revision_date"] != "NOT_VERIFIED"
                   for s in value["sources"])):
        raise RuntimeError("staging_contract_not_met")
    return value


def main():
    for key in ("JASON_BETA_LLM_API_KEY", "DEEPSEEK_API_KEY",
                "OPENAI_API_KEY"):
        if os.environ.get(key):
            raise RuntimeError("external_api_key_must_be_unset")
    # Existing UI backend independently checks clean 'staging' checkout,
    # source SHA, Staging DB, and localhost embedding guard per question.
    print("GATE C1: EXPERIMENT ONLY; NOT AN ACTIVE RERANKER")
    totals = {p: {"top3": 0, "top5": 0} for p in POLICIES}
    for case_id, question, source, anchors in CASES:
        try:
            result = checked(question)
            if result["status"] != "EVIDENCE_ONLY_REVIEW_REQUIRED":
                raise RuntimeError("unexpected_status")
            ranks = {}
            for policy in POLICIES:
                proposal = propose_order(question, result["evidence"], policy)
                pos = candidate_anchor_rank(proposal, source, anchors)
                ranks[policy] = pos
                totals[policy]["top3"] += int(pos is not None and pos <= 3)
                totals[policy]["top5"] += int(pos is not None and pos <= 5)
            print(case_id + " " + " ".join(
                p + "=" + str(ranks[p]) for p in POLICIES), flush=True)
        except Exception as exc:
            print(case_id + " ERROR=" + type(exc).__name__, flush=True)
            raise SystemExit(1)
    count = 0
    for case_id, question in SAFETY:
        try:
            r = checked(question)
            ok = r["status"] == "CURRENTNESS_UNVERIFIED_ABSTAIN"
            print(case_id + " CURRENTNESS=" + ("PASS" if ok else "FAIL"),
                  flush=True)
            if not ok:
                raise RuntimeError("currentness_refusal_regressed")
            count += 1
        except Exception as exc:
            print(case_id + " ERROR=" + type(exc).__name__, flush=True)
            raise SystemExit(1)
    print("SUMMARY: draft-anchor presentation-order comparisons only")
    for policy, counts in totals.items():
        print(policy + " TOP3=" + str(counts["top3"]) + "/16"
              + " TOP5=" + str(counts["top5"]) + "/16")
    print("CURRENTNESS=" + str(count) + "/4")
    print("NO_GOLD_NO_LEGAL_ANSWER_NO_DEPLOYMENT")
    print("GATE_C1_LIVE_STAGING_EXPERIMENT: PASS")


if __name__ == "__main__":
    main()
