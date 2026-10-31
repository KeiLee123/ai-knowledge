#!/usr/bin/env python3
"""M10B-2I: pinned APP149 read-only generated Silver case pilot.

Only operator-supplied in-memory original PDF bytes. No PDF acquisition,
network, file I/O, model, DB, Gold approval or Production operations.
The generator and its verifier use the same PDF; this is NOT semantic QA.
"""
import hashlib
import json

from m10b2f_offline_silver_evidence_v1 import EvidenceContractError
from m10b2g_app149_readonly_silver_pilot_v1 import (
    PINNED_DOCUMENT_VERSION, PINNED_PDF_SHA256, PINNED_PHYSICAL_PAGE_COUNT,
    PINNED_SOURCE_ID,
)
from m10b2h_offline_silver_generation_v1 import run_offline_silver_generation

VERSION = "m10b2i-app149-readonly-generated-silver-v1"
SUITE_ID = "app149-native-text-generated-silver-v1"
SAMPLE_SEED = "app149-readonly-qa-v1"
MAX_GENERATED_CASES = 10
PER_PAGE_LIMIT = 2
QA_SAMPLE_PERCENT = 10


def run_pinned_generated_profile(
    pdf_bytes, *, source_id, document_version, suite_id, pinned_sha256,
    expected_page_count, max_cases=MAX_GENERATED_CASES,
    max_per_page=PER_PAGE_LIMIT, sample_percent=QA_SAMPLE_PERCENT,
    sample_seed=SAMPLE_SEED,
):
    """Reusable synthetic CI profile, rejects source drift before extraction."""
    if (type(pdf_bytes) is not bytes
            or type(pinned_sha256) is not str
            or hashlib.sha256(pdf_bytes).hexdigest() != pinned_sha256):
        raise EvidenceContractError("pinned_source_pdf_sha_mismatch")
    if (type(expected_page_count) is not int
            or not 1 <= expected_page_count <= 30):
        raise EvidenceContractError("invalid_expected_page_count")

    result = run_offline_silver_generation(
        pdf_bytes, source_id=source_id, document_version=document_version,
        suite_id=suite_id, expected_sha256=pinned_sha256,
        max_cases=max_cases, max_per_page=max_per_page,
        sample_percent=sample_percent, sample_seed=sample_seed,
    )
    if result["native_page_count"] != expected_page_count:
        raise EvidenceContractError("pinned_pdf_page_count_mismatch")
    if (result["source_id"] != source_id
            or result["source_pdf_sha256"] != pinned_sha256
            or result["case_count"] > max_cases):
        raise EvidenceContractError("generated_profile_identity_mismatch")
    return result


def run_app149_readonly_generated_silver(pdf_bytes):
    """M10B-2H profile fixed to the previously byte-matched Drive APP149 copy.

    This function cannot certify official website bytes or legal correctness.
    Counts are workload ROUTING PROXIES, not time savings or QA measurements.
    """
    data = run_pinned_generated_profile(
        pdf_bytes,
        source_id=PINNED_SOURCE_ID,
        document_version=PINNED_DOCUMENT_VERSION,
        suite_id=SUITE_ID,
        pinned_sha256=PINNED_PDF_SHA256,
        expected_page_count=PINNED_PHYSICAL_PAGE_COUNT,
    )
    total = data["case_count"]
    queue = data["review_queue_count"]
    counts = data["verification_counts"]
    if (not 1 <= total <= MAX_GENERATED_CASES
            or queue > total
            or sum(counts.values()) != total
            or data["human_gold_cases_approved"] != 0
            or data["gold_page_verified"] is not None
            or data["official_source_verified"] is not False):
        raise EvidenceContractError("generation_profile_contract_violation")

    output = {
        "version": VERSION,
        "status": "APP149_READ_ONLY_GENERATED_SILVER_PREVIEW",
        "source_id": PINNED_SOURCE_ID,
        "document_version": PINNED_DOCUMENT_VERSION,
        "pinned_drive_copy_sha256": PINNED_PDF_SHA256,
        "source_bytes_match_known_drive_copy": True,
        "native_pdf_page_count": data["native_page_count"],
        "generated_case_count": total,
        "generated_case_type": "POSITIVE_CONTEXT_CLOZE_ONLY",
        "verification_counts": dict(counts),
        "review_queue_count": queue,
        "review_queue": [dict(row) for row in data["review_queue"]],
        "human_review_required_count": data["required_human_review_count"],
        "sampled_qa_count": data["sampled_human_qa_count"],
        "evidence_remediation_count": data["evidence_remediation_count"],
        "not_queued_case_count": total - queue,
        "not_queued_case_fraction": round((total - queue) / total, 4),
        "review_queue_fraction": round(queue / total, 4),
        "review_all_cases_comparator_count": total,
        "review_queue_operational_proxy_only": True,
        "review_time_saved_measured": False,
        "question_usefulness_human_reviewed": False,
        "sample_statistics_validated": False,
        "sample_seed": data["sample_seed"],
        "sample_percent": data["sample_percent"],
        "generator_report_sha256": data["report_sha256"],
        "official_website_raw_pdf_byte_match_verified": False,
        "official_source_verified": False,
        "independent_answer_correctness_verified": False,
        "human_review_completed_count": 0,
        "human_gold_cases_approved": 0,
        "gold_page_verified": None,
        "real_embedding_service_called": False,
        "semantic_verified": False,
        "shared_db_access": False,
        "production_access": False,
        "write_authorized": False,
        "artifact_written": False,
        "environment": "staging",
        "notice": (
            "The cloze cases are mechanically self-grounded, NOT independent "
            "natural-language QA or human Official Gold. Queue fraction is "
            "an unvalidated routing proxy, NOT measured time savings. "
            "Human QA and official web-vs-Drive byte equivalence remain open."
        ),
    }
    checksum_input = json.dumps(
        output, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    output["report_sha256"] = hashlib.sha256(
        checksum_input.encode("utf-8")).hexdigest()
    return output
