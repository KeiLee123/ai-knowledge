#!/usr/bin/env python3
"""Offline Gate C-1b: demonstrate C1 candidate failures cannot pass no-harm."""
from gate_c1b_rank_snapshot_v1 import (
    EXPERIMENT_SHA, STAGING_SHA, LABELS, ROWS, ranks_for,
)
from gate_c1b_no_regression_v1 import (
    NoRegressionRefused, evaluate,
)


def reject_invalid(baseline, candidate):
    try:
        evaluate(baseline, candidate)
    except NoRegressionRefused:
        return
    raise AssertionError("malformed_or_unpinned_ranks_accepted")


def test_operator_snapshot_is_complete_and_pinned():
    assert len(ROWS) == 16
    assert EXPERIMENT_SHA == "2746954dbd43bba5c750e33af7b663eb6d0a126f"
    assert STAGING_SHA == "099094e04bc0ea46fba3eee2cba9050d1a209e7f"
    assert LABELS == "DRAFT_NOT_PROFESSIONALLY_APPROVED_GOLD"
    original = ranks_for("original")
    assert original == tuple(("Q%02d" % i, r[1]) for i, r in enumerate(ROWS, 1))


def test_original_is_no_harm_but_not_a_quality_pass():
    before = ranks_for("original")
    result = evaluate(before, before)
    assert result["top3"] == result["baseline_top3"] == 7
    assert result["top5"] == result["baseline_top5"] == 13
    assert result["no_harm"] is True
    assert result["q09_improved_to_top5"] is False
    assert result["draft_numeric_targets_met"] is False
    assert result["disposition"] == "HOLD_NUMERIC_TARGETS_OR_Q09"
    assert not result["release_authorized"]
    assert before == ranks_for("original")


def test_source_cohesion_rejected_despite_aggregate_gain():
    result = evaluate(ranks_for("original"), ranks_for("source_cohesion"))
    assert result["top3"] == 8 and result["top5"] == 14
    assert result["top5_losses"] == ("Q04",)
    assert result["top1_to_outside_top3"] == ()
    assert result["no_harm"] is False
    assert result["disposition"] == "REJECT_HARD_REGRESSION"


def test_form_aware_rejected_even_though_top3_improved():
    result = evaluate(
        ranks_for("original"), ranks_for("source_cohesion_form_aware"))
    assert result["top3"] == 9 and result["top5"] == 12
    assert result["top5_losses"] == ("Q04", "Q06", "Q07")
    assert result["top1_to_outside_top3"] == ("Q06", "Q07", "Q13")
    assert result["q09_improved_to_top5"] is False
    assert result["disposition"] == "REJECT_HARD_REGRESSION"


def test_purely_numeric_winner_still_requires_expert_gold():
    # A deliberately unrealistic synthetic upper bound, NOT a real reranker.
    original = ranks_for("original")
    synthetic = tuple((case, 1) for case, rank in original)
    result = evaluate(original, synthetic)
    assert result["no_harm"] is True
    assert result["top3"] == 16 and result["top5"] == 16
    assert result["q09_improved_to_top5"] is True
    assert result["draft_numeric_targets_met"] is True
    assert result["disposition"] == "EXPERT_REVIEW_REQUIRED_NO_ACTIVATION"
    assert result["professional_gold_approved"] is False
    assert result["currentness_runtime_tested"] is False
    assert result["source_integrity_runtime_tested"] is False
    assert result["release_authorized"] is False


def test_tampered_incomplete_duplicate_and_bool_ranks_refused():
    original = ranks_for("original")
    candidate = list(original)
    reject_invalid(original[:-1], original)
    reject_invalid(original, candidate[:-1])
    candidate[1] = candidate[0]
    reject_invalid(original, candidate)
    candidate = list(original)
    candidate[1] = ("Q99", 1)
    reject_invalid(original, candidate)
    candidate = list(original)
    candidate[1] = ("Q02", True)
    reject_invalid(original, candidate)
    candidate = list(original)
    candidate[1] = ("Q02", 17)
    reject_invalid(original, candidate)
    tampered = list(original)
    tampered[0] = ("Q01", 1)
    reject_invalid(tampered, original)


def test_read_only_rank_metadata_and_no_runtime_wiring():
    import inspect
    import gate_c1b_no_regression_v1 as scorer
    assert set(scorer.evaluate(ranks_for("original"), ranks_for("original"))) <= {
        "contract_version", "source_baseline_staging_sha", "anchor_labels",
        "case_count", "top3", "top5", "baseline_top3", "baseline_top5",
        "top5_losses", "top1_to_outside_top3", "no_harm",
        "q09_improved_to_top5", "draft_numeric_targets_met",
        "currentness_runtime_tested", "source_integrity_runtime_tested",
        "legal_answer_validated", "professional_gold_approved",
        "release_authorized", "disposition",
    }
    src = inspect.getsource(scorer)
    for prohibited in (
        "import requests", "import subprocess", "import urllib",
        "import psycopg", "import beta_private_ui", "open(",
    ):
        assert prohibited not in src
    assert "AI" not in scorer.VERSION


def main():
    tests = (
        test_operator_snapshot_is_complete_and_pinned,
        test_original_is_no_harm_but_not_a_quality_pass,
        test_source_cohesion_rejected_despite_aggregate_gain,
        test_form_aware_rejected_even_though_top3_improved,
        test_purely_numeric_winner_still_requires_expert_gold,
        test_tampered_incomplete_duplicate_and_bool_ranks_refused,
        test_read_only_rank_metadata_and_no_runtime_wiring,
    )
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("GATE_C1B_NO_REGRESSION_OFFLINE: PASS")
    print("NO_GOLD_NO_RUNTIME_NO_PRODUCTION")


if __name__ == "__main__":
    main()
