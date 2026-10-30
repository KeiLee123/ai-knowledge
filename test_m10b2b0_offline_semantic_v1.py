#!/usr/bin/env python3
"""M10B-2B-0 offline-only synthetic semantic contract regression."""
import copy
import hashlib
import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

from build_multimodal_chunks_v2 import build_chunks
from extract_document_v2 import build_manifest
from m10b2a_candidate_lexical_v1 import rank_lexical
from m10b2a_gold_cases_v1 import read_gold_suite
from m10b2b0_offline_semantic_v1 import (
    EXPECTED_MODEL_CONTRACT, SemanticContractError,
    evaluate_offline_synthetic, rank_cosine, validate_vector,
)
from test_m10b2a_gold_cases_v1 import (
    FIXTURE, SOURCE, SUITE_FILE, make_pdf,
)

PREDICTION_FILE = (
    Path(__file__).resolve().parent /
    "tests/fixtures/m10b2b0_offline_vectors_v1.json"
)


def one_hot(axis):
    vec = [0.0] * 384
    vec[axis] = 1.0
    return vec


def materials(directory):
    pdf = directory / "synthetic_two_page_not_official.pdf"
    make_pdf(pdf)
    manifest = build_manifest(pdf)
    chunks = build_chunks(manifest, target_chars=1800, overlap_chars=0)
    suite = read_gold_suite(SUITE_FILE)
    p1 = copy.deepcopy(suite["cases"][0])
    p1.update({
        "case_id": "SYN_GOLD_P1_PARAPHRASE",
        "query": "Who supervises small building jobs?",
    })
    hard_negative = copy.deepcopy(suite["cases"][2])
    hard_negative.update({
        "case_id": "SYN_GOLD_NEGATIVE_NEAR_MISS",
        "query": "authorized signatory jellyfish",
    })
    suite["cases"].extend([p1, hard_negative])
    fixture = json.loads(PREDICTION_FILE.read_text(encoding="utf-8"))
    assert fixture["scope"] == "synthetic_only"
    assert fixture["model_contract"] == EXPECTED_MODEL_CONTRACT
    assert fixture["dimension"] == 384
    vectors = {
        str(c["chunk_index"]): one_hot(
            fixture["page_axes"][str(c["page_start"])])
        for c in chunks
    }
    predictions = {
        case_id: {
            "query_vector": one_hot(settings["axis"]),
            "abstain": settings["abstain"],
        }
        for case_id, settings in fixture["predictions"].items()
    }
    assert set(predictions) == {c["case_id"] for c in suite["cases"]}
    return (pdf, manifest, chunks, suite,
            manifest["source"]["sha256"], vectors, predictions)


def evaluate(data, *, suite=None, vectors=None, predictions=None,
             model_contract=None, source_id=SOURCE, candidate_sha=None,
             fixture_id=FIXTURE, top_k=3):
    _, manifest, chunks, gold, sha, vecs, preds = data
    return evaluate_offline_synthetic(
        manifest, chunks, gold if suite is None else suite,
        source_id=source_id,
        candidate_sha=sha if candidate_sha is None else candidate_sha,
        fixture_id=fixture_id, vectors=vecs if vectors is None else vectors,
        predictions=preds if predictions is None else predictions,
        model_contract=(EXPECTED_MODEL_CONTRACT if model_contract is None
                        else model_contract),
        top_k=top_k,
    )


def rejects(fn):
    try:
        fn()
    except SemanticContractError:
        return
    raise AssertionError("Expected fail-closed semantic contract")


def test_positive_paraphrase_and_negative_abstain_offline():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        pdf = data[0]
        before = (hashlib.sha256(pdf.read_bytes()).hexdigest(),
                  pdf.stat().st_mtime_ns)
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("HTTP forbidden")), \
             patch("socket.create_connection",
                   side_effect=AssertionError("network forbidden")), \
             patch("subprocess.run",
                   side_effect=AssertionError("subprocess forbidden")):
            output = evaluate(data)
        assert output["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_PASSED", output
        assert len(output["cases"]) == 5, output
        assert all(c["status"] == "PASS" for c in output["cases"])
        assert output["metrics"]["synthetic_hit_at_1"] == 1.0
        assert output["metrics"]["synthetic_mrr"] == 1.0
        assert output["metrics"]["negative_false_positive_count"] == 0
        assert output["cases"][3]["retrieved_pages"][0] == 1
        assert output["cases"][4]["retrieved_pages"] == []
        assert output["gold_page_verified"] is None
        assert output["semantic_verified"] is False
        assert output["real_embedding_service_called"] is False
        assert output["official_document_verified"] is False
        assert output["shared_db_access"] is False
        assert output["production_write"] is False
        assert output["artifact_written"] is False
        assert evaluate(data) == output
        assert before == (hashlib.sha256(pdf.read_bytes()).hexdigest(),
                          pdf.stat().st_mtime_ns)


def test_paraphrase_has_no_literal_lexical_overlap():
    with tempfile.TemporaryDirectory() as root:
        _, manifest, chunks, suite, sha, vectors, predictions = materials(Path(root))
        para = next(c for c in suite["cases"]
                    if c["case_id"] == "SYN_GOLD_P1_PARAPHRASE")
        assert rank_lexical(chunks, para["query"], 3) == []


def test_negative_must_have_explicit_abstention_decision():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        predictions = copy.deepcopy(data[6])
        predictions["SYN_GOLD_NEGATIVE_NEAR_MISS"]["abstain"] = False
        result = evaluate(data, predictions=predictions)
        assert result["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
        assert result["metrics"]["negative_false_positive_count"] == 1
        negative = result["cases"][4]
        assert negative["status"] == "FAIL"
        assert negative["reason"] == "negative_answerability_failure"
        assert negative["retrieved_pages"]
        assert result["gold_page_verified"] is None


def test_wrong_gold_page_and_excerpt_fail():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        wrong = copy.deepcopy(data[3])
        wrong["cases"][0]["expected_page_numbers"] = [2]
        output = evaluate(data, suite=wrong)
        assert output["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
        assert output["cases"][0]["status"] == "FAIL"
        wrong = copy.deepcopy(data[3])
        wrong["cases"][0]["expected_excerpt"] = "unwritten fabricated phrase"
        output = evaluate(data, suite=wrong)
        assert output["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"


def test_wrong_page_prediction_is_not_self_certified():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        predictions = copy.deepcopy(data[6])
        predictions["SYN_GOLD_P1_APPOINTMENT"]["query_vector"] = one_hot(1)
        output = evaluate(data, predictions=predictions, top_k=1)
        assert output["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
        assert output["cases"][0]["status"] == "FAIL"
        assert output["cases"][0]["retrieved_pages"] == [2]


def test_model_identity_revision_dimension_and_mode_rejected():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        for key, value in [
            ("model_id", "multilingual-e5-small"),
            ("mode", "live-loopback"),
            ("model_revision", "unknown"),
            ("dimension", 768),
            ("adapter_version", "external-http"),
        ]:
            invalid = dict(EXPECTED_MODEL_CONTRACT, **{key: value})
            rejects(lambda: evaluate(data, model_contract=invalid))


def test_vector_validation_rejects_bad_numeric_and_norm():
    for vector in (
        [0.0] * 384,
        [0.0] * 383,
        [float("nan")] + [0.0] * 383,
        [float("inf")] + [0.0] * 383,
        [True] + [0.0] * 383,
        "fake-vector",
        [1e308] * 384,
    ):
        rejects(lambda v=vector: validate_vector(v))
    normalized = validate_vector([3.0, 4.0] + [0.0] * 382)
    assert abs(math.sqrt(sum(v*v for v in normalized)) - 1.0) < 1e-9


def test_vector_namespace_cross_candidate_and_page_tamper():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        missing = copy.deepcopy(data[5])
        missing.pop(next(iter(missing)))
        rejects(lambda: evaluate(data, vectors=missing))
        extra = copy.deepcopy(data[5])
        extra["99999"] = one_hot(0)
        rejects(lambda: evaluate(data, vectors=extra))
        rejects(lambda: evaluate(data, candidate_sha="a" * 64))
        rejects(lambda: evaluate(data, source_id="BD_PNAP_APP145"))
        rejects(lambda: evaluate(data, fixture_id="not-the-same-fixture"))
        wrong_content = copy.deepcopy(data[2])
        wrong_content[0]["content"] = "unrelated injected text"
        other = list(data)
        other[2] = wrong_content
        rejects(lambda: evaluate(tuple(other)))


def test_gold_suite_cannot_claim_official_review():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        for key, value in (
            ("scope", "official"),
            ("review_status", "human_verified"),
            ("gold_provenance", "ai_generated"),
        ):
            forged = copy.deepcopy(data[3])
            forged[key] = value
            rejects(lambda suite=forged: evaluate(data, suite=suite))
        incomplete = copy.deepcopy(data[6])
        incomplete.pop("SYN_GOLD_NEGATIVE_NEAR_MISS")
        rejects(lambda: evaluate(data, predictions=incomplete))


def test_abstain_positive_is_failure_not_retrieval_success():
    with tempfile.TemporaryDirectory() as root:
        data = materials(Path(root))
        pred = copy.deepcopy(data[6])
        pred["SYN_GOLD_P2_EVACUATION"]["abstain"] = True
        output = evaluate(data, predictions=pred)
        assert output["status"] == "OFFLINE_SYNTHETIC_SEMANTIC_FAILED"
        assert output["cases"][1]["status"] == "FAIL"


def test_tie_breaker_and_finite_cosines():
    corpus = [
        {"chunk_id": 9, "page_number": 2, "evidence_origin": "native_text",
         "content_sha256": "a"*64, "vector": validate_vector(one_hot(0))},
        {"chunk_id": 1, "page_number": 1, "evidence_origin": "native_text",
         "content_sha256": "b"*64, "vector": validate_vector(one_hot(0))},
    ]
    ranked = rank_cosine(corpus, one_hot(0), top_k=2)
    assert [r["page_number"] for r in ranked] == [1, 2]
    assert ranked[0]["cosine_similarity"] == 1.0
    rejects(lambda: rank_cosine(corpus, one_hot(0), top_k=11))


def main():
    tests = [
        test_positive_paraphrase_and_negative_abstain_offline,
        test_paraphrase_has_no_literal_lexical_overlap,
        test_negative_must_have_explicit_abstention_decision,
        test_wrong_gold_page_and_excerpt_fail,
        test_wrong_page_prediction_is_not_self_certified,
        test_model_identity_revision_dimension_and_mode_rejected,
        test_vector_validation_rejects_bad_numeric_and_norm,
        test_vector_namespace_cross_candidate_and_page_tamper,
        test_gold_suite_cannot_claim_official_review,
        test_abstain_positive_is_failure_not_retrieval_success,
        test_tie_breaker_and_finite_cosines,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2B-0 OFFLINE synthetic semantic contract regression: PASS")


if __name__ == "__main__":
    main()
