#!/usr/bin/env python3
"""M10B-0: offline-only safety and interface contract audit.

This intentionally audits EXISTING APIs without invoking any writer,
network, Docker, OCR, Vision, or live ingestion subprocess.
"""
import ast
import hashlib
import tempfile
from pathlib import Path

from m10_candidate_intake_v1 import inspect_batch
from route_document_v2 import assess_manifest
from test_m10_candidate_intake_v1 import make
from version_qualification_policy_v1 import (
    CANDIDATE_NEW_VERSION,
    POLICY_BLOCKED,
    evaluate_version_candidate,
    evaluate_version_update,
)
from version_signal_extractor_v1 import compare_version_snapshots


ROOT = Path(__file__).resolve().parent


def read_source(filename):
    return (ROOT / filename).read_text(encoding="utf-8")


def snapshot(*, sha, revision, host="www.bd.gov.hk", content="c", metadata="m"):
    return {
        "authority_code": "BD",
        "document_code": "APP-149",
        "canonical_host": host,
        "issue_date": revision,
        "revision_date": revision,
        "edition": None,
        "document_sha256": sha * 64,
        "normalized_content_fingerprint": content * 64,
        "metadata_fingerprint": metadata * 64,
    }


def evaluate(old, new):
    signals = compare_version_snapshots(
        old, new,
        staging_validation_verified=False,
        deterministic_release=False,
    )
    return signals, evaluate_version_candidate(signals)


def test_m10a_admission_remains_read_only():
    with tempfile.TemporaryDirectory() as dirname:
        root, summary, _files = make(Path(dirname))
        before = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(),
                          p.stat().st_mtime_ns)
                  for p in root.rglob("*") if p.is_file()}
        output = inspect_batch(summary, state_root=root)
        item = output["results"][0]
        assert item["status"] == "READY_FOR_STAGING_VALIDATION"
        assert item["candidate_id"].startswith("BD_PNAP_APP149:")
        assert item["candidate"]["staging_validation_verified"] is False
        assert item["write_authorized"] is False
        assert output["write_authorized"] is False
        assert before == {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                  p.stat().st_mtime_ns)
                          for p in root.rglob("*") if p.is_file()}


def test_no_change_requires_no_workspace():
    with tempfile.TemporaryDirectory() as dirname:
        root, summary, _files = make(Path(dirname), decision="NO_CHANGE")
        before = sorted(str(p) for p in root.rglob("*"))
        output = inspect_batch(summary, state_root=root)
        item = output["results"][0]
        assert item["status"] == "NO_CHANGE"
        assert item["candidate"] is None
        assert item["candidate_id"] is None
        assert sorted(str(p) for p in root.rglob("*")) == before


def test_identity_and_downgrade_policy_contract():
    old = snapshot(sha="a", revision="2025-01", content="b", metadata="c")
    new = snapshot(sha="d", revision="2026-08", content="e", metadata="f")
    signals, result = evaluate(old, new)
    assert result["decision"] == CANDIDATE_NEW_VERSION
    assert signals["staging_validation_verified"] is False
    assert signals["deterministic_release"] is False
    assert evaluate_version_update(signals)["decision"] == POLICY_BLOCKED

    identity_mismatch = dict(new, authority_code="NOT_BD")
    assert evaluate(old, identity_mismatch)[1]["decision"] == POLICY_BLOCKED
    older = dict(new, issue_date="2024-01", revision_date="2024-01")
    assert evaluate(old, older)[1]["decision"] == POLICY_BLOCKED


def test_null_identity_comparison_gap_is_recorded_not_accepted():
    # Deliberately exposes a limitation in a frozen comparator:
    # None == None is True; M10B must enforce required nonblank fields
    # BEFORE invoking it. A policy result alone is not enough.
    old = snapshot(sha="a", revision="2025-01", content="b",
                   metadata="c", host=None)
    new = snapshot(sha="d", revision="2026-08", content="e",
                   metadata="f", host=None)
    signals, _result = evaluate(old, new)
    assert signals["official_host_match"] is True
    assert old["canonical_host"] is None
    assert new["canonical_host"] is None


def test_partial_router_not_equivalent_to_valid_full_document():
    payload = {
        "schema_version": "document-manifest-v2",
        "source": {"filename": "candidate.pdf", "sha256": "a" * 64},
        "document": {"kind": "pdf", "page_count": 3},
        "selection": {"page_numbers": [1]},
        "units": [{
            "unit_type": "page", "page_number": 1,
            "text_chars": 30, "images": [],
            "ocr_candidate": False,
            "vector_metrics": {"meaningful_drawing_item_count": 0},
        }],
    }
    result = assess_manifest(payload, allow_partial=False)
    assert result["document"]["partial_manifest"] is True
    assert result["decision"]["production_decision_valid"] is False
    # Even if the router returns legacy-v1, this is NOT eligible
    # for M10B full-document verification.
    assert result["safety"]["database_write_performed"] is False


def test_m10a_module_has_no_direct_side_effect_calls():
    tree = ast.parse(read_source("m10_candidate_intake_v1.py"))
    blocked = {"urlopen", "run", "Popen", "check_call", "check_output",
               "mkdir", "write_text", "write_bytes", "unlink",
               "replace", "rename", "execute_transaction", "run_rclone"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else "")
            assert name not in blocked, (
                "M10A gained a side-effect entrypoint: " + name
            )


def test_existing_prepare_is_not_offline_safe():
    orchestration = read_source("orchestrate_document_v2.py")
    canary = read_source("run_multimodal_canary_v2.py")
    ingestion = read_source("ingest_manifest_v2.py")
    # These are observed risk signatures, NOT permissions to call.
    # Changes require re-auditing this file and design record.
    assert "read_existing_document(" in orchestration
    assert '"--check-db"' in orchestration
    assert '"--prepare"' in canary
    assert "run_checked(" in canary
    assert "DEFAULT_DB_CONTAINER" in ingestion
    assert "execute_transaction(" in ingestion


def test_existing_vision_has_external_api_egress():
    vision = read_source("augment_vision_v2.py")
    assert "DEEPSEEK_API_KEY" in vision
    assert '"/chat/completions"' in vision
    assert "urllib.request.urlopen(" in vision
    # Never use this adapter implicitly in isolated M10B-1.


def test_current_canonical_and_staging_db_are_not_candidate_namespace():
    text_ingestion = read_source("ingest_canonical_text_staging_v1.py")
    retrieval = read_source("validate_staging_retrieval_v2.py")
    assert 'source_path.startswith("Current/")' in text_ingestion
    assert '"INSERT INTO documents ("' in text_ingestion
    assert "FROM embeddings e" in retrieval
    assert "JOIN documents d" in retrieval
    # Existing shared Staging DB search is not candidate-only search.


def main():
    cases = [
        test_m10a_admission_remains_read_only,
        test_no_change_requires_no_workspace,
        test_identity_and_downgrade_policy_contract,
        test_null_identity_comparison_gap_is_recorded_not_accepted,
        test_partial_router_not_equivalent_to_valid_full_document,
        test_m10a_module_has_no_direct_side_effect_calls,
        test_existing_prepare_is_not_offline_safe,
        test_existing_vision_has_external_api_egress,
        test_current_canonical_and_staging_db_are_not_candidate_namespace,
    ]
    for test in cases:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-0 offline contract audit: PASS")
    print("AUDIT FINDINGS: offline prepare DB read, vision API egress,")
    print("missing-host identity gap and shared-DB coupling REQUIRE M10B-1 gates.")


if __name__ == "__main__":
    main()
