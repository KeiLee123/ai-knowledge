#!/usr/bin/env python3
"""M11B: one literal APP149 evidence -> historical TEST-only Anki preview.

Reuses the existing M10 Silver verifier, Private Beta Staging read-only
retrieval, and Anki card formatter. Never calls a model, writes a database,
creates a package, imports Anki, or changes the running Private Beta UI.
A candidate is only literal-source checked, NOT legally/semantically verified.
"""
import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path

import beta_ask_staging_v1 as qa
from generate_anki_cards_v1 import SCHEMA_VERSION, make_card
from m10b2f_offline_silver_evidence_v1 import HIGH_RISK_TERMS, normalize
from m10b2g_app149_readonly_silver_pilot_v1 import (
    PINNED_DOCUMENT_VERSION, PINNED_PDF_SHA256, PINNED_SOURCE_ID,
    build_app149_candidate_suite, run_app149_readonly_pilot,
)

VERSION = "m11b-literal-evidence-anki-preview-v1"
CASE_ID = "APP149-SILVER-L01"
ANSWER_LITERAL = "authorized signatory"
OFFICIAL_URL = (
    "https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
    "practice-notes-and-circular-letters/pnap/APP/APP149.pdf"
)


class PreviewRefused(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise PreviewRefused(reason)


def hold(reason):
    return {
        "version": VERSION,
        "environment": "staging",
        "source_id": PINNED_SOURCE_ID,
        "source_sha256": PINNED_PDF_SHA256,
        "document_version": PINNED_DOCUMENT_VERSION,
        "candidate_status": "AUTO_HOLD",
        "hold_reason": reason,
        "quality": {
            "mechanical_quote_page_checked": False,
            "semantic_answer_accuracy": "UNKNOWN_NOT_MEASURED",
            "anki_card_accuracy": "UNKNOWN_NOT_MEASURED",
            "official_gold_approved": 0,
            "currentness_verified": False,
            "publish_authorized": False,
        },
        "manifest": None,
        "external_ai_called": False,
        "production_write": False,
        "canonical_drive_write": False,
        "anki_imported": False,
        "anki_package_created": False,
    }


def build_preview_from_verified_packet(packet, silver):
    """Only the single low-risk pinned positive literal case is eligible.

    All other four APP149 Silver drafts remain held, not silently promoted.
    A successful preview can be exported only by a later explicit TEST step.
    """
    suite = build_app149_candidate_suite()
    case = next(c for c in suite["cases"] if c["case_id"] == CASE_ID)
    require(case["case_type"] == "POSITIVE"
            and case["expected_physical_pdf_page"] == 1,
            "pinned_case_contract_changed")
    require(ANSWER_LITERAL in normalize(case["evidence_quote"])
            and not HIGH_RISK_TERMS.search(case["query"] + " " +
                                           case["evidence_quote"]),
            "pinned_low_risk_literal_contract_changed")
    require(type(packet) is dict and type(silver) is dict,
            "invalid_verification_payload")
    source = packet.get("source")
    coverage = packet.get("retrieval_coverage")
    require(type(source) is dict and type(coverage) is dict,
            "source_or_retrieval_coverage_missing")
    require(packet.get("environment") == "staging"
            and packet.get("database") == qa.STAGING_DB_CONTAINER
            and packet.get("guard_ok") is True
            and packet.get("read_only") is True
            and packet.get("production_write") is False
            and packet.get("question") == case["query"],
            "not_pinned_staging_evidence_packet")
    require(source.get("source_id") == PINNED_SOURCE_ID
            and source.get("checksum") == PINNED_PDF_SHA256
            and source.get("official_url") == OFFICIAL_URL
            and source.get("currentness_verified") is False,
            "source_identity_or_currentness_refused")
    require(coverage.get("complete_index_coverage") is True
            and type(coverage.get("indexed_chunks")) is int
            and coverage["indexed_chunks"] == 8
            and coverage.get("retrieved_unique_chunks") == 8,
            "incomplete_retrieval_refused")
    require(silver.get("source_id") == PINNED_SOURCE_ID
            and silver.get("expected_original_pdf_sha256") == PINNED_PDF_SHA256
            and silver.get("source_version") == PINNED_DOCUMENT_VERSION
            and silver.get("case_count") == 5
            and silver.get("human_gold_cases_approved") == 0
            and silver.get("counts") == {
                "MACHINE_EVIDENCE_CHECKED": 1,
                "HUMAN_REVIEW_REQUIRED": 4,
                "REJECTED_EVIDENCE_MISMATCH": 0,
            }, "silver_profile_mismatch")
    rows = silver.get("cases")
    require(type(rows) is list and len(rows) == 5,
            "silver_case_inventory_invalid")
    selected = [r for r in rows if r.get("case_id") == CASE_ID]
    require(len(selected) == 1
            and selected[0].get("status") == "MACHINE_EVIDENCE_CHECKED"
            and selected[0].get("official_gold_approved") is False
            and selected[0].get("human_reviewed") is False,
            "pinned_literal_not_verified")
    require(all(r.get("status") == "HUMAN_REVIEW_REQUIRED"
                for r in rows if r.get("case_id") != CASE_ID),
            "held_legal_cases_status_changed")

    # One unique native-text retrieval chunk must contain the SAME Silver quote.
    # Matching exact text is not independent confirmation of legal semantics.
    evidence = packet.get("evidence")
    require(type(evidence) is list and len(evidence) == 8,
            "missing_source_chunks")
    hits = [r for r in evidence if type(r) is dict
            and r.get("page") == 1
            and type(r.get("chunk_id")) is int and r["chunk_id"] > 0
            and type(r.get("content")) is str
            and normalize(case["evidence_quote"]) in normalize(r["content"])
            and normalize(ANSWER_LITERAL) in normalize(r["content"])]
    if len(hits) != 1:
        return hold("UNIQUE_SOURCE_CHUNK_NOT_VERIFIED")
    match = hits[0]
    if sum(normalize(case["evidence_quote"]) in normalize(r.get("content", ""))
           for r in evidence if type(r) is dict) != 1:
        return hold("QUOTE_REPEATED_ACROSS_CHUNKS")

    locator = {
        # Source ID is NOT the database documents.id; do not fabricate one.
        "document_id": None,
        "document_title": source.get("title") or "APP149",
        "document_checksum": PINNED_PDF_SHA256,
        "chunk_id": match["chunk_id"],
        "page_start": 1,
        "page_end": 1,
        "source_type": "official_public_pdf",
        "source_url": OFFICIAL_URL + "#page=1",
        "source_filename": "APP149.pdf",
        "locator_label": "APP149 (2010-12), PDF p.1",
    }
    chunk = {
        "document_checksum": PINNED_PDF_SHA256,
        "content": match["content"],
        "domain": "building",
        "topic": "historical_source_term",
    }
    generated = {
        "card_type": "text_recall",
        "question": ("In the historical APP149 (2010-12) text, "
                     "what is the appointed person of a PRC commonly called?"),
        "answer": ANSWER_LITERAL,
        "explanation": ("Literal terminology from the pinned APP149 source. "
                        "Not a statement of current legal applicability."),
        "related_knowledge": [],
    }
    card = make_card(chunk, locator, generated)
    card["tags"].extend([
        "test_only", "auto_evidence_checked", "not_human_verified",
        "currentness_unverified", "historical_source_2010_12",
    ])
    card["quality"] = {
        "status": "AUTO_EVIDENCE_CHECKED_NOT_HUMAN_VERIFIED",
        "evidence_case_id": CASE_ID,
        "exact_pdf_quote_page_verified": True,
        "semantic_answer_accuracy": "UNKNOWN_NOT_MEASURED",
        "legal_applicability_verified": False,
        "release_authorized": False,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": VERSION,
        "read_only": True,
        "database_write_performed": False,
        "deck": {"name": "Jason OS :: TEST ONLY :: Historical APP149 2010-12"},
        "generation": {
            "requested_chunk_ids": [match["chunk_id"]],
            "cards_per_chunk": 1,
            "generated_card_count": 1,
            "model_call_performed": False,
            "media_rendered": False,
            "anki_package_created": False,
            "literal_source_preview_only": True,
        },
        "cards": [card],
    }
    return {
        "version": VERSION,
        "environment": "staging",
        "source_id": PINNED_SOURCE_ID,
        "source_sha256": PINNED_PDF_SHA256,
        "document_version": PINNED_DOCUMENT_VERSION,
        "candidate_status": "TEST_ONLY_LITERAL_PREVIEW",
        "hold_reason": None,
        "quality": {
            "mechanical_quote_page_checked": True,
            "semantic_answer_accuracy": "UNKNOWN_NOT_MEASURED",
            "anki_card_accuracy": "UNKNOWN_NOT_MEASURED",
            "official_gold_approved": 0,
            "currentness_verified": False,
            "publish_authorized": False,
        },
        "manifest": manifest,
        "external_ai_called": False,
        "production_write": False,
        "canonical_drive_write": False,
        "anki_imported": False,
        "anki_package_created": False,
    }


def build_preview(pdf_path):
    path = Path(pdf_path)
    require(path.is_file() and not path.is_symlink(),
            "missing_or_symlink_pdf")
    require(100 <= path.stat().st_size <= 3_000_000,
            "invalid_pdf_size")
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == PINNED_PDF_SHA256,
            "pinned_pdf_sha_mismatch")
    # Independent M10 native-PDF literal/page/context check BEFORE Staging DB IO.
    silver = run_app149_readonly_pilot(data)
    case = next(c for c in build_app149_candidate_suite()["cases"]
                if c["case_id"] == CASE_ID)
    packet = qa.build_packet(PINNED_SOURCE_ID, case["query"])
    return build_preview_from_verified_packet(packet, silver)


def main():
    parser = argparse.ArgumentParser(
        description="Historical APP149 literal Anki TEST-only preview")
    parser.add_argument("--pdf", required=True,
                        help="Private temporary, SHA-pinned official APP149 PDF")
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        result = build_preview(args.pdf)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (PreviewRefused, qa.BetaRefused, RuntimeError, ValueError) as exc:
        raise SystemExit("M11B_PREVIEW_REFUSED: " + str(exc)) from None
