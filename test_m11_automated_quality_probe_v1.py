#!/usr/bin/env python3
"""Offline, synthetic-only M11 automation contract tests; no real official PDF."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import m11_automated_quality_probe_v1 as m11


def fake_manifest():
    return {
        "schema_version": "document-manifest-v2",
        "source": {"sha256": m11.PINNED_PDF_SHA256},
        "document": {"kind": "pdf", "page_count": 5},
        "units": [{"page_number": i, "text": "synthetic page"}
                  for i in range(1, 6)],
        "summary": {
            "total_text_chars": 70, "total_tables": 0,
            "ocr_candidate_units": [], "vector_candidate_units": [],
        },
        "extraction": {"database_write_performed": False,
                       "ocr_performed": False, "vision_model_used": False},
    }


def fake_silver():
    return {
        "source_id": m11.PINNED_SOURCE_ID,
        "expected_original_pdf_sha256": m11.PINNED_PDF_SHA256,
        "case_count": 5,
        "counts": {"MACHINE_EVIDENCE_CHECKED": 1,
                   "HUMAN_REVIEW_REQUIRED": 4,
                   "REJECTED_EVIDENCE_MISMATCH": 0},
        "gold_page_verified": None, "official_source_verified": False,
        "human_gold_cases_approved": 0,
        "production_access": False, "write_authorized": False,
    }


def fake_packet(question):
    pages = [5, 5, 3, 1, 4, 1, 2, 2]
    return {
        "environment": "staging", "production_write": False,
        "read_only": True, "guard_ok": True,
        "source": {"source_id": m11.PINNED_SOURCE_ID,
                   "checksum": m11.PINNED_PDF_SHA256,
                   "currentness_verified": False},
        "retrieval_coverage": {"complete_index_coverage": True,
                               "indexed_chunks": 8,
                               "retrieved_unique_chunks": 8},
        "integrity": {"integrity_ok": True},
        "evidence": [{"chunk_id": 120+i, "page": p,
                      "distance": float(i)/10, "content": "synthetic"}
                     for i,p in enumerate(pages)],
    }


def refused(fn):
    try:
        fn()
    except m11.AutoQualityRefused:
        return
    raise AssertionError("expected automatic quality refusal")


def test_document_manifest_pinned_and_flags():
    r = m11.summarize_document_manifest(fake_manifest())
    assert r["physical_pages"] == 5
    assert r["source_sha256"] == m11.PINNED_PDF_SHA256
    assert r["needs_separate_ocr_or_table_validation"] is False
    assert "synthetic page" not in json.dumps(r)

    bad = fake_manifest()
    bad["summary"]["ocr_candidate_units"] = [4]
    bad["units"][2]["table_extraction_errors"] = ["fictional error"]
    r = m11.summarize_document_manifest(bad)
    assert r["ocr_or_vector_or_table_error_pages"] == [3, 4]
    assert r["needs_separate_ocr_or_table_validation"]

    bad = fake_manifest()
    bad["source"]["sha256"] = "0" * 64
    refused(lambda: m11.summarize_document_manifest(bad))
    bad = fake_manifest()
    bad["units"][2]["page_number"] = 4
    refused(lambda: m11.summarize_document_manifest(bad))
    bad = fake_manifest()
    bad["extraction"]["database_write_performed"] = True
    refused(lambda: m11.summarize_document_manifest(bad))


def test_silver_risk_automatically_held_no_human_gold():
    r = m11.summarize_silver_verification(fake_silver())
    assert r["auto_evidence_checked"] == 1
    assert r["auto_hold_unverified"] == 4
    assert r["auto_rejected_evidence"] == 0
    assert r["not_human_verified"] is True
    assert r["official_gold_approved"] == 0
    assert r["safe_for_automatic_anki_publication"] is False

    bad = fake_silver()
    bad["gold_page_verified"] = True
    refused(lambda: m11.summarize_silver_verification(bad))
    bad = fake_silver()
    bad["counts"]["HUMAN_REVIEW_REQUIRED"] = 3
    refused(lambda: m11.summarize_silver_verification(bad))


def test_retrieval_candidate_rank_never_called_accuracy():
    packet = fake_packet("synthetic question")
    r = m11.summarize_retrieval_packet(packet, "SYNTHETIC-P01", 2)
    assert r["first_proposed_page_rank"] == 7
    assert r["top_5_physical_pages"] == [5, 5, 3, 1, 4]
    assert r["answer_correctness_verified"] is False
    assert "accuracy" not in json.dumps(r).lower()
    bad = fake_packet("q")
    bad["integrity"]["integrity_ok"] = False
    refused(lambda: m11.summarize_retrieval_packet(bad, "x", 2))
    bad = fake_packet("q")
    bad["evidence"][4]["chunk_id"] = bad["evidence"][0]["chunk_id"]
    refused(lambda: m11.summarize_retrieval_packet(bad, "x", 2))
    bad = fake_packet("q")
    bad["evidence"][2]["distance"] = float("nan")
    refused(lambda: m11.summarize_retrieval_packet(bad, "x", 2))
    bad = fake_packet("q")
    bad["production_write"] = True
    refused(lambda: m11.summarize_retrieval_packet(bad, "x", 2))


def test_retrieval_uses_existing_staging_and_has_guard():
    with patch.object(m11.qa, "build_packet",
                      side_effect=lambda sid,q: fake_packet(q)) as mocked, \\
         patch.object(m11.qa, "generate_draft",
                      side_effect=AssertionError("no external model")):
        report = m11.run_retrieval_probe()
    assert mocked.call_count == 3
    assert len(report["cases"]) == 3
    assert report["current_law_question"] == "CURRENTNESS_UNVERIFIED_ABSTAIN"
    assert report["semantic_answer_accuracy"] == "NOT_MEASURED"
    assert all(x["first_proposed_page_rank"] is not None
               for x in report["cases"])
    assert "暫時代理" not in json.dumps(report, ensure_ascii=False)


def test_pinned_file_guard_and_end_to_end_with_synthetic_mocks():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "synthetic.pdf"
        raw = b"not a real PDF" * 20
        path.write_bytes(raw)
        refused(lambda: m11.build_report(path))
        with patch.object(m11, "PINNED_PDF_SHA256",
                          hashlib.sha256(raw).hexdigest()), \\
             patch.object(m11, "build_manifest",
                          side_effect=lambda p: fake_manifest()), \\
             patch.object(m11, "run_app149_readonly_pilot",
                          side_effect=lambda b: fake_silver()):
            report = m11.build_report(path)
            assert report["external_ai_called"] is False
            assert report["production_write"] is False
            assert report["anki_package_created"] is False
            assert report["answer_correctness_accuracy"] == "UNKNOWN_NOT_MEASURED"
            assert report["human_verification_requested"] is False
            assert report["evidence_verifier"]["auto_hold_unverified"] == 4
            assert report["retrieval"] is None
            link = Path(tmp) / "link.pdf"
            link.symlink_to(path)
            refused(lambda: m11.build_report(link))


def test_no_provider_or_db_write_path_in_probe():
    code = Path(m11.__file__).read_text(encoding="utf-8")
    for forbidden in ("generate_draft(", "get_model_config(", "api.deepseek.com",
                      "subprocess.run(", "psql(", "INSERT INTO", "UPDATE documents",
                      "gdrive-bd-write:", "AnkiConnect", "0.0.0.0"):
        assert forbidden not in code, forbidden


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("M11 AUTOMATED QUALITY OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
