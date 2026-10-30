#!/usr/bin/env python3
"""M10B-2B-0: pure OFFLINE semantic retrieval contract (synthetic only).

Vectors are supplied as deterministic test data. No HTTP, local embedding
service, database, file IO, network, subprocess, model inference or writes.
Passing synthetic ranking never establishes official Gold, answer correctness
or real-model semantic capability.
"""
import hashlib
import json
import math

from m10_candidate_intake_v1 import valid_sha
from m10b2a_candidate_lexical_v1 import verify_chunks, compact_text
from m10b2a_gold_cases_v1 import validate_suite

CONTRACT_VERSION = "m10b2b0-offline-semantic-v1"
EXPECTED_MODEL_CONTRACT = {
    "mode": "offline-synthetic",
    "model_id": "synthetic-orthogonal-vectors-v1",
    "model_revision": "fixed-test-fixture-v1",
    "dimension": 384,
    "adapter_version": "offline-fixture-only-v1",
}
DIM = 384
MAX_CHUNKS = 5000


class SemanticContractError(ValueError):
    pass


def require(condition, why):
    if not condition:
        raise SemanticContractError(why)


def sha_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def validate_vector(vector, *, expected_dim=DIM):
    require(type(vector) in (list, tuple) and len(vector) == expected_dim,
            "dimension_mismatch")
    require(all(type(v) in (int, float) and math.isfinite(v) for v in vector),
            "invalid_vector_numeric")
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    require(norm > 0 and math.isfinite(norm), "zero_or_invalid_norm")
    return tuple(float(v) / norm for v in vector)


def normalize_corpus(manifest, chunks, vectors, *, candidate_sha):
    require(valid_sha(candidate_sha), "invalid_candidate_sha")
    require(manifest.get("source", {}).get("sha256") == candidate_sha,
            "manifest_candidate_mismatch")
    require(manifest.get("document", {}).get("kind") == "pdf",
            "not_pdf_manifest")
    try:
        verify_chunks(manifest, chunks, candidate_sha)
    except (ValueError, KeyError, TypeError) as exc:
        raise SemanticContractError("untrusted_page_provenance") from exc
    require(0 < len(chunks) <= MAX_CHUNKS, "invalid_chunk_count")
    require(type(vectors) is dict
            and set(vectors) == {str(x["chunk_index"]) for x in chunks},
            "wrong_candidate_vector_namespace")
    result = []
    for chunk in chunks:
        idx = chunk["chunk_index"]
        result.append({
            "chunk_id": idx,
            "page_number": chunk["page_start"],
            "evidence_origin": "native_text",
            "content_sha256": sha_text(chunk["content"]),
            "vector": validate_vector(vectors[str(idx)]),
        })
    return result


def rank_cosine(corpus, query_vector, *, top_k):
    require(type(top_k) is int and 1 <= top_k <= 10, "invalid_top_k")
    q = validate_vector(query_vector)
    hits = []
    for chunk in corpus:
        # Inputs already unit-normalized; cosine = dot product.
        score = sum(a * b for a, b in zip(q, chunk["vector"]))
        require(math.isfinite(score), "nonfinite_cosine")
        hits.append({
            "chunk_id": chunk["chunk_id"],
            "page_number": chunk["page_number"],
            "evidence_origin": chunk["evidence_origin"],
            "content_sha256": chunk["content_sha256"],
            "cosine_similarity": round(max(-1.0, min(1.0, score)), 8),
        })
    hits.sort(key=lambda x: (-x["cosine_similarity"], x["page_number"],
                             x["chunk_id"]))
    return hits[:top_k]


def evaluate_offline_synthetic(manifest, chunks, suite, *, source_id,
                               candidate_sha, fixture_id, vectors,
                               predictions, model_contract,
                               top_k=3):
    """Evaluation with caller-supplied predictions, never Gold-derived labels.

    predictions: case_id -> {"query_vector": 384 finite numbers,
                             "abstain": explicit bool}
    The query vector/abstain are synthetic fixture inputs, not real-model
    predictions. This function never derives them from gold expected pages.
    """
    require(type(model_contract) is dict
            and model_contract == EXPECTED_MODEL_CONTRACT,
            "synthetic_model_contract_required")
    require(type(top_k) is int and 1 <= top_k <= 10, "invalid_top_k")
    try:
        cases = validate_suite(suite, source_id=source_id,
                               fixture_id=fixture_id)
    except ValueError as exc:
        raise SemanticContractError("untrusted_gold_suite") from exc
    require(type(predictions) is dict and
            set(predictions) == {c["case_id"] for c in cases},
            "missing_or_extra_query_predictions")
    corpus = normalize_corpus(manifest, chunks, vectors,
                              candidate_sha=candidate_sha)
    page_count = manifest["document"]["page_count"]
    chunks_by_id = {c["chunk_index"]: c for c in chunks}
    rows = []
    positive_reciprocal_ranks = []
    positive_hit1 = 0
    positive_hit3 = 0
    negative_false_positives = 0
    for case in cases:
        case_id = case["case_id"]
        prediction = predictions[case_id]
        require(type(prediction) is dict
                and set(prediction) == {"query_vector", "abstain"}
                and type(prediction["abstain"]) is bool,
                "invalid_prediction_contract")
        require(all(p <= page_count for p in case["expected_page_numbers"]),
                "expected_gold_page_out_of_range")
        ranked = rank_cosine(corpus, prediction["query_vector"], top_k=top_k)
        abstain = prediction["abstain"]
        if abstain:
            presented = []
        else:
            presented = ranked
        if case["should_find"]:
            correct_positions = [
                n for n, hit in enumerate(presented, start=1)
                if hit["page_number"] in case["expected_page_numbers"]
                and compact_text(case["expected_excerpt"]) in compact_text(
                    chunks_by_id[hit["chunk_id"]]["content"])
                and all(compact_text(term) in compact_text(
                    chunks_by_id[hit["chunk_id"]]["content"])
                    for term in case["expected_terms"])
            ]
            rank = min(correct_positions) if correct_positions else None
            passed = rank is not None
            positive_reciprocal_ranks.append(
                1.0 / rank if rank is not None else 0.0)
            positive_hit1 += int(rank is not None and rank <= 1)
            positive_hit3 += int(rank is not None and rank <= 3)
            reason = "synthetic_expected_page_retrieved" if passed else (
                "synthetic_gold_page_not_retrieved_or_abstained")
        else:
            rank = None
            passed = abstain
            negative_false_positives += int(not abstain)
            reason = ("synthetic_explicit_abstention" if passed
                      else "negative_answerability_failure")
        rows.append({
            "case_id": case_id,
            "case_type": "positive" if case["should_find"] else "negative",
            "status": "PASS" if passed else "FAIL",
            "reason": reason,
            "retrieved_pages": [hit["page_number"] for hit in presented],
            "retrieved_hits": presented,
            "expected_synthetic_pages": case["expected_page_numbers"],
            "synthetic_expected_page_rank": rank,
            "synthetic_abstain_input": abstain,
            "official_gold_page_verified": None,
        })
    npos = len(positive_reciprocal_ranks)
    require(npos > 0, "no_positive_synthetic_cases")
    passed = all(row["status"] == "PASS" for row in rows)
    return {
        "version": CONTRACT_VERSION,
        "status": ("OFFLINE_SYNTHETIC_SEMANTIC_PASSED" if passed
                   else "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"),
        "mode": "offline-synthetic",
        "source_id": source_id,
        "candidate_id": source_id + ":" + candidate_sha,
        "fixture_id": fixture_id,
        "suite_id": suite["suite_id"],
        "model_contract": dict(model_contract),
        "chunk_count": len(corpus),
        "top_k": top_k,
        "metrics": {
            "positive_case_count": npos,
            "synthetic_hit_at_1": round(positive_hit1 / npos, 6),
            "synthetic_hit_at_3": round(positive_hit3 / npos, 6),
            "synthetic_mrr": round(
                sum(positive_reciprocal_ranks) / npos, 6),
            "negative_false_positive_count": negative_false_positives,
        },
        "cases": rows,
        "gold_page_verified": None,
        "official_document_verified": False,
        "real_embedding_service_called": False,
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
