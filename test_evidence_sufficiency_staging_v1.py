#!/usr/bin/env python3
"""Synthetic, offline negative-only contract tests; NOT professional Gold QA."""

from copy import deepcopy
from pathlib import Path

import yaml

import evidence_sufficiency_staging_v1 as p1


SOURCES = [
    {"source_id": "BD_PNAP_APP145", "sha256": "a" * 64},
    {"source_id": "BD_PNAP_APP149", "sha256": "b" * 64},
]
QUESTION = "Synthetic technical parameter absent from reviewed corpus?"


def approved_fixture():
    return {
        "schema_version": p1.VERSION,
        "review_status": "APPROVED",  # synthetic fixture; not a real signoff
        "review_id": "synthetic-only-test-reference",
        "reviewer_qualification": "synthetic-only-test-qualification",
        "reviewed_at": "synthetic-only",
        "source_sha256": {s["source_id"]: s["sha256"] for s in SOURCES},
        "negative_cases": [{
            "case_id": "synthetic-gap-1",
            "review_ref": "synthetic-only-review-reference",
            "reason_code": "DOCUMENT_CAPABILITY_GAP",
            "scope": "APPROVED_CORPUS_ONLY",
            "reviewed_questions": [QUESTION, "Synthetic paraphrase of missing parameter?"],
        }],
    }


def test_default_disabled_cannot_assert_insufficiency():
    r = p1.assess(QUESTION, SOURCES, approved_fixture())
    assert r["assessment"] == "NOT_VERIFIED" and r["method"] == "NOT_ASSESSED"


def test_repo_manifest_is_pending_and_empty():
    path = Path(__file__).with_name("evidence_sufficiency_capabilities_staging_v1.yaml")
    pending = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert pending["review_status"] == "PENDING"
    assert pending["negative_cases"] == []
    assert p1.assess(QUESTION, SOURCES, pending, enabled=True)["assessment"] == "NOT_VERIFIED"


def test_only_exact_synthetic_approved_variant_can_be_negative():
    c = approved_fixture()
    for q in c["negative_cases"][0]["reviewed_questions"]:
        r = p1.assess(q, SOURCES, c, enabled=True)
        assert r["assessment"] == "INSUFFICIENT"
        assert r["reason_codes"] == ["DOCUMENT_CAPABILITY_GAP"]
    assert p1.assess(QUESTION + " Also explain fire safety?", SOURCES, c,
                     enabled=True)["assessment"] == "NOT_VERIFIED"
    assert p1.assess("Real question in approved sources?", SOURCES, c,
                     enabled=True)["assessment"] == "NOT_VERIFIED"
    assert p1.assess("Synthetic technical parameter absent from reviewed corpus!",
                     SOURCES, c, enabled=True)["assessment"] == "NOT_VERIFIED"


def test_sha_scope_and_source_fidelity():
    c = approved_fixture()
    source_before = deepcopy(SOURCES)
    source_bad = deepcopy(SOURCES)
    source_bad[0]["sha256"] = "c" * 64
    assert p1.assess(QUESTION, source_bad, c, enabled=True)["assessment"] == "NOT_VERIFIED"
    assert p1.assess(QUESTION, SOURCES[:1], c, enabled=True)["assessment"] == "NOT_VERIFIED"
    assert p1.assess(QUESTION, SOURCES + [SOURCES[0]], c, enabled=True)["assessment"] == "NOT_VERIFIED"
    assert SOURCES == source_before
    assert p1.assess(QUESTION, SOURCES, c, enabled=True)["assessment"] == "INSUFFICIENT"


def test_incomplete_approval_and_invalid_cases_fail_safe():
    for mutate in (
        lambda c: c.update(review_status="PENDING"),
        lambda c: c.update(review_id=""),
        lambda c: c.update(negative_cases=[]),
        lambda c: c["negative_cases"][0].update(scope="ALL_GOVERNMENT"),
        lambda c: c["negative_cases"][0].update(reason_code="SIMILARITY_LOW"),
        lambda c: c["negative_cases"][0].update(review_ref=""),
        lambda c: c["negative_cases"][0]["reviewed_questions"].append(QUESTION),
    ):
        c = approved_fixture()
        mutate(c)
        r = p1.assess(QUESTION, SOURCES, c, enabled=True)
        assert r["assessment"] == "NOT_VERIFIED"
        assert "GATE_UNAVAILABLE" in r["reason_codes"]


def test_never_returns_positive_sufficient_or_answer():
    for r in (
        p1.assess(QUESTION, SOURCES, approved_fixture()),
        p1.assess(QUESTION, SOURCES, approved_fixture(), enabled=True),
        p1.assess("unreviewed", SOURCES, approved_fixture(), enabled=True),
    ):
        assert r["assessment"] in ("NOT_VERIFIED", "INSUFFICIENT")
        assert "answer" not in r and "citations" not in r


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(fn.__name__ + ": PASS")
    print("P1 DORMANT NEGATIVE-ONLY OFFLINE CONTRACT: PASS")
