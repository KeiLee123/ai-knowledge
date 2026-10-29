#!/usr/bin/env python3
"""M10B-2A Gold Case contract (synthetic-only v0.1).

This pure evaluator checks independently authored expected pages/excerpts
against candidate-only lexical search results. It never labels an official
document's page as independently reviewed. No DB, network, or writes.
"""
import json
import re
from pathlib import Path

from m10_candidate_intake_v1 import valid_sha
from m10b2a_candidate_lexical_v1 import (
    compact_text, rank_lexical, verify_chunks, words,
)

CONTRACT_VERSION = "m10b2a-gold-contract-v1"
SUITE_SCHEMA = "m10b2a-gold-suite-v1"
FIXTURE_PROVENANCE = "synthetic_authored_independently"
ALLOWED_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GoldContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise GoldContractError(message)


def read_gold_suite(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "unsafe_gold_suite_path")
    require(path.stat().st_size <= 100_000, "gold_suite_too_large")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_suite(suite, *, source_id, fixture_id):
    require(isinstance(suite, dict), "suite_not_object")
    require(suite.get("schema_version") == SUITE_SCHEMA, "wrong_suite_schema")
    require(suite.get("scope") == "synthetic", "real_gold_review_not_implemented")
    require(suite.get("review_status") == "synthetic_only", "not_synthetic_only")
    require(suite.get("gold_provenance") == FIXTURE_PROVENANCE,
            "missing_independent_fixture_provenance")
    require(isinstance(source_id, str) and ALLOWED_SOURCE_ID.fullmatch(source_id),
            "unsafe_source_id")
    require(suite.get("source_id") == source_id, "suite_wrong_source")
    require(isinstance(fixture_id, str) and fixture_id and len(fixture_id) <= 100,
            "invalid_fixture_id")
    require(suite.get("fixture_id") == fixture_id, "wrong_fixture_id")
    require(isinstance(suite.get("suite_id"), str) and suite["suite_id"].strip(),
            "missing_suite_id")
    cases = suite.get("cases")
    require(isinstance(cases, list) and 1 <= len(cases) <= 50,
            "no_or_too_many_gold_cases")
    seen = set()
    for case in cases:
        require(isinstance(case, dict), "case_not_object")
        case_id = case.get("case_id")
        require(isinstance(case_id, str)
                and ALLOWED_SOURCE_ID.fullmatch(case_id)
                and case_id not in seen, "invalid_or_duplicate_case_id")
        seen.add(case_id)
        require(case.get("source_id") == source_id, "case_wrong_source")
        require(case.get("fixture_id") == fixture_id, "case_wrong_fixture")
        require(case.get("review_status") == "synthetic_only",
                "case_not_synthetic_only")
        require(case.get("gold_provenance") == FIXTURE_PROVENANCE,
                "case_missing_independent_provenance")
        query = case.get("query")
        require(isinstance(query, str) and 2 <= len(words(query)) <= 25
                and len(query) <= 300, "invalid_query")
        require(type(case.get("should_find")) is bool, "invalid_label")
        pages = case.get("expected_page_numbers")
        terms = case.get("expected_terms")
        excerpt = case.get("expected_excerpt")
        require(isinstance(pages, list)
                and all(type(p) is int and p >= 1 for p in pages)
                and len(set(pages)) == len(pages), "invalid_gold_pages")
        require(isinstance(terms, list)
                and all(isinstance(t, str) and t.strip() and len(t) <= 70
                        for t in terms), "invalid_case_terms")
        if case["should_find"]:
            require(bool(pages) and bool(terms)
                    and isinstance(excerpt, str) and len(excerpt.strip()) >= 8,
                    "positive_case_missing_gold")
        else:
            require(not pages and not terms and excerpt is None,
                    "negative_case_has_positive_gold")
    return cases


def evaluate_synthetic_suite(manifest, chunks, suite, *, source_id,
                             candidate_sha, fixture_id, top_k=5):
    """Only synthetic fixture assertions. Never emits gold_page_verified=True."""
    require(valid_sha(candidate_sha), "invalid_candidate_sha")
    require(type(top_k) is int and 1 <= top_k <= 10, "invalid_top_k")
    cases = validate_suite(suite, source_id=source_id, fixture_id=fixture_id)
    require(manifest.get("source", {}).get("sha256") == candidate_sha,
            "manifest_wrong_candidate_sha")
    require(manifest.get("document", {}).get("kind") == "pdf",
            "gold_requires_pdf_manifest")
    # Provenance check against each original page, not just self-reported IDs.
    verify_chunks(manifest, chunks, candidate_sha)
    page_count = manifest["document"]["page_count"]
    rows = []
    for case in cases:
        pages = case["expected_page_numbers"]
        require(all(page <= page_count for page in pages),
                "gold_page_outside_document")
        hits = rank_lexical(chunks, case["query"], top_k)
        if case["should_find"]:
            matched = [
                hit for hit in hits
                if hit["page_number"] in pages
                and compact_text(case["expected_excerpt"])
                in compact_text(hit["_full_content"])
                and all(compact_text(term) in
                        compact_text(hit["_full_content"])
                        for term in case["expected_terms"])
            ]
            passed = bool(matched)
            reason = ("expected_page_and_excerpt_found" if passed else
                      "expected_page_excerpt_or_terms_missing")
        else:
            # A naive lexical hit is not an answer: fail negative examples
            # instead of pretending the system knows when to abstain.
            passed = not hits
            reason = ("negative_query_abstained" if passed else
                      "negative_query_false_positive")
        rows.append({
            "case_id": case["case_id"],
            "case_type": ("positive" if case["should_find"] else "negative"),
            "status": ("PASS" if passed else "FAIL"),
            "reason": reason,
            "retrieved_page_numbers": [hit["page_number"] for hit in hits],
            "expected_page_numbers": pages,
            "retrieved_chunk_ids": [hit["chunk_id"] for hit in hits],
            "synthetic_page_match": passed if case["should_find"] else None,
            "gold_page_verified": None,
        })
    passed = all(row["status"] == "PASS" for row in rows)
    return {
        "version": CONTRACT_VERSION,
        "suite_id": suite["suite_id"],
        "source_id": source_id,
        "candidate_id": source_id + ":" + candidate_sha,
        "fixture_id": fixture_id,
        "scope": "synthetic",
        "review_status": "synthetic_only",
        "status": ("SYNTHETIC_GOLD_CASES_PASSED" if passed
                   else "SYNTHETIC_GOLD_CASES_FAILED"),
        "cases": rows,
        "gold_page_verified": None,
        "official_document_verified": False,
        "semantic_verified": False,
        "answer_verified": False,
        "retrieval_verified": False,
        "environment": "staging",
        "production_access": False,
        "production_write": False,
        "write_authorized": False,
        "canonical_promoted": False,
        "accepted_reference_advanced": False,
        "shared_db_access": False,
        "external_vision_api_used": False,
        "artifact_written": False,
    }
