#!/usr/bin/env python3
"""Gate C1c OFFLINE-ONLY, human-intent clause ordering preview.

Never imported by the Private Beta UI. Does not receive question text,
source excerpts, embeddings or tokens. Does not infer user intent.
No files, network, DB, AI provider, legal assertion or persistent side effect.
"""
import re

from gate_c1c_clause_catalog_v1 import (
    APP145, APP149, DRAFT_INTENT_CLAUSES, OFFICIAL_URL, REVIEW_STATUS,
    SOURCE_FILENAME, SOURCE_SHA256, VERSION,
)


class ReviewRefused(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise ReviewRefused(reason)


def _validate_rows(rows):
    require(type(rows) in (tuple, list) and 1 <= len(rows) <= 16,
            "candidate_count_invalid")
    visited = set()
    for rank, item in enumerate(rows, 1):
        require(type(item) is dict and
                set(item) == {"id", "source_id", "chunk_id", "page", "source_url"},
                "metadata_only_shape_required")
        sid, chunk, page = item["source_id"], item["chunk_id"], item["page"]
        require(item["id"] == "S" + str(rank), "original_rank_ids_changed")
        require(sid in (APP145, APP149) and
                type(chunk) is int and chunk > 0 and
                type(page) is int and page > 0, "unapproved_source_or_anchor")
        key = sid, chunk
        require(key not in visited, "duplicate_source_chunk")
        visited.add(key)
        url = OFFICIAL_URL + SOURCE_FILENAME[sid] + "#page=" + str(page)
        require(item["source_url"] == url, "untrusted_citation_url")


def _rows_without_mutation(rows):
    return tuple({
        "evidence_id": item["id"], "original_rank": rank,
        "preview_rank": rank, "source_id": item["source_id"],
        "chunk_id": item["chunk_id"], "page": item["page"],
    } for rank, item in enumerate(rows, 1))


def preview_manual_intent(intent_code, rows, observed_sha256):
    """DRAFT preview, never approved/activated. Unknown -> original order."""
    _validate_rows(rows)
    require(type(observed_sha256) is dict, "sha_map_required")
    require(type(intent_code) is str, "intent_code_required")
    original = _rows_without_mutation(rows)
    source_ids = {item["source_id"] for item in rows}
    # Do not allow unused or unreviewed source identities into this sample.
    require(set(observed_sha256) == source_ids, "sha_source_set_mismatch")
    for val in observed_sha256.values():
        require(type(val) is str and re.fullmatch(r"[0-9a-f]{64}", val),
                "invalid_sha256_format")

    mismatch = any(observed_sha256[s] != SOURCE_SHA256[s]
                   for s in source_ids)
    code = intent_code.strip()
    purpose = DRAFT_INTENT_CLAUSES.get(code)
    reason = ("SOURCE_SHA_MISMATCH" if mismatch else
              "MANUAL_INTENT_UNKNOWN_OR_AMBIGUOUS" if purpose is None else
              "DRAFT_PREVIEW_NOT_ACTIVATABLE")
    # A missing reviewed target is not evidence of source relevance.
    if mismatch or purpose is None or not any(
            (row["source_id"], row["chunk_id"]) in purpose for row in rows):
        if not mismatch and purpose is not None:
            reason = "REVIEW_TARGET_NOT_RETRIEVED"
        candidate = original
        changed = False
    else:
        # Only a preview of a human-authored exact clause priority map.
        # Unsupported chunks retain their original order and are NOT lost.
        positions = {key: i for i, key in enumerate(purpose)}
        reordered = sorted(
            enumerate(rows, 1),
            key=lambda pair: (0, positions[(pair[1]["source_id"],
                                            pair[1]["chunk_id"])])
            if (pair[1]["source_id"], pair[1]["chunk_id"]) in positions
            else (1, pair[0]),
        )
        candidate = tuple({
            "evidence_id": row["id"], "original_rank": original_rank,
            "preview_rank": preview_rank, "source_id": row["source_id"],
            "chunk_id": row["chunk_id"], "page": row["page"],
        } for preview_rank, (original_rank, row) in enumerate(reordered, 1))
        changed = tuple(x["evidence_id"] for x in candidate) != tuple(
            x["evidence_id"] for x in original)

    return {
        "version": VERSION,
        "scope": "OFFLINE_EXPLICIT_MANUAL_INTENT_ONLY",
        "review_status": REVIEW_STATUS,
        "intent_detector_implemented": False,
        "candidate_preview_only": True,
        "release_authorized": False,
        "professional_gold_approved": False,
        "source_currentness_verified": False,
        "sufficiency_verified": False,
        "runtime_wired": False,
        "fallback_reason": reason,
        "order_changed": changed,
        "original": original,
        "preview": candidate,
    }
