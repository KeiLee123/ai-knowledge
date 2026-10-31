#!/usr/bin/env python3
"""M10B-2F: deterministic, read-only *silver* evidence checks on PDF bytes.

No generation, model, network, DB, filesystem, timers, or Gold approval.
A literal quote + page match is not proof of semantic/legal correctness.
"""
import hashlib
import json
import re

import pymupdf

VERSION = "m10b2f-silver-evidence-v1"
SUITE_VERSION = "m10b2f-candidate-suite-v1"
SCOPE = "machine_evidence_candidate_only"
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SUITE_FIELDS = frozenset({
    "version", "scope", "suite_id", "source_id", "document_version",
    "original_pdf_sha256", "cases",
})
CASE_FIELDS = frozenset({
    "case_id", "case_type", "source_id", "original_pdf_sha256",
    "query", "expected_physical_pdf_page", "evidence_quote",
    "context_before", "context_after",
})
CASE_TYPES = frozenset({"POSITIVE", "PARAPHRASE", "NEAR_MISS", "NEGATIVE"})
HIGH_RISK_TERMS = re.compile(
    r"\b(?:must|shall|required?|only|not|never|prohibit(?:ed)?|"
    r"may\s+not|within|days?|weeks?|months?|years?|fees?|"
    r"liability|responsib(?:le|ility)|penalt(?:y|ies)|"
    r"approved?|permit|consent|shall|maximum|minimum)\b|\d",
    re.IGNORECASE,
)
MAX_BYTES = 3_000_000
MAX_PAGES = 30
MAX_CASES = 50


class EvidenceContractError(ValueError):
    """Source integrity or candidate schema violation."""


def require(ok, message):
    if not ok:
        raise EvidenceContractError(message)


def safe_id(s):
    return type(s) is str and SAFE_ID.fullmatch(s) is not None


def safe_text(s, min_len, max_len):
    return (type(s) is str and min_len <= len(s) <= max_len
            and not any(ord(c) < 32 and c not in "\t\n\r" for c in s))


def normalize(s):
    # Whitespace folding ONLY; do not silently alter digits, negations or
    # Unicode lookalikes (which may differ in legal text).
    return " ".join(s.split())


def validate_suite(suite, sha):
    require(type(suite) is dict and set(suite) == SUITE_FIELDS,
            "unexpected_candidate_suite_schema")
    require(suite["version"] == SUITE_VERSION
            and suite["scope"] == SCOPE, "not_silver_candidate_suite")
    require(safe_id(suite["suite_id"]) and safe_id(suite["source_id"])
            and safe_id(suite["document_version"]), "unsafe_source_identity")
    declared = suite["original_pdf_sha256"]
    require(type(declared) is str and SHA256.fullmatch(declared)
            and declared == sha, "source_pdf_sha_mismatch")
    cases = suite["cases"]
    require(type(cases) is list and 1 <= len(cases) <= MAX_CASES,
            "invalid_case_count")
    ids = set()
    for case in cases:
        require(type(case) is dict and set(case) == CASE_FIELDS,
                "unexpected_candidate_case_schema")
        cid = case["case_id"]
        require(safe_id(cid) and cid not in ids, "duplicate_or_unsafe_case_id")
        ids.add(cid)
        require(case["source_id"] == suite["source_id"]
                and case["original_pdf_sha256"] == declared,
                "cross_source_or_pdf_case")
        require(case["case_type"] in CASE_TYPES, "invalid_case_type")
        require(safe_text(case["query"], 5, 250), "unsafe_query")
        if case["case_type"] == "NEGATIVE":
            require(case["expected_physical_pdf_page"] is None
                    and case["evidence_quote"] is None
                    and case["context_before"] is None
                    and case["context_after"] is None,
                    "negative_claims_a_page_or_quote")
        else:
            pg = case["expected_physical_pdf_page"]
            require(type(pg) is int and 1 <= pg <= MAX_PAGES,
                    "invalid_physical_page_number")
            require(safe_text(case["evidence_quote"], 15, 400)
                    and safe_text(case["context_before"], 8, 150)
                    and safe_text(case["context_after"], 8, 150),
                    "insufficient_exact_quote_and_context")
            for field in ("evidence_quote", "context_before", "context_after"):
                require("|" not in case[field], "unsafe_evidence_markup")


def _extract_native_pages(pdf_bytes):
    """Only inspect the supplied in-memory bytes; extraction has no remote IO."""
    require(type(pdf_bytes) is bytes
            and 100 <= len(pdf_bytes) <= MAX_BYTES
            and pdf_bytes.startswith(b"%PDF-"),
            "invalid_or_oversized_pdf_bytes")
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            require(not doc.needs_pass and 1 <= doc.page_count <= MAX_PAGES,
                    "encrypted_or_invalid_page_count")
            pages = []
            for page in doc:
                # Scanned/image-only pages are not independently verifiable
                # by this native text rule and must not be auto-qualified.
                pages.append(normalize(page.get_text("text", sort=False)))
            return pages
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise EvidenceContractError("pdf_native_text_extraction_failed") from exc


def verify_silver_candidate_suite(pdf_bytes, suite):
    """Return ONLY case IDs, pass/fail reasons, flags and fingerprints.

    Output contains NO queries, excerpts, page text or PDF bytes. This
    module cannot produce HUMAN_REVIEWED or HUMAN_APPROVED_GOLD.
    """
    require(type(pdf_bytes) is bytes, "pdf_not_bytes")
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    validate_suite(suite, sha)
    pages = _extract_native_pages(pdf_bytes)

    rows = []
    for case in suite["cases"]:
        kind, cid = case["case_type"], case["case_id"]
        if kind == "NEGATIVE":
            status, reason, match = (
                "HUMAN_REVIEW_REQUIRED", "NEGATIVE_ABSENCE_NOT_PROVABLE",
                False,
            )
        else:
            n = case["expected_physical_pdf_page"] - 1
            if n >= len(pages) or not pages[n]:
                status, reason, match = (
                    "REJECTED_EVIDENCE_MISMATCH",
                    "PAGE_MISSING_OR_NO_NATIVE_TEXT", False,
                )
            else:
                quote = normalize(case["evidence_quote"])
                joined = normalize(
                    case["context_before"] + " " + case["evidence_quote"]
                    + " " + case["context_after"]
                )
                # PDF extraction may insert line wraps; spaces folded only.
                # For a machine-pass the quote must be unique in whole PDF
                # and flanked by the claimed exact surrounding words.
                qcount = sum(p.count(quote) for p in pages)
                match = qcount == 1 and joined in pages[n]
                if not match:
                    status, reason = (
                        "REJECTED_EVIDENCE_MISMATCH",
                        "QUOTE_PAGE_CONTEXT_MISSING_OR_AMBIGUOUS",
                    )
                elif kind != "POSITIVE":
                    status, reason = (
                        "HUMAN_REVIEW_REQUIRED",
                        "NON_LITERAL_QUERY_SEMANTICS_NEED_REVIEW",
                    )
                elif HIGH_RISK_TERMS.search(
                    case["evidence_quote"] + " " + case["query"]
                ):
                    status, reason = (
                        "HUMAN_REVIEW_REQUIRED",
                        "HIGH_IMPACT_WORDING_NEEDS_REVIEW",
                    )
                else:
                    status, reason = (
                        "MACHINE_EVIDENCE_CHECKED",
                        "EXACT_UNIQUE_PAGE_QUOTE_AND_CONTEXT",
                    )
        rows.append({
            "case_id": cid,
            "case_type": kind,
            "proposed_physical_pdf_page": (
                case["expected_physical_pdf_page"]),
            "native_text_evidence_matched": match,
            "status": status,
            "reason": reason,
            "human_reviewed": False,
            "official_gold_approved": False,
        })
    counts = {
        key: sum(r["status"] == key for r in rows)
        for key in (
            "MACHINE_EVIDENCE_CHECKED",
            "HUMAN_REVIEW_REQUIRED",
            "REJECTED_EVIDENCE_MISMATCH",
        )
    }
    result = {
        "version": VERSION,
        "scope": SCOPE,
        "suite_id": suite["suite_id"],
        "source_id": suite["source_id"],
        "document_version": suite["document_version"],
        "pdf_sha256": sha,
        "native_text_page_count": len(pages),
        "case_count": len(rows),
        "counts": counts,
        "cases": rows,
        "source_bytes_integrity_checked": True,
        "official_source_verified": False,
        "official_document_verified": False,
        "gold_page_verified": None,
        "real_embedding_service_called": False,
        "semantic_verified": False,
        "answer_verified": False,
        "production_access": False,
        "production_write": False,
        "shared_db_access": False,
        "write_authorized": False,
        "artifact_written": False,
        "environment": "staging",
        "notice": (
            "MACHINE_EVIDENCE_CHECKED is a literal native-text PDF "
            "quote/page/context check only. Not verified relevance, "
            "legal meaning, an independent review or Official Gold."
        ),
    }
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    result["report_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    return result
