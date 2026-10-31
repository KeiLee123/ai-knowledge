#!/usr/bin/env python3
"""M10B-2G: strictly pinned, in-memory APP149 read-only Silver pilot.

Accepts an operator-supplied original PDF byte stream, NOT a URL or path.
No network, file operations, database, model, source promotion or Gold approval.
The original official-site bytes have NOT been independently matched to
the Drive copy: exact local SHA matching is necessary but not sufficient.
"""
import hashlib

from m10b2f_offline_silver_evidence_v1 import (
    EvidenceContractError, SCOPE, SUITE_VERSION,
    verify_silver_candidate_suite,
)

VERSION = "m10b2g-app149-readonly-silver-pilot-v1"
PINNED_SOURCE_ID = "BD_PNAP_APP149"
PINNED_DOCUMENT_VERSION = "2010-12"
PINNED_PDF_SHA256 = (
    "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8"
)
PINNED_PHYSICAL_PAGE_COUNT = 5
SUITE_ID = "app149-readonly-silver-candidates-v1"
EXPECTED_CASE_IDS = (
    "APP149-SILVER-L01", "APP149-DRAFT-P01", "APP149-DRAFT-P02",
    "APP149-DRAFT-M01", "APP149-DRAFT-N01",
)
CASE_RECORDS = (
    # One simple literal fact to demonstrate machine-checked evidence.
    # NOT one of the four pending human-reviewed Gold drafts.
    (
        "APP149-SILVER-L01", "POSITIVE",
        "What is the appointed person of a PRC commonly called?",
        1, "commonly known as the “authorized signatory” (AS) of the PRC.",
        "This appointed person is",
        "Under section 9AA(6) of the BO, a PRC should",
    ),
    (
        "APP149-DRAFT-P01", "POSITIVE",
        "When is absence notification due and what if illness is sudden?",
        2,
        "at least 7 days prior to the absence of the AS except in case of sudden "
        "illness or accident. In the latter case, the PRC or the AS should "
        "provide documentary proof within 3 days",
        "The notification should be submitted",
        "showing that the AS is unable to act due to illness or accident;",
    ),
    (
        "APP149-DRAFT-P02", "POSITIVE",
        "What is the temporary acting period and the extension condition?",
        2,
        "14 days. Further extension of this acting period would only be considered",
        "The maximum period of temporary acting by the nominated AS is",
        "upon submission of documentary proof of special circumstances, such "
        "as illness.",
    ),
    (
        "APP149-DRAFT-M01", "NEAR_MISS",
        "Can a temporary AS sign specified forms or supervision plans?",
        3,
        "is not permitted to sign on any supervision plans or specified forms",
        "the nominated temporary AS, being not the AS appointed to act for the "
        "PRC for the submission as stipulated in paragraph 2 above,",
        "for the submission for which he is only acting temporarily",
    ),
    (
        "APP149-DRAFT-N01", "NEGATIVE",
        "Does APP-149 specify a fixed filing fee for nominating a temporary AS?",
        None, None, None, None,
    ),
)


def build_app149_candidate_suite():
    """Construct a new exact-contract Silver candidate set each call.

    No PDF text or complete PDF is committed to GitHub. Quotes are short
    snippets for local, read-only equality checks. This is curated pilot
    data, not an automated question generator.
    """
    cases = []
    for cid, kind, query, page, quote, before, after in CASE_RECORDS:
        cases.append({
            "case_id": cid,
            "case_type": kind,
            "source_id": PINNED_SOURCE_ID,
            "original_pdf_sha256": PINNED_PDF_SHA256,
            "query": query,
            "expected_physical_pdf_page": page,
            "evidence_quote": quote,
            "context_before": before,
            "context_after": after,
        })
    return {
        "version": SUITE_VERSION,
        "scope": SCOPE,
        "suite_id": SUITE_ID,
        "source_id": PINNED_SOURCE_ID,
        "document_version": PINNED_DOCUMENT_VERSION,
        "original_pdf_sha256": PINNED_PDF_SHA256,
        "cases": cases,
    }


def verify_pinned_silver_profile(
    pdf_bytes, suite, *, expected_sha, expected_page_count, expected_source_id
):
    """Reusable core for CI with synthetic bytes; not an approval gate.

    The source identity is operator-asserted, not independently certified.
    """
    if type(pdf_bytes) is not bytes or not (100 <= len(pdf_bytes) <= 3_000_000):
        raise EvidenceContractError("invalid_pdf_byte_stream")
    if (type(expected_sha) is not str
            or hashlib.sha256(pdf_bytes).hexdigest() != expected_sha):
        raise EvidenceContractError("pinned_source_pdf_sha_mismatch")
    if (type(expected_page_count) is not int
            or not 1 <= expected_page_count <= 30):
        raise EvidenceContractError("invalid_pinned_page_count")
    if (type(suite) is not dict or
            suite.get("source_id") != expected_source_id):
        raise EvidenceContractError("pinned_source_id_mismatch")
    report = verify_silver_candidate_suite(pdf_bytes, suite)
    if report["native_text_page_count"] != expected_page_count:
        raise EvidenceContractError("pinned_pdf_page_count_mismatch")
    return report


def run_app149_readonly_pilot(pdf_bytes):
    """Pin APP149's exact Drive-copy bytes; no external I/O or Gold upgrades."""
    report = verify_pinned_silver_profile(
        pdf_bytes, build_app149_candidate_suite(),
        expected_sha=PINNED_PDF_SHA256,
        expected_page_count=PINNED_PHYSICAL_PAGE_COUNT,
        expected_source_id=PINNED_SOURCE_ID,
    )
    if ([row["case_id"] for row in report["cases"]] !=
            list(EXPECTED_CASE_IDS) or report["case_count"] != 5):
        raise EvidenceContractError("pilot_case_inventory_mismatch")
    # Output metadata never changes verifier's literal-only trust boundary.
    return {
        "version": VERSION,
        "status": "APP149_READ_ONLY_SILVER_EVIDENCE_PREVIEW",
        "source_id": PINNED_SOURCE_ID,
        "source_version": PINNED_DOCUMENT_VERSION,
        "expected_original_pdf_sha256": PINNED_PDF_SHA256,
        "source_bytes_match_pinned_drive_copy": True,
        "official_web_pdf_binary_match_verified": False,
        "official_source_verified": False,
        "human_gold_cases_approved": 0,
        "gold_page_verified": None,
        "case_count": report["case_count"],
        "counts": dict(report["counts"]),
        "cases": [dict(row) for row in report["cases"]],
        "verifier_report_sha256": report["report_sha256"],
        "real_embedding_service_called": False,
        "shared_db_access": False,
        "production_access": False,
        "write_authorized": False,
        "artifact_written": False,
        "environment": "staging",
        "notice": (
            "Machine checks confirm literal PDF evidence only, not legal "
            "correctness. Human Gold approval remains pending; official "
            "website raw-byte equivalence was not independently proven."
        ),
    }
