#!/usr/bin/env python3
"""M11 automation-only quality probe: APP149, Staging, no AI or writes.

Reuses previously implemented Document v2, pinned Silver evidence verifier,
and optional existing Staging read-only retrieval. This is NOT an answer
correctness benchmark, legal validity check, or production-ready Anki deck.
Results contain no questions, PDF excerpts, credentials, or review requests.
"""

import argparse
import contextlib
import hashlib
import json
import math
import sys
from pathlib import Path

import beta_ask_staging_v1 as qa
from extract_document_v2 import build_manifest
from m10b2g_app149_readonly_silver_pilot_v1 import (
    PINNED_PDF_SHA256, PINNED_PHYSICAL_PAGE_COUNT, PINNED_SOURCE_ID,
    run_app149_readonly_pilot,
)

VERSION = "m11-automated-quality-probe-v1"

# These pages were proposed in an existing pilot and are NOT human Gold.
RETRIEVAL_CANDIDATES = (
    ("APP149-DRAFT-P01",
     "暫代獲授權簽署人一般須提前多久通知屋宇署？突發疾病或意外有甚麼例外安排？", 2),
    ("APP149-DRAFT-P02",
     "暫時代理的 AS 最長可代理多少天？甚麼情況下可延長？", 2),
    ("APP149-DRAFT-M01",
     "臨時代理的 AS 可以簽署現場巡查紀錄；這是否代表亦可以簽署指定表格或監督計劃？", 3),
)


class AutoQualityRefused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise AutoQualityRefused(reason)


def summarize_document_manifest(manifest):
    """Mechanical extraction report; no OCR or legal accuracy claims."""
    require(isinstance(manifest, dict) and
            manifest.get("schema_version") == "document-manifest-v2",
            "manifest_contract_refused")
    source = manifest.get("source") or {}
    doc = manifest.get("document") or {}
    units = manifest.get("units")
    extraction = manifest.get("extraction") or {}
    summary = manifest.get("summary") or {}
    require(source.get("sha256") == PINNED_PDF_SHA256,
            "document_sha_mismatch")
    require(doc.get("kind") == "pdf" and
            doc.get("page_count") == PINNED_PHYSICAL_PAGE_COUNT,
            "document_page_count_refused")
    require(isinstance(units, list) and len(units) == PINNED_PHYSICAL_PAGE_COUNT
            and [x.get("page_number") for x in units] ==
            list(range(1, PINNED_PHYSICAL_PAGE_COUNT + 1)),
            "physical_page_sequence_refused")
    require(extraction.get("database_write_performed") is False and
            extraction.get("ocr_performed") is False and
            extraction.get("vision_model_used") is False,
            "unexpected_extractor_side_effect")
    require(all(isinstance(x.get("text"), str) for x in units),
            "invalid_page_text")
    require(type(summary.get("total_text_chars")) is int and
            summary["total_text_chars"] > 0,
            "empty_extracted_document")
    problem_pages = sorted(set(
        list(summary.get("ocr_candidate_units") or []) +
        list(summary.get("vector_candidate_units") or []) +
        [x["page_number"] for x in units
         if x.get("table_extraction_errors")]
    ))
    require(all(type(n) is int and 1 <= n <= PINNED_PHYSICAL_PAGE_COUNT
                for n in problem_pages), "invalid_problem_page")
    return {
        "schema": manifest["schema_version"],
        "source_sha256": source["sha256"],
        "physical_pages": PINNED_PHYSICAL_PAGE_COUNT,
        "extracted_text_chars": summary["total_text_chars"],
        "table_count_reported": summary.get("total_tables", 0),
        "ocr_or_vector_or_table_error_pages": problem_pages,
        "needs_separate_ocr_or_table_validation": bool(problem_pages),
        "extraction_is_not_legal_verification": True,
    }


def summarize_silver_verification(result):
    """Convert old human-review queue into automatic HOLD (not Gold)."""
    require(isinstance(result, dict) and
            result.get("source_id") == PINNED_SOURCE_ID and
            result.get("expected_original_pdf_sha256") == PINNED_PDF_SHA256,
            "silver_source_mismatch")
    counts = result.get("counts") or {}
    checked = counts.get("MACHINE_EVIDENCE_CHECKED")
    held = counts.get("HUMAN_REVIEW_REQUIRED")
    rejected = counts.get("REJECTED_EVIDENCE_MISMATCH")
    require(all(type(n) is int and n >= 0
                for n in (checked, held, rejected)),
            "silver_count_shape_refused")
    require(checked + held + rejected == result.get("case_count"),
            "silver_count_total_mismatch")
    require(result.get("gold_page_verified") is None and
            result.get("official_source_verified") is False and
            result.get("human_gold_cases_approved") == 0 and
            result.get("production_access") is False and
            result.get("write_authorized") is False,
            "silver_approval_or_side_effect_refused")
    return {
        "case_count": result["case_count"],
        "auto_evidence_checked": checked,
        "auto_hold_unverified": held,
        "auto_rejected_evidence": rejected,
        "not_human_verified": True,
        "official_gold_approved": 0,
        "machine_literal_checks_only": True,
        "safe_for_automatic_anki_publication": False,
    }


def summarize_retrieval_packet(packet, case_id, proposed_page):
    """Evidence integrity + candidate page rank. Page is NOT official Gold."""
    source = packet.get("source") or {}
    coverage = packet.get("retrieval_coverage") or {}
    evidence = packet.get("evidence") or []
    integrity = packet.get("integrity") or {}
    require(packet.get("environment") == "staging" and
            packet.get("production_write") is False and
            packet.get("read_only") is True and
            packet.get("guard_ok") is True,
            "unsafe_retrieval_context")
    require(source.get("source_id") == PINNED_SOURCE_ID and
            source.get("checksum") == PINNED_PDF_SHA256 and
            source.get("currentness_verified") is False,
            "retrieval_source_identity_refused")
    require(integrity.get("integrity_ok") is True,
            "retrieval_integrity_refused")
    require(coverage.get("complete_index_coverage") is True and
            coverage.get("retrieved_unique_chunks") ==
            coverage.get("indexed_chunks") == 8 and
            len(evidence) == 8,
            "retrieval_coverage_refused")
    ids = [item.get("chunk_id") for item in evidence]
    require(all(type(cid) is int and cid > 0 for cid in ids) and
            len(set(ids)) == len(ids),
            "retrieval_chunk_identity_refused")
    pages = []
    for item in evidence:
        page = item.get("page")
        distance = item.get("distance")
        require(type(page) is int and
                1 <= page <= PINNED_PHYSICAL_PAGE_COUNT and
                type(distance) in (int, float) and math.isfinite(distance) and
                isinstance(item.get("content"), str) and item["content"].strip(),
                "retrieval_evidence_invalid")
        pages.append(page)
    ranks = [i for i, page in enumerate(pages, 1) if page == proposed_page]
    return {
        "case_id": case_id,
        "proposed_page_not_official_gold": proposed_page,
        "first_proposed_page_rank": min(ranks) if ranks else None,
        "top_5_physical_pages": pages[:5],
        "all_indexed_chunks_returned": True,
        "answer_generated": False,
        "answer_correctness_verified": False,
    }


def run_retrieval_probe():
    results = []
    for case_id, question, proposed_page in RETRIEVAL_CANDIDATES:
        packet = qa.build_packet(PINNED_SOURCE_ID, question)
        results.append(summarize_retrieval_packet(packet, case_id, proposed_page))
    # The local current-law guard requires no additional DB query or AI call.
    source = {"source_id": PINNED_SOURCE_ID,
              "revision_date": "NOT_VERIFIED", "currentness_verified": False}
    decision = qa.currentness_abstention({
        "question": "截至2026年11月1日，現行法定限期是甚麼？",
        "source": source,
    })
    require(isinstance(decision, dict) and
            decision.get("status") == "CURRENTNESS_UNVERIFIED_ABSTAIN",
            "currentness_abstention_failed")
    return {
        "tested_source": PINNED_SOURCE_ID,
        "cases": results,
        "current_law_question": "CURRENTNESS_UNVERIFIED_ABSTAIN",
        "semantic_answer_accuracy": "NOT_MEASURED",
        "proposed_pages_are_not_official_gold": True,
    }


def build_report(pdf_path, *, include_retrieval=False):
    path = Path(pdf_path)
    require(path.is_file() and not path.is_symlink(), "pdf_path_refused")
    require(100 <= path.stat().st_size <= 3_000_000, "pdf_size_refused")
    pdf_bytes = path.read_bytes()
    require(hashlib.sha256(pdf_bytes).hexdigest() == PINNED_PDF_SHA256,
            "pdf_not_pinned_approved_copy")
    document = summarize_document_manifest(build_manifest(path))
    silver = summarize_silver_verification(run_app149_readonly_pilot(pdf_bytes))
    retrieval = run_retrieval_probe() if include_retrieval else None
    return {
        "version": VERSION,
        "environment": ("staging_retrieval_readonly" if include_retrieval
                        else "local_offline_pdf"),
        "source_id": PINNED_SOURCE_ID,
        "document": document,
        "evidence_verifier": silver,
        "retrieval": retrieval,
        "answer_correctness_accuracy": "UNKNOWN_NOT_MEASURED",
        "anki_card_accuracy": "UNKNOWN_NOT_MEASURED",
        "anki_package_created": False,
        "human_verification_requested": False,
        "human_gold_approved": 0,
        "external_ai_called": False,
        "production_write": False,
        "shared_db_write": False,
        "canonical_drive_write": False,
        "notice": ("Machine-checked source/page/quote evidence is not proof "
                   "of semantic answer correctness, legal applicability, "
                   "or approved Anki learning content. Risks are auto-held."),
    }


def main():
    parser = argparse.ArgumentParser(
        description="APP149 M11 automatic evidence/ingest probe (no human review)")
    parser.add_argument("--pdf", required=True,
                        help="Temporary local copy of pinned APP149 PDF")
    parser.add_argument("--with-staging-retrieval", action="store_true",
                        help="Read-only Staging DB and local embedding only")
    args = parser.parse_args()
    # PDF extraction libraries may print diagnostics on stdout. Keep stdout
    # strictly JSON for downstream tools; leave diagnostics/errors on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        result = build_report(
            args.pdf, include_retrieval=args.with_staging_retrieval)
    print(json.dumps(result, ensure_ascii=False, indent=2,
                     sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (AutoQualityRefused, qa.BetaRefused, ValueError, RuntimeError) as exc:
        raise SystemExit(
            "M11_AUTO_QUALITY_REFUSED: " + str(exc)) from None
