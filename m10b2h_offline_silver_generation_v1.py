#!/usr/bin/env python3
"""M10B-2H: offline passage-cloze Silver candidate generation and review queue.

This is intentionally RULE-BASED, not an AI model and not Official Gold.
Candidate text is extracted from the SAME PDF used to verify it; therefore
a mechanical evidence match is not an independent correctness benchmark.
No filesystem, network, subprocess, database, model or Production access.
"""
import hashlib
import json

from m10b2f_offline_silver_evidence_v1 import (
    EvidenceContractError, MAX_BYTES, MAX_CASES, SCOPE, SUITE_VERSION,
    _extract_native_pages, safe_id, verify_silver_candidate_suite,
)

VERSION = "m10b2h-offline-silver-generator-v1"
METHOD = "deterministic_native_text_context_cloze"
REPORT_SCOPE = "generated_machine_checked_silver_not_gold"
DEFAULT_SAMPLE_PERCENT = 10


def _guard(pdf_bytes, source_id, document_version, suite_id,
           expected_sha256, max_cases, max_per_page, sample_percent, seed):
    if (type(pdf_bytes) is not bytes
            or not 100 <= len(pdf_bytes) <= MAX_BYTES
            or not pdf_bytes.startswith(b"%PDF-")):
        raise EvidenceContractError("invalid_or_oversized_pdf_bytes")
    if (type(expected_sha256) is not str
            or len(expected_sha256) != 64
            or not all(ch in "0123456789abcdef" for ch in expected_sha256)
            or hashlib.sha256(pdf_bytes).hexdigest() != expected_sha256):
        raise EvidenceContractError("pinned_pdf_sha_mismatch")
    if not (safe_id(source_id) and safe_id(document_version)
            and safe_id(suite_id) and safe_id(seed)):
        raise EvidenceContractError("unsafe_generator_identity")
    if (type(max_cases) is not int or not 1 <= max_cases <= MAX_CASES
            or type(max_per_page) is not int or not 1 <= max_per_page <= 3):
        raise EvidenceContractError("invalid_generation_budget")
    if type(sample_percent) is not int or not 0 <= sample_percent <= 20:
        raise EvidenceContractError("invalid_sampling_percentage")


def build_generated_silver_suite(
    pdf_bytes, *, source_id, document_version, suite_id,
    expected_sha256, max_cases=15, max_per_page=2,
):
    """Return an EPHEMERAL exact M10B-2F candidate suite.

    WARNING: contains original source fragments. Do not print, save, upload
    or treat it as ground-truth without independent human approval.
    """
    _guard(pdf_bytes, source_id, document_version, suite_id,
           expected_sha256, max_cases, max_per_page,
           DEFAULT_SAMPLE_PERCENT, "fixed-seed")
    pages = _extract_native_pages(pdf_bytes)
    cases = []
    for page_no, page in enumerate(pages, start=1):
        words = page.split()
        produced = 0
        # Six words of context either side, eight words of quote.
        # Leave a generous margin to avoid picking up page headers/footers.
        for start in range(8, len(words) - 13, 9):
            before = " ".join(words[start - 6:start])
            quote = " ".join(words[start:start + 8])
            after = " ".join(words[start + 8:start + 14])
            query = "What wording follows this passage: " + before
            if (not 20 <= len(quote) <= 250
                    or not 8 <= len(before) <= 150
                    or not 8 <= len(after) <= 150
                    or not 5 <= len(query) <= 250
                    or any("|" in x for x in (before, quote, after))
                    or sum(p.count(quote) for p in pages) != 1):
                continue
            cid = "GEN_P%03d_C%02d" % (page_no, produced + 1)
            cases.append({
                "case_id": cid,
                "case_type": "POSITIVE",
                "source_id": source_id,
                "original_pdf_sha256": expected_sha256,
                "query": query,
                "expected_physical_pdf_page": page_no,
                "evidence_quote": quote,
                "context_before": before,
                "context_after": after,
            })
            produced += 1
            if produced >= max_per_page or len(cases) >= max_cases:
                break
        if len(cases) >= max_cases:
            break
    if not cases:
        raise EvidenceContractError("no_unique_native_text_candidates")
    return {
        "version": SUITE_VERSION,
        "scope": SCOPE,
        "suite_id": suite_id,
        "source_id": source_id,
        "document_version": document_version,
        "original_pdf_sha256": expected_sha256,
        "cases": cases,
    }


def _ranked_sample(cases, seed, percent):
    """Deterministic sample selection for workflow QA, NOT statistical proof."""
    if percent == 0 or not cases:
        return []
    count = max(1, (len(cases) * percent + 99) // 100)
    scored = sorted(
        cases,
        key=lambda x: (
            hashlib.sha256((seed + "|" + x["case_id"]).encode("ascii")
                           ).hexdigest(),
            x["case_id"],
        ),
    )
    return sorted(x["case_id"] for x in scored[:count])


def run_offline_silver_generation(
    pdf_bytes, *, source_id, document_version, suite_id,
    expected_sha256, max_cases=15, max_per_page=2,
    sample_percent=DEFAULT_SAMPLE_PERCENT, sample_seed="audit-v1",
):
    """Redacted report, review queue and deterministic QA sample; no raw text."""
    _guard(pdf_bytes, source_id, document_version, suite_id,
           expected_sha256, max_cases, max_per_page,
           sample_percent, sample_seed)
    suite = build_generated_silver_suite(
        pdf_bytes, source_id=source_id, document_version=document_version,
        suite_id=suite_id, expected_sha256=expected_sha256,
        max_cases=max_cases, max_per_page=max_per_page,
    )
    verification = verify_silver_candidate_suite(pdf_bytes, suite)
    machine = [r for r in verification["cases"]
               if r["status"] == "MACHINE_EVIDENCE_CHECKED"]
    sampled = set(_ranked_sample(machine, sample_seed, sample_percent))
    queue = []
    for row in verification["cases"]:
        status = row["status"]
        if status == "HUMAN_REVIEW_REQUIRED":
            queue.append({
                "case_id": row["case_id"],
                "route": "REQUIRED_HUMAN_REVIEW",
                "reason": row["reason"],
                "priority": 1,
            })
        elif status == "REJECTED_EVIDENCE_MISMATCH":
            queue.append({
                "case_id": row["case_id"],
                "route": "EVIDENCE_REMEDIATION",
                "reason": row["reason"],
                "priority": 0,
            })
        elif row["case_id"] in sampled:
            queue.append({
                "case_id": row["case_id"],
                "route": "SAMPLED_HUMAN_QA",
                "reason": "DETERMINISTIC_MACHINE_CASE_AUDIT_SAMPLE",
                "priority": 2,
            })
    queue.sort(key=lambda x: (x["priority"], x["case_id"]))
    result = {
        "version": VERSION,
        "scope": REPORT_SCOPE,
        "generation_method": METHOD,
        "source_id": source_id,
        "document_version": document_version,
        "source_pdf_sha256": expected_sha256,
        "suite_id": suite_id,
        "case_count": verification["case_count"],
        "generated_case_type": "POSITIVE_CONTEXT_CLOZE_ONLY",
        "verifier_report_sha256": verification["report_sha256"],
        "verification_counts": dict(verification["counts"]),
        "review_queue": queue,
        "review_queue_count": len(queue),
        "required_human_review_count": sum(
            x["route"] == "REQUIRED_HUMAN_REVIEW" for x in queue),
        "evidence_remediation_count": sum(
            x["route"] == "EVIDENCE_REMEDIATION" for x in queue),
        "sampled_human_qa_count": len(sampled),
        "sample_percent": sample_percent,
        "sample_seed": sample_seed,
        "sample_statistics_validated": False,
        "native_page_count": verification["native_text_page_count"],
        "generated_from_same_pdf_as_evidence": True,
        "independent_answer_correctness_verified": False,
        "official_source_verified": False,
        "gold_page_verified": None,
        "human_gold_cases_approved": 0,
        "human_reviewed": False,
        "real_embedding_service_called": False,
        "semantic_verified": False,
        "shared_db_access": False,
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
        "artifact_written": False,
        "environment": "staging",
        "notice": (
            "Only deterministic context-cloze questions generated from source "
            "text. Machine checks are self-grounded and NOT independent "
            "legal/semantic QA, natural-query accuracy or Official Gold. "
            "Queue selections do not mean human reviews took place."
        ),
    }
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":"))
    result["report_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")).hexdigest()
    return result
