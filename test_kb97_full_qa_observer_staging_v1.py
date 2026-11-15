#!/usr/bin/env python3
"""Synthetic-only Issue #97 contracts; NEVER calls Staging DB or provider."""
import contextlib
import copy
import io
import json
from unittest.mock import patch

import kb97_full_qa_observer_staging_v1 as obs
from kb03_issue97_app149_ranking_baseline_staging_v1 import BaselineRefused
from test_kb03_issue97_app149_ranking_baseline_staging_v1 import sample_result


def fixture(status="EVIDENCE_ONLY_REVIEW_REQUIRED"):
    result = sample_result()
    result["status"] = status
    for src in result["sources"]:
        src["sha256"] = obs.SOURCE_SHA[src["source_id"]]
        src["revision_date"] = "NOT_VERIFIED"
    return result


def refuse(action, reason=None):
    try:
        action()
    except BaselineRefused as exc:
        if reason:
            assert reason in str(exc), str(exc)
    else:
        raise AssertionError("unsafe candidate QA state accepted")


def test_all_twenty_cases_are_exact_draft_set_not_gold():
    assert tuple(obs.CASES)[:20] == tuple(
        "Q" + str(n).zfill(2) for n in range(1, 21))
    assert tuple(obs.CASES)[20:] == ("Q19b",)
    assert len(obs.SOURCE_SHA) == 2
    assert obs.CASES["Q03"][2] == ((111, 1), (112, 1))
    assert obs.CASES["Q10"][2] == ((121, 2),)
    assert obs.CASES["Q14"][2] == ((124, 4),)
    assert obs.CASES["Q15"][2] == ((125, 5),)


def test_relevance_ranks_are_observations_not_answers():
    response = fixture()
    expected = {"Q01": (4, 115), "Q06": (12, 116),
                "Q09": (5, 121), "Q14": (13, 124),
                "Q15": (1, 125)}
    for case, (rank, chunk) in expected.items():
        row = obs.observe(case, response)
        assert (row["candidate_first_rank"], row["candidate_anchor_chunk"]) == (rank, chunk)
        assert row["candidate_gold_approved"] is False
        assert row["semantic_answer_support_evaluated"] is False
        assert row["candidate_top3"] == (rank <= 3)
        assert row["candidate_top5"] == (rank <= 5)
        assert len(row["top5_source_chunk_page"]) == 5
    q10 = obs.observe("Q10", response)
    assert q10["intent_class"] == "AMBIGUOUS_REVIEW"


def test_currentness_and_ambiguous_scope_never_claim_sufficiency():
    abstain = fixture("CURRENTNESS_UNVERIFIED_ABSTAIN")
    for case in ("Q17", "Q18", "Q19", "Q20"):
        row = obs.observe(case, abstain)
        assert row["currentness_refusal_observed"] is True
        assert row["scope_sufficiency_conclusion"] == "NOT_EVALUATED"
    row = obs.observe("Q19b", fixture())
    assert row["sufficiency_conclusion"] == "NOT_EVALUATED_AMBIGUOUS"
    refuse(lambda: obs.observe("Q19", fixture()),
           "currentness_guard_not_triggered")
    refuse(lambda: obs.observe("Q19b", abstain),
           "unexpected_q19b_status")


def test_safe_metadata_only_capture_and_counts():
    calls = []
    def ask(data):
        assert set(data) == {"question"}
        calls.append(data["question"])
        status = ("CURRENTNESS_UNVERIFIED_ABSTAIN"
                  if any(data["question"] == obs.CASES[c][0]
                         for c in ("Q17", "Q18", "Q19", "Q20"))
                  else "EVIDENCE_ONLY_REVIEW_REQUIRED")
        return fixture(status)
    selection = ["Q01", "Q06", "Q09", "Q14", "Q15", "Q17",
                 "Q18", "Q19", "Q20", "Q19b"]
    report = obs.capture(selection, ask)
    assert len(calls) == len(selection)
    assert report["status"] == "DRAFT_CANDIDATE_BASELINE_NOT_GOLD"
    assert report["professional_gold_approved"] is False
    assert report["ranking_modified"] is False
    assert report["answer_generated"] is False
    assert report["feedback_or_file_written"] is False
    assert report["summary"] == {
        "cases_observed": 10,
        "draft_in_scope_count": 5,
        "draft_anchor_top3_count": 1,
        "draft_anchor_top5_count": 3,
        "currentness_guard_cases": 4,
        "currentness_guard_pass": 4,
        "ambiguous_sufficiency_cases_not_scored": 1,
    }
    public_output = json.dumps(report, ensure_ascii=False)
    for forbidden in ("sensitive", "private answer", "request_id",
                      "question", "content", "X-Jason-OS-Beta-Token"):
        assert forbidden not in public_output


def test_malformed_source_sha_and_ranking_fail_closed():
    invalid = fixture()
    invalid["sources"][0]["sha256"] = "f" * 64
    refuse(lambda: obs.observe("Q01", invalid), "approved_source_sha_changed")
    invalid = fixture()
    invalid["sources"][1]["revision_date"] = "VERIFIED"
    refuse(lambda: obs.observe("Q09", invalid), "unreviewed_currentness_state")
    invalid = fixture()
    invalid["evidence"][0]["source_url"] = "https://evil.example/APP149.pdf#page=5"
    refuse(lambda: obs.observe("Q15", invalid), "official_page_url_invalid")
    invalid = fixture()
    invalid["coverage"]["complete_index_coverage"] = False
    refuse(lambda: obs.observe("Q01", invalid),
           "incomplete_approved_chunk_coverage")
    invalid = fixture()
    invalid["evidence"][0]["chunk_id"] = 121
    invalid["evidence"][0]["page"] = 5
    refuse(lambda: obs.observe("Q15", invalid),
           "duplicate_source_chunk")


def test_no_legal_answer_or_invalid_case_selection():
    wrong = fixture()
    wrong["answer"] = "Unsupported compliance advice"
    refuse(lambda: obs.observe("Q09", wrong), "unexpected_answer_payload")
    refuse(lambda: obs.observe("Q09", fixture("CURRENTNESS_UNVERIFIED_ABSTAIN")),
           "unexpected_positive_case_status")
    for selection in ([], ["Q99"], ["Q01", "Q01"]):
        refuse(lambda cases=selection: obs.capture(cases, lambda _: fixture()),
               "invalid_case_selection")


def test_explicit_live_opt_in_and_no_network_in_test():
    output, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(err):
        try:
            obs.main(["--case-ids", "Q01"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("CLI must require --run-live")
    assert output.getvalue() == ""
    assert "explicit --run-live required" in err.getvalue()
    assert "beta_private_ui_staging_v1" not in obs.__dict__


def main():
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(name + ": PASS")
    print("KB97 20-CASE DRAFT QA OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
