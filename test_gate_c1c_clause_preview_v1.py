#!/usr/bin/env python3
"""Gate C1c synthetic contract tests: not a real 20-question quality score."""
import copy

from gate_c1c_clause_catalog_v1 import (
    APP145, APP149, DRAFT_INTENT_CLAUSES, OFFICIAL_URL, SOURCE_FILENAME,
    SOURCE_SHA256, REVIEW_STATUS,
)
from gate_c1c_clause_preview_v1 import ReviewRefused, preview_manual_intent


def fixture():
    # Synthetic minimal version of observed Q09 chunk ordering only.
    entries = (
        (APP149, 123, 3), (APP149, 119, 1), (APP149, 125, 5),
        (APP149, 126, 5), (APP149, 120, 1), (APP149, 121, 2),
        (APP149, 124, 4), (APP145, 116, 3),
    )
    return [{
        "id": "S" + str(i), "source_id": sid, "chunk_id": chunk,
        "page": page,
        "source_url": OFFICIAL_URL + SOURCE_FILENAME[sid] + "#page=" + str(page),
    } for i, (sid, chunk, page) in enumerate(entries, 1)]


def sha_map():
    return dict(SOURCE_SHA256)


def rank(result, source, chunk):
    return next(x["preview_rank"] for x in result["preview"]
                if x["source_id"] == source and x["chunk_id"] == chunk)


def test_manual_temp_absence_preview_is_draft_only_and_preserves_metadata():
    evidence = fixture()
    copy_before = copy.deepcopy(evidence)
    result = preview_manual_intent("as_temporary_absence", evidence, sha_map())
    assert rank(result, APP149, 121) == 1
    assert result["order_changed"]
    assert evidence == copy_before
    assert result["original"][5]["evidence_id"] == "S6"
    assert {x["evidence_id"] for x in result["original"]} == {
        x["evidence_id"] for x in result["preview"]}
    assert result["review_status"] == REVIEW_STATUS
    assert not result["release_authorized"]
    assert not result["professional_gold_approved"]
    assert not result["intent_detector_implemented"]
    assert not result["runtime_wired"]


def test_two_distinct_as_forms_do_not_conflate():
    change = preview_manual_intent(
        "as_change_notification_form", fixture(), sha_map())
    temp = preview_manual_intent(
        "as_temporary_nomination_form", fixture(), sha_map())
    assert rank(change, APP149, 124) == 1
    assert rank(temp, APP149, 125) == 1
    assert rank(change, APP149, 125) > 1
    assert rank(temp, APP149, 124) > 1
    assert all(not p["release_authorized"] for p in (change, temp))


def test_relevant_original_first_remains_first_for_own_purpose():
    e = fixture()
    p = preview_manual_intent("as_absence_over_30_days", e, sha_map())
    assert rank(p, APP149, 123) == 1
    assert not p["order_changed"]
    p2 = preview_manual_intent("fire_compliance_difficulty", e, sha_map())
    assert rank(p2, APP145, 116) == 1
    assert p2["review_status"] == REVIEW_STATUS


def test_unknown_and_ambiguous_and_missing_target_fall_back_original():
    e = fixture()
    for code in ("", "as_unspecified", "as_change_vs_temporary", "Q09"):
        p = preview_manual_intent(code, e, sha_map())
        assert not p["order_changed"]
        assert p["preview"] == p["original"]
        assert p["fallback_reason"] == "MANUAL_INTENT_UNKNOWN_OR_AMBIGUOUS"
    p = preview_manual_intent("fire_legacy_exception", e, sha_map())
    assert p["fallback_reason"] == "REVIEW_TARGET_NOT_RETRIEVED"
    assert p["preview"] == p["original"]


def test_source_revision_change_blocks_preview():
    s = sha_map()
    s[APP149] = "0" * 64
    p = preview_manual_intent("as_temporary_absence", fixture(), s)
    assert p["preview"] == p["original"]
    assert p["fallback_reason"] == "SOURCE_SHA_MISMATCH"
    assert not p["release_authorized"]


def test_invalid_metadata_or_source_sha_refused():
    def refused(rows, hashes):
        try:
            preview_manual_intent("as_temporary_absence", rows, hashes)
        except ReviewRefused:
            return
        raise AssertionError("invalid_input_accepted")
    e = fixture()
    bad = copy.deepcopy(e)
    bad[0]["id"] = "S2"
    refused(bad, sha_map())
    bad = copy.deepcopy(e)
    bad[1]["chunk_id"] = True
    refused(bad, sha_map())
    bad = copy.deepcopy(e)
    bad[1]["source_url"] = "https://untrusted.test/foo"
    refused(bad, sha_map())
    bad = copy.deepcopy(e)
    bad[1]["content"] = "PRIVATE EXCERPT SHOULD NOT BE LOGGED"
    refused(bad, sha_map())
    refused(e, {APP149: SOURCE_SHA256[APP149]})
    refused(e, {APP149: SOURCE_SHA256[APP149], APP145: "abc"})


def test_no_runtime_wiring_or_external_side_effects():
    import inspect
    import gate_c1c_clause_preview_v1 as module
    import gate_c1c_clause_catalog_v1 as source
    text = inspect.getsource(module) + inspect.getsource(source)
    assert "import requests" not in text
    assert "import psycopg" not in text
    assert "import subprocess" not in text
    assert "import beta_private_ui" not in text
    assert "open(" not in text
    assert len(DRAFT_INTENT_CLAUSES) == 9
    p = preview_manual_intent("as_temporary_absence", fixture(), sha_map())
    assert "content" not in str(p)
    assert "query" not in p
    assert not p["source_currentness_verified"]
    assert not p["sufficiency_verified"]


def main():
    tests = (
        test_manual_temp_absence_preview_is_draft_only_and_preserves_metadata,
        test_two_distinct_as_forms_do_not_conflate,
        test_relevant_original_first_remains_first_for_own_purpose,
        test_unknown_and_ambiguous_and_missing_target_fall_back_original,
        test_source_revision_change_blocks_preview,
        test_invalid_metadata_or_source_sha_refused,
        test_no_runtime_wiring_or_external_side_effects,
    )
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("GATE_C1C_MANUAL_CLAUSE_PREVIEW_OFFLINE: PASS")
    print("DRAFT_INTENTS_ONLY / NO_AUTO_CLASSIFICATION / NO_RELEASE")


if __name__ == "__main__":
    main()
