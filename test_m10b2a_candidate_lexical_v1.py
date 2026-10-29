#!/usr/bin/env python3
"""M10B-2A candidate-only lexical validation: synthetic, offline, no DB."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from m10b2a_candidate_lexical_v1 import run, rank_lexical, words
from m10b1_isolated_candidate_v1 import process
from test_m10b1_isolated_candidate_v1 import fixture, save, call
from test_m10_candidate_intake_v1 import SOURCE, make


def context(base):
    root, summary, records, workspace = fixture(base)
    old = call(root, summary, workspace, validate=True)
    assert old["status"] == "PARSE_VERIFIED", old
    return root, summary, records, workspace, old


def validate(root, workspace, old, **kw):
    return run(SOURCE, old["candidate_sha256"], state_root=root,
               workspace_root=workspace, **kw)


def snapshot(root, workspace):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
            for base in (root, workspace) if base.exists()
            for p in base.rglob("*") if p.is_file()}


def test_candidate_only_smoke_and_no_writes():
    with tempfile.TemporaryDirectory() as tmp:
        root, summary, records, workspace, old = context(Path(tmp))
        before = snapshot(root, workspace)
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("network forbidden")), \
             patch("subprocess.run",
                   side_effect=AssertionError("subprocess forbidden")):
            report = validate(root, workspace, old)
        assert report["status"] == "LEXICAL_CANARY_PASSED", report
        assert report["matched_terms"] == ["authorized", "signatory", "minor", "works"]
        assert report["missing_terms"] == []
        assert report["chunk_count"] >= 1
        assert report["citation_present"] is True
        assert all(x["page_number"] == 1 for x in report["ranked_evidence"])
        assert all(x["evidence_origin"] == "native_text"
                   for x in report["ranked_evidence"])
        assert all(len(x["content_sha256"]) == 64
                   for x in report["ranked_evidence"])
        assert report["gold_page_verified"] is None
        assert report["retrieval_verified"] is False
        assert report["production_write"] is False
        assert report["shared_db_access"] is False
        assert report["proof_written"] is False
        assert snapshot(root, workspace) == before
        assert validate(root, workspace, old) == report


def test_missing_term_fails_smoke_not_pass():
    import m10b2a_candidate_lexical_v1 as module
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        real = module.trusted_source
        def changed(source_id):
            source, host = real(source_id)
            source = dict(source)
            validation = dict(source["staging_validation"])
            validation["expect_terms"] = ["authorized", "unfindableunicorn"]
            source["staging_validation"] = validation
            return source, host
        with patch.object(module, "trusted_source", side_effect=changed):
            report = validate(root, workspace, old)
        assert report["status"] == "LEXICAL_CANARY_FAILED", report
        assert report["missing_terms"] == ["unfindableunicorn"]


def test_unrelated_query_gives_no_hits():
    import m10b2a_candidate_lexical_v1 as module
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        real = module.trusted_source
        def changed(source_id):
            source, host = real(source_id)
            source = dict(source)
            source["staging_validation"] = {"query": "unfindableunicorn jellyfish", "expect_terms": ["jellyfish"]}
            return source, host
        with patch.object(module, "trusted_source", side_effect=changed):
            report = validate(root, workspace, old)
        assert report["status"] == "LEXICAL_CANARY_FAILED", report
        assert report["ranked_evidence"] == []


def test_empty_expectations_blocked():
    import m10b2a_candidate_lexical_v1 as module
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        real = module.trusted_source
        def changed(source_id):
            source, host = real(source_id)
            source = dict(source)
            source["staging_validation"] = {"query": "authorized signatory", "expect_terms": []}
            return source, host
        with patch.object(module, "trusted_source", side_effect=changed):
            report = validate(root, workspace, old)
        assert report["status"] == "BLOCKED", report


def test_mismatched_candidate_sha_and_source_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        assert run("BD_PNAP_APP145", old["candidate_sha256"],
                   state_root=root, workspace_root=workspace)["status"] == "BLOCKED"
        assert run(SOURCE, "a" * 64, state_root=root,
                   workspace_root=workspace)["status"] == "BLOCKED"


def test_evidence_tamper_and_reference_drift_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        root, _, items, workspace, old = context(Path(tmp))
        folder = workspace / "candidates" / SOURCE / old["candidate_sha256"]
        evidence = folder / "evidence.json"
        record = json.loads(evidence.read_text())
        record["trusted_identity"]["canonical_host"] = "evil.example"
        save(evidence, record)
        assert validate(root, workspace, old)["status"] == "BLOCKED"
    with tempfile.TemporaryDirectory() as tmp:
        root, _, items, workspace, old = context(Path(tmp))
        record = json.loads(items[SOURCE]["ref"].read_text())
        record["snapshot"]["metadata_fingerprint"] = "f" * 64
        save(items[SOURCE]["ref"], record)
        assert validate(root, workspace, old)["status"] == "BLOCKED"


def test_pdf_tamper_and_manifest_drift_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        pdf = workspace / "candidates" / SOURCE / old["candidate_sha256"] / "candidate.pdf"
        pdf.write_bytes(pdf.read_bytes() + b"altered")
        assert validate(root, workspace, old)["status"] == "BLOCKED"
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        import extract_document_v2
        orig = extract_document_v2.build_manifest
        def drift(path):
            manifest = orig(path)
            manifest["summary"]["total_text_chars"] += 1
            return manifest
        with patch("extract_document_v2.build_manifest", side_effect=drift):
            result = validate(root, workspace, old)
        assert result["status"] == "BLOCKED", result
        assert "manifest_hash_or_parser_drift" in str(result["reasons"])


def test_wrong_page_and_provenance_blocked():
    import build_multimodal_chunks_v2
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        real = build_multimodal_chunks_v2.build_chunks
        def bad(manifest, target_chars, overlap_chars):
            chunks = real(manifest, target_chars, overlap_chars)
            chunks[0]["page_start"] = 999
            return chunks
        with patch("build_multimodal_chunks_v2.build_chunks", side_effect=bad):
            assert validate(root, workspace, old)["status"] == "BLOCKED"
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        real = build_multimodal_chunks_v2.build_chunks
        def bad(manifest, target_chars, overlap_chars):
            chunks = real(manifest, target_chars, overlap_chars)
            chunks[0]["metadata"]["evidence_origin"] = "visual_understanding"
            return chunks
        with patch("build_multimodal_chunks_v2.build_chunks", side_effect=bad):
            assert validate(root, workspace, old)["status"] == "BLOCKED"


def test_symlink_and_no_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _, workspace, old = context(Path(tmp))
        folder = workspace / "candidates" / SOURCE / old["candidate_sha256"]
        original = folder / "candidate.pdf"
        moved = folder / "moved.pdf"
        original.rename(moved)
        original.symlink_to(moved)
        assert validate(root, workspace, old)["status"] == "BLOCKED"
    with tempfile.TemporaryDirectory() as tmp:
        root, _, _ = make(Path(tmp), decision="NO_CHANGE")
        workspace = Path(tmp) / "source-update-validation-staging"
        assert run(SOURCE, "a"*64, state_root=root,
                   workspace_root=workspace)["status"] == "BLOCKED"
        assert not workspace.exists()


def test_ranker_ties_stable_and_no_false_gold():
    def chunk(index, page, content):
        return {"chunk_index": index, "page_start": page,
                "content": content,
                "metadata": {"evidence_origin": "native_text"}}
    hits = rank_lexical([
        chunk(0, 2, "authorized signatory form"),
        chunk(1, 1, "authorized signatory form"),
        chunk(2, 3, "unrelated topic"),
    ], "authorized signatory", 2)
    assert [x["page_number"] for x in hits] == [1, 2]
    assert hits[0]["score"] == 2
    assert words("What's an authorized signatory?") >= {"authorized", "signatory"}


def main_test():
    cases = [
        test_candidate_only_smoke_and_no_writes,
        test_missing_term_fails_smoke_not_pass,
        test_unrelated_query_gives_no_hits,
        test_empty_expectations_blocked,
        test_mismatched_candidate_sha_and_source_blocked,
        test_evidence_tamper_and_reference_drift_blocked,
        test_pdf_tamper_and_manifest_drift_blocked,
        test_wrong_page_and_provenance_blocked,
        test_symlink_and_no_candidate,
        test_ranker_ties_stable_and_no_false_gold,
    ]
    for case in cases:
        case()
        print(case.__name__ + ": PASS")
    print("M10B-2A isolated lexical regression: PASS")


if __name__ == "__main__":
    main_test()
