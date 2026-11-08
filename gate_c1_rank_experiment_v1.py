#!/usr/bin/env python3
"""Gate C-1 pure in-memory ranking experiments; NEVER used by the Beta API.

These are presentation-order HYPOTHESES, not semantic correctness, Gold labels,
or legal evidence sufficiency. There are no file, DB, network or model calls.
"""
import re

VERSION = "gate-c1-rank-experiment-v0.1"
POLICIES = ("original", "source_cohesion", "source_cohesion_form_aware")
FORM_REQUEST = re.compile(r"表格|表單|附錄|\b(?:forms?|appendix|template)\b", re.I)
FORM_LIKE = re.compile(
    r"\bappendix\s+[a-z]\b|\bnotification of (?:change|nomination)\b|_{4,}",
    re.I,
)


class ExperimentRefused(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise ExperimentRefused(reason)


def _validate_evidence(evidence):
    require(type(evidence) is list and 1 <= len(evidence) <= 32,
            "invalid_candidate_list")
    seen = set()
    for rank, item in enumerate(evidence, 1):
        require(type(item) is dict and
                {"id", "source_id", "chunk_id", "page", "content",
                 "source_url"} <= set(item), "invalid_evidence_shape")
        sid, cid, page = item["source_id"], item["chunk_id"], item["page"]
        require(item["id"] == "S" + str(rank), "original_rank_ids_changed")
        require(type(sid) is str and
                re.fullmatch(r"[A-Za-z0-9_-]{3,70}", sid) is not None,
                "invalid_source_id")
        require(type(cid) is int and cid > 0 and
                type(page) is int and page >= 1, "invalid_chunk_or_page")
        require((sid, cid) not in seen, "duplicate_evidence_chunk")
        seen.add((sid, cid))
        require(type(item["content"]) is str and
                1 <= len(item["content"]) <= 15000, "invalid_candidate_text")
        url = item["source_url"]
        require(type(url) is str and
                url.startswith("https://www.bd.gov.hk/") and
                url.endswith("#page=" + str(page)), "invalid_source_page_url")


def propose_order(question, evidence, policy="original"):
    """Return ONLY rank/identity metadata; never mutate evidence or emit text.

    Source cohesion groups by the source of the first original hit. Form-aware
    is an UNCALIBRATED structural probe, not a blanket appendix penalty.
    All original S IDs and page URLs stay exclusively in the caller's data.
    """
    require(type(question) is str and 5 <= len(question.strip()) <= 1200,
            "invalid_question")
    require(policy in POLICIES, "invalid_policy")
    _validate_evidence(evidence)
    rows = list(enumerate(evidence, 1))
    first_source_rank = {}
    for rank, item in rows:
        first_source_rank.setdefault(item["source_id"], rank)
    asks_for_form = FORM_REQUEST.search(question) is not None

    if policy == "source_cohesion":
        rows.sort(key=lambda entry: (
            first_source_rank[entry[1]["source_id"]], entry[0]))
    elif policy == "source_cohesion_form_aware":
        rows.sort(key=lambda entry: (
            first_source_rank[entry[1]["source_id"]],
            0 if (FORM_LIKE.search(entry[1]["content"]) is not None)
            == asks_for_form else 1,
            entry[0],
        ))
    return {
        "version": VERSION,
        "scope": "OFFLINE_STAGING_EXPERIMENT_ONLY",
        "policy": policy,
        "form_request_detected": asks_for_form,
        "candidates": [
            {
                "evidence_id": item["id"],
                "original_rank": old_rank,
                "candidate_rank": new_rank,
                "source_id": item["source_id"],
                "chunk_id": item["chunk_id"],
                "page": item["page"],
            }
            for new_rank, (old_rank, item) in enumerate(rows, 1)
        ],
    }


def candidate_anchor_rank(report, source_id, chunk_ids):
    """Score a DRAFT test anchor without declaring that it is Gold."""
    ranks = [
        item["candidate_rank"] for item in report["candidates"]
        if item["source_id"] == source_id and item["chunk_id"] in chunk_ids
    ]
    return min(ranks) if ranks else None
