#!/usr/bin/env python3
"""Gate C-1b rank-only NO-REGRESSION evaluator; intentionally non-operational.

This is an OFFLINE reviewer aid for DRAFT source anchors, not a production
reranker, a Gold benchmark, or source/answer/currentness verification.
"""
from gate_c1b_rank_snapshot_v1 import ranks_for, STAGING_SHA, LABELS

VERSION = "gate-c1b-no-regression-v1"
CASE_IDS = tuple("Q%02d" % i for i in range(1, 17))
TARGET_TOP3 = 13
TARGET_TOP5 = 15


class NoRegressionRefused(ValueError):
    pass


def _require(ok, why):
    if not ok:
        raise NoRegressionRefused(why)


def _parse_rank_rows(rows, label):
    """Validate one rank-only table, including duplicates and forged booleans."""
    _require(type(rows) in (tuple, list) and len(rows) == len(CASE_IDS),
             label + "_bad_case_count")
    ordered = {}
    for row in rows:
        _require(type(row) in (tuple, list) and len(row) == 2,
                 label + "_bad_row")
        case_id, rank = row
        _require(type(case_id) is str and case_id in CASE_IDS,
                 label + "_invalid_case_id")
        _require(case_id not in ordered, label + "_duplicate_case_id")
        _require(type(rank) is int and 1 <= rank <= 16,
                 label + "_invalid_rank")
        ordered[case_id] = rank
    _require(set(ordered) == set(CASE_IDS), label + "_case_mismatch")
    return ordered


def evaluate(baseline_rows, candidate_rows):
    """Compare DRAFT first-core-anchor ranks without modifying either input.

    Hard gate H1: baseline Top5 anchors must remain Top5.
    Hard gate H2: baseline rank #1 anchors must remain Top3.
    Separate product goals are NOT a release authorization.
    """
    baseline = _parse_rank_rows(baseline_rows, "baseline")
    candidate = _parse_rank_rows(candidate_rows, "candidate")
    _require(baseline == _parse_rank_rows(ranks_for("original"), "pin"),
             "unpinned_baseline_refused")

    top5_losses = tuple(k for k in CASE_IDS
                        if baseline[k] <= 5 and candidate[k] > 5)
    top1_losses = tuple(k for k in CASE_IDS
                        if baseline[k] == 1 and candidate[k] > 3)
    top3 = sum(candidate[k] <= 3 for k in CASE_IDS)
    top5 = sum(candidate[k] <= 5 for k in CASE_IDS)
    no_harm = not top5_losses and not top1_losses
    q09_fixed = candidate["Q09"] <= 5
    draft_targets_met = top3 >= TARGET_TOP3 and top5 >= TARGET_TOP5

    if not no_harm:
        disposition = "REJECT_HARD_REGRESSION"
    elif not (draft_targets_met and q09_fixed):
        disposition = "HOLD_NUMERIC_TARGETS_OR_Q09"
    else:
        disposition = "EXPERT_REVIEW_REQUIRED_NO_ACTIVATION"

    return {
        "contract_version": VERSION,
        "source_baseline_staging_sha": STAGING_SHA,
        "anchor_labels": LABELS,
        "case_count": len(CASE_IDS),
        "top3": top3,
        "top5": top5,
        "baseline_top3": sum(r <= 3 for r in baseline.values()),
        "baseline_top5": sum(r <= 5 for r in baseline.values()),
        "top5_losses": top5_losses,
        "top1_to_outside_top3": top1_losses,
        "no_harm": no_harm,
        "q09_improved_to_top5": q09_fixed,
        "draft_numeric_targets_met": draft_targets_met,
        "currentness_runtime_tested": False,
        "source_integrity_runtime_tested": False,
        "legal_answer_validated": False,
        "professional_gold_approved": False,
        "release_authorized": False,
        "disposition": disposition,
    }
