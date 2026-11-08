#!/usr/bin/env python3
"""Dormant Private Beta P1 assessor: reviewed *negative* corpus gaps only.

This pure adapter is deliberately NOT wired into the running Private Beta.
No source reads, network/model calls, DB writes or ranking changes occur here.
A future reviewed integration must keep the existing currentness and integrity
fail-closed guards ahead of this assessment and feature-flag it OFF by default.
"""

import re

VERSION = "source-capability-review-v0.1"
SOURCES = frozenset(("BD_PNAP_APP145", "BD_PNAP_APP149"))
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _result(assessment="NOT_VERIFIED", *, method="NOT_ASSESSED",
            reason_codes=(), version=None):
    return {
        "assessment": assessment,
        "method": method,
        "reason_codes": list(reason_codes),
        "capability_contract_version": version,
    }


def _text(value):
    """Whitespace-only canonicalization. Never fuzzily expand question intent."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _sha_map(sources):
    if not isinstance(sources, (list, tuple)) or len(sources) != len(SOURCES):
        return None
    actual = {}
    for item in sources:
        if not isinstance(item, dict):
            return None
        sid, sha = item.get("source_id"), item.get("sha256")
        if sid not in SOURCES or not isinstance(sha, str) or not _SHA.fullmatch(sha):
            return None
        if sid in actual:
            return None
        actual[sid] = sha
    return actual if set(actual) == SOURCES else None


def _approved_contract(contract):
    """Check the minimal approval boundary, not professional truth itself.

    Approval details must be separately signed off and code-reviewed. Having a
    structurally valid fixture is *not* itself an independent Gold assessment.
    """
    if not isinstance(contract, dict) or contract.get("schema_version") != VERSION:
        return False
    if contract.get("review_status") != "APPROVED":
        return False
    if not all(_text(contract.get(k)) for k in
               ("review_id", "reviewer_qualification", "reviewed_at")):
        return False
    pins = contract.get("source_sha256")
    if not isinstance(pins, dict) or set(pins) != SOURCES:
        return False
    if not all(isinstance(v, str) and _SHA.fullmatch(v) for v in pins.values()):
        return False
    cases = contract.get("negative_cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        return False
    seen_ids, seen_questions = set(), set()
    for case in cases:
        if not isinstance(case, dict):
            return False
        case_id = case.get("case_id")
        variants = case.get("reviewed_questions")
        if (not isinstance(case_id, str) or not case_id.strip()
                or case_id in seen_ids
                or case.get("review_ref") is None
                or not _text(case.get("review_ref"))
                or case.get("reason_code") != "DOCUMENT_CAPABILITY_GAP"
                or case.get("scope") != "APPROVED_CORPUS_ONLY"
                or not isinstance(variants, list)
                or not 1 <= len(variants) <= 20):
            return False
        seen_ids.add(case_id)
        for item in variants:
            text = _text(item)
            if not text or len(text) > 1200 or text in seen_questions:
                return False
            seen_questions.add(text)
    return True


def assess(question, sources, contract=None, *, enabled=False):
    """Return an additive negative-only assessment; never claim sufficiency.

    Only exact reviewer-approved question variants qualify. Anything unclear,
    unreviewed, changed, disabled or out of approved source scope stays
    NOT_VERIFIED, with no alteration to the caller's evidence or status.
    """
    if enabled is not True:
        return _result()
    actual = _sha_map(sources)
    if (actual is None or not _approved_contract(contract)
            or actual != contract["source_sha256"]):
        return _result(reason_codes=("GATE_UNAVAILABLE",))
    normalized = _text(question)
    if not normalized or len(normalized) > 1200:
        return _result(reason_codes=("GATE_UNAVAILABLE",))
    for case in contract["negative_cases"]:
        if normalized in {_text(q) for q in case["reviewed_questions"]}:
            return _result(
                "INSUFFICIENT", method="SOURCE_CAPABILITY_REVIEW_V1",
                reason_codes=("DOCUMENT_CAPABILITY_GAP",), version=VERSION)
    return _result(method="SOURCE_CAPABILITY_REVIEW_V1", version=VERSION)
