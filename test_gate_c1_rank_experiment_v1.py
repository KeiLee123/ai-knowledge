#!/usr/bin/env python3
"""Offline, synthetic-only tests: NO Staging/Production DB or real embeddings."""
import copy

import gate_c1_rank_experiment_v1 as experiment

APP149 = "BD_PNAP_APP149"
APP145 = "BD_PNAP_APP145"
BASE = "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnap/APP/"


def row(rank, source, chunk, page, text):
    return {
        "id": "S" + str(rank), "source_id": source,
        "chunk_id": chunk, "page": page, "content": text,
        "source_url": BASE + source[-6:] + ".pdf#page=" + str(page),
    }


def as_fixture():
    # Synthetic fragments mirror IDs/order ONLY from a user-observed case.
    # No professional source-content or semantic accuracy is asserted.
    return [
        row(1, APP149, 123, 3, "Absence over 30 days procedure"),
        row(2, APP149, 119, 1, "Prescribed contractor introduction"),
        row(3, APP149, 125, 5, "Appendix B nomination form"),
        row(4, APP149, 126, 5, "Name ______ Signature ______"),
        row(5, APP149, 120, 1, "Appointment of original signatory"),
        row(6, APP149, 121, 2, "Nomination for temporary absence"),
        row(7, APP149, 124, 4, "Appendix A change form"),
        row(8, APP145, 116, 3, "Difficulties complying with fire safety"),
    ]


def nz_fixture():
    return [
        row(1, APP145, 111, 1, "Introduction"),
        row(2, APP149, 124, 4, "Appendix A"),
        row(3, APP145, 117, 4, "Building plans"),
        row(4, APP149, 120, 1, "Authorized signatory"),
        row(5, APP149, 125, 5, "Appendix B"),
        row(6, APP145, 113, 2, "New Territories exception"),
        row(7, APP149, 123, 3, "Absence over 30 days"),
        row(8, APP149, 126, 5, "_______ _______"),
    ]


def test_original_is_unchanged_and_no_text_emitted():
    before = as_fixture()
    evidence = copy.deepcopy(before)
    result = experiment.propose_order("小型工程的 AS 突然病假怎樣處理？", evidence)
    assert evidence == before
    assert [x["evidence_id"] for x in result["candidates"]] == [
        "S" + str(i) for i in range(1, 9)]
    assert experiment.candidate_anchor_rank(result, APP149, (121,)) == 6
    assert "content" not in repr(result)
    assert "Signature ______" not in repr(result)
    assert result["scope"] == "OFFLINE_STAGING_EXPERIMENT_ONLY"


def test_source_cohesion_is_stable_and_not_a_solution_to_q09():
    result = experiment.propose_order(
        "小型工程的 AS 突然病假怎樣處理？", as_fixture(), "source_cohesion")
    assert experiment.candidate_anchor_rank(result, APP149, (121,)) == 6
    assert result["candidates"][-1]["source_id"] == APP145
    result = experiment.propose_order(
        "新界舊樓適用範圍是否不同？", nz_fixture(), "source_cohesion")
    assert experiment.candidate_anchor_rank(result, APP145, (113,)) == 3


def test_structural_probe_is_context_dependent_not_appendix_ban():
    question = "小型工程的 AS 突然病假怎樣處理？"
    p = experiment.propose_order(
        question, as_fixture(), "source_cohesion_form_aware")
    assert experiment.candidate_anchor_rank(p, APP149, (121,)) < 6
    assert [x["evidence_id"] for x in p["candidates"] if
            x["source_id"] == APP149] != ["S" + str(i) for i in range(1, 8)]
    form = experiment.propose_order(
        "臨時代替 AS 的通知表格在哪裡？",
        as_fixture(), "source_cohesion_form_aware")
    assert form["form_request_detected"]
    assert experiment.candidate_anchor_rank(form, APP149, (125,)) <= 3
    assert {x["evidence_id"] for x in form["candidates"]} == {
        x["id"] for x in as_fixture()}


def test_bad_inputs_fail_closed():
    def refused(question, evidence, policy="original"):
        try:
            experiment.propose_order(question, evidence, policy)
        except experiment.ExperimentRefused:
            return
        raise AssertionError("invalid experiment was accepted")

    refused("abc", as_fixture())
    refused("valid question", as_fixture(), "enable_runtime")
    d = as_fixture()
    d[1]["id"] = "S1"
    refused("valid question", d)
    d = as_fixture()
    d[1]["chunk_id"] = 123
    refused("valid question", d)
    d = as_fixture()
    d[2]["page"] = True
    refused("valid question", d)
    d = as_fixture()
    d[2]["source_url"] = "https://untrusted.invalid/doc#page=5"
    refused("valid question", d)


def test_no_nonlocal_side_effects_or_quality_claims():
    import inspect
    src = inspect.getsource(experiment)
    assert "import requests" not in src
    assert "import subprocess" not in src
    assert "import urllib" not in src
    assert "open(" not in src
    assert "SUFFICIENT" not in src
    assert "production_write" not in src
    result = experiment.propose_order(
        "更換 AS 的通知表格在哪裡？", as_fixture(),
        "source_cohesion_form_aware")
    assert "answer" not in result
    assert "gold" not in result
    assert "ai_answer_generated" not in result


def main():
    tests = (
        test_original_is_unchanged_and_no_text_emitted,
        test_source_cohesion_is_stable_and_not_a_solution_to_q09,
        test_structural_probe_is_context_dependent_not_appendix_ban,
        test_bad_inputs_fail_closed,
        test_no_nonlocal_side_effects_or_quality_claims,
    )
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("GATE_C1_PURE_EXPERIMENT_OFFLINE: PASS")


if __name__ == "__main__":
    main()
