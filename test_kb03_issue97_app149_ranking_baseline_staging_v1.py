#!/usr/bin/env python3
"""Issue #97 synthetic-only contracts, not measured real ranking/Gold labels."""

import copy
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import kb03_issue97_app149_ranking_baseline_staging_v1 as b


PAGES = {
    111: 1, 112: 1, 113: 2, 114: 2, 115: 3, 116: 3, 117: 4, 118: 5,
    119: 1, 120: 1, 121: 2, 122: 2, 123: 3, 124: 4, 125: 5, 126: 5,
}


def sample_result(chunks=None):
    # Synthetic failed Q09: form 125 ranks S1, relevant body 121 ranks S5.
    if chunks is None:
        chunks = [125, 113, 119, 115, 121, 111, 120, 112,
                  122, 114, 123, 116, 124, 117, 126, 118]
    evidence = []
    for i, chunk in enumerate(chunks, 1):
        source = "BD_PNAP_APP149" if chunk >= 119 else "BD_PNAP_APP145"
        code = "APP149" if chunk >= 119 else "APP145"
        page = PAGES[chunk]
        evidence.append({
            "id": "S" + str(i), "source_id": source, "chunk_id": chunk,
            "page": page,
            "source_url": (
                "https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
                "practice-notes-and-circular-letters/pnap/APP/"
                + code + ".pdf#page=" + str(page)),
            "content": "sensitive raw evidence must not be emitted",
        })
    return {
        "request_id": "sensitive-request-id-not-to-echo",
        "environment": "staging",
        "source": {"source_id": "AUTO_APPROVED"},
        "sources": [
            {"source_id": source, "coverage": {
                "indexed_chunks": 8, "retrieved_unique_chunks": 8,
                "complete_index_coverage": True}}
            for source in ("BD_PNAP_APP145", "BD_PNAP_APP149")
        ],
        "coverage": {"indexed_chunks": 16, "retrieved_unique_chunks": 16,
                     "complete_index_coverage": True},
        "status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "ai_answer_generated": False, "production_write": False,
        "message": "private answer content not to echo",
        "evidence": evidence,
    }


def reject(action, why=None):
    try:
        action()
    except b.BaselineRefused as exc:
        if why:
            assert why in str(exc), str(exc)
        return
    raise AssertionError("unsafe ranking result was accepted")


def test_q09_body_behind_form_measured_not_patched():
    result = sample_result()
    row = b.observe("Q09", result)
    assert row["first_anchor_rank"] == 5
    assert row["first_app149_form_rank"] == 1
    assert row["form_before_body_anchor"] is True
    assert row["candidate_hit_top3"] is False
    assert row["candidate_hit_top5"] is True
    assert row["candidate_anchor_chunk"] == 121
    assert len(row["top5_source_chunk_page"]) == 5


def test_q15_form_ranks_first_is_good_and_not_penalized():
    row = b.observe("Q15", sample_result())
    assert row["anchor_intent"] == "form"
    assert row["first_anchor_rank"] == 1
    assert row["candidate_hit_top3"] is True
    assert row["form_before_body_anchor"] is None
    assert row["candidate_anchor_page"] == 5


def test_q14_different_appendix_not_mistaken_for_q15():
    row = b.observe("Q14", sample_result())
    assert row["candidate_anchor_chunk"] == 124
    assert row["candidate_anchor_page"] == 4
    assert row["first_anchor_rank"] == 13
    assert row["candidate_hit_top5"] is False


def test_full_capture_metrics_are_observed_not_gold():
    call = []
    def fake_ask(params):
        assert list(params) == ["question"]
        call.append(params["question"])
        return sample_result()
    output = b.capture(["Q09", "Q11", "Q14", "Q15"], fake_ask)
    assert len(call) == 4
    assert output["summary"] == {
        "cases": 4, "body_cases": 2, "form_cases": 2,
        "body_candidate_top3_count": 0, "form_candidate_top3_count": 1,
        "body_cases_with_form_above_anchor": 2,
        "candidate_misses_top5": 2,
    }
    assert output["candidate_anchors_not_professional_gold"] is True
    assert output["automated_reranking_performed"] is False
    assert output["answer_correctness_not_evaluated"] is True
    assert output["feedback_queue_accessed"] is False
    assert output["report_written_to_disk"] is False
    txt = json.dumps(output, ensure_ascii=False)
    for forbidden in ("sensitive", "request_id", "content", "private answer"):
        assert forbidden not in txt


def test_missing_anchor_or_page_refused_not_silently_passed():
    result = sample_result()
    for item in result["evidence"]:
        if item["chunk_id"] == 121:
            item["page"] = 3
            item["source_url"] = item["source_url"].replace("#page=2", "#page=3")
    reject(lambda: b.observe("Q09", result), "candidate_anchor_missing_or_page_changed")


def test_incomplete_or_misleading_auto_scope_refused():
    template = sample_result()
    variants = []
    wrong_scope = copy.deepcopy(template)
    wrong_scope["source"]["source_id"] = "BD_PNAP_APP149"
    variants.append(wrong_scope)
    incomplete = copy.deepcopy(template)
    incomplete["coverage"]["complete_index_coverage"] = False
    variants.append(incomplete)
    bogus = copy.deepcopy(template)
    bogus["ai_answer_generated"] = True
    variants.append(bogus)
    wrong_source = copy.deepcopy(template)
    wrong_source["sources"][0]["source_id"] = "BD_PNAP_APP149"
    variants.append(wrong_source)
    for variant in variants:
        reject(lambda x=variant: b.observe("Q09", x))


def test_invalid_id_duplicate_chunk_or_url_refused():
    source = sample_result()
    bad_id = copy.deepcopy(source)
    bad_id["evidence"][0]["id"] = "S42"
    reject(lambda: b.observe("Q09", bad_id), "display_ranking_invalid")
    dup = copy.deepcopy(source)
    dup["evidence"][1]["chunk_id"] = 125
    dup["evidence"][1]["source_id"] = "BD_PNAP_APP149"
    reject(lambda: b.observe("Q09", dup), "duplicate_source_chunk")
    wrong_url = copy.deepcopy(source)
    wrong_url["evidence"][0]["source_url"] = "https://untrusted.test/APP149.pdf#page=5"
    reject(lambda: b.observe("Q09", wrong_url), "official_page_url_invalid")


def test_explicit_run_flag_required_before_import_or_queries():
    buf = io.StringIO()
    with patch.object(b, "__name__", "__unlikely__"), redirect_stdout(buf):
        try:
            b.main(["--case-ids", "Q09"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("missing --run-live must refuse")
    assert buf.getvalue() == ""
    for selection in ([], ["Q99"], ["Q09", "Q09"]):
        reject(lambda c=selection: b.capture(c, lambda _x: sample_result()),
               "invalid_case_selection")


def main():
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(name + ": PASS")
    print("KB03 ISSUE97 OFFLINE RANKING BASELINE CONTRACTS: PASS")


if __name__ == "__main__":
    main()
