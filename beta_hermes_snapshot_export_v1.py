#!/usr/bin/env python3
"""Export an APPROVED Staging PNAP source as a bounded, self-contained JSON snapshot.

Operator-only trusted-side export; reads Staging DB through existing validated
code, but never runs in Hermes. Output stdout only: caller decides where to
store the file. This does not open a port or change database/Drive/Production.
"""

import argparse
import json
import sys

from beta_ask_staging_v1 import (
    ALLOWED, BetaRefused, approved_source, check_checkout,
)
from validate_canonical_text_staging_milestone_v1 import (
    build_integrity_sql, parse_integrity_payload, validate_integrity,
)
from validate_staging_retrieval_v2 import (
    run_staging_query, validate_checksum,
)

VERSION = "hermes-approved-snapshot-v0.1"
MAX_CHUNKS = 32
MAX_TEXT_CHARS = 150000


def build_all_chunks_sql(checksum):
    """Exactly one approved SHA per SQL statement, no query/URL interpolation."""
    value = validate_checksum(checksum)
    return f"""
SELECT COALESCE(json_agg(json_build_object(
    'chunk_id', c.id,
    'page_start', c.page_start,
    'page_end', c.page_end,
    'evidence_origin', c.metadata->>'evidence_origin',
    'evidence_tier', c.metadata->>'evidence_tier',
    'retrieval_role', c.metadata->>'retrieval_role',
    'text', c.content
) ORDER BY c.id), '[]'::json)::text
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.checksum_sha256 = '{value}';
""".strip()


def validate_all_chunks(rows, expected_count):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CHUNKS:
        raise BetaRefused("snapshot_chunk_count_refused")
    if len(rows) != expected_count:
        raise BetaRefused("snapshot_chunk_count_mismatch")

    seen = set()
    output = []
    char_count = 0
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise BetaRefused("invalid_snapshot_chunk")
        chunk_id = row.get("chunk_id")
        page = row.get("page_start")
        end = row.get("page_end")
        content = row.get("text")
        if type(chunk_id) is not int or chunk_id <= 0 or chunk_id in seen:
            raise BetaRefused("snapshot_chunk_identity_refused")
        seen.add(chunk_id)
        if type(page) is not int or page <= 0:
            raise BetaRefused("snapshot_page_missing")
        if end is not None and (type(end) is not int or end < page):
            raise BetaRefused("snapshot_page_range_invalid")
        if (
            row.get("evidence_origin") != "native_text"
            or row.get("evidence_tier") != "primary"
            or row.get("retrieval_role") != "text-primary"
        ):
            raise BetaRefused("snapshot_evidence_tier_refused")
        if not isinstance(content, str) or not content.strip():
            raise BetaRefused("snapshot_empty_text")
        char_count += len(content)
        if char_count > MAX_TEXT_CHARS:
            raise BetaRefused("snapshot_text_budget_exceeded")
        output.append({
            "id": "P" + str(index),
            "chunk_id": chunk_id,
            "pdf_page_start": page,
            "pdf_page_end": end if end is not None else page,
            "text": content,
        })
    return output


def build_snapshot(source_id):
    if source_id not in ALLOWED:
        raise BetaRefused("snapshot_source_not_allowlisted")
    check_checkout()
    source = approved_source(source_id)
    integrity = validate_integrity(
        parse_integrity_payload(
            run_staging_query(build_integrity_sql(source["checksum"]))
        ),
        source["canonical_source"],
    )
    raw = run_staging_query(build_all_chunks_sql(source["checksum"]))
    try:
        rows = json.loads(raw.strip())
    except (TypeError, ValueError):
        raise BetaRefused("snapshot_json_invalid") from None

    chunks = validate_all_chunks(rows, integrity["chunk_count"])
    return {
        "schema_version": VERSION,
        "environment": "staging",
        "source_id": source_id,
        "official_title": source["title"],
        "official_pdf_url": source["official_url"],
        "approved_pdf_sha256": source["checksum"],
        "revision_date": "NOT_VERIFIED",
        "current_legal_applicability": "NOT_VERIFIED",
        "read_only_source": True,
        "answer": None,
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export full approved Staging APP145/149 text evidence as JSON")
    parser.add_argument("--source", required=True, choices=ALLOWED)
    args = parser.parse_args()
    try:
        result = build_snapshot(args.source)
    except (BetaRefused, RuntimeError, ValueError, OSError):
        print(json.dumps({
            "schema_version": VERSION,
            "status": "REFUSED",
            "answer": None,
        }))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
