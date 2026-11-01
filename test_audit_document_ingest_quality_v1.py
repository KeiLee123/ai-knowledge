#!/usr/bin/env python3
"""Offline synthetic test, no live documents."""
from audit_document_ingest_quality_v1 import (
    table_shape, analyze_manifest, IngestAuditRefused,
)


def sample():
    return {
        "schema_version": "document-manifest-v2",
        "source": {"sha256": "a" * 64, "size_bytes": 1024},
        "document": {"kind": "pdf", "page_count": 1},
        "selection": {"page_numbers": None},
        "extraction": {
            "database_write_performed": False,
            "ocr_performed": False,
            "vision_model_used": False,
        },
        "units": [{
            "unit_type": "page", "page_number": 1,
            "width": 612.0, "height": 792.0,
            "text": "Synthetic table", "text_chars": 15,
            "images": [], "table_extraction_errors": [],
            "layout_metrics": {"text_table_candidate": True},
            "vector_metrics": {"meaningful_drawing_item_count": 500},
            "ocr_candidate": False, "vector_candidate": False,
            "tables": [{
                "table_index": 0, "detection_strategy": "lines",
                "bbox": [10.0, 10.0, 200.0, 150.0],
                "row_count": 2, "column_count": 2,
                "rows": [["Item", "Limit"], ["Concrete", "40 mm"]],
            }],
        }],
    }


def inspect(m):
    return analyze_manifest(
        m, drive_file_id="SYNTHETIC",
        expected_size=1024, expected_sha256="a" * 64,
    )



def test_bounded_full_document_coverage():
    import hashlib
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    import audit_document_ingest_quality_v1 as audit

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.pdf"
        raw = b"synthetic test PDF substitute" * 12
        path.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        calls = []

        def fake_builder(_path, selected_pages=None):
            assert _path == path
            assert selected_pages and len(selected_pages) <= 25
            calls.append(list(selected_pages))
            m = sample()
            m["source"]["sha256"] = sha
            m["source"]["size_bytes"] = len(raw)
            m["document"]["page_count"] = 298
            m["selection"]["page_numbers"] = list(selected_pages)
            m["units"] = []
            for number in selected_pages:
                unit = sample()["units"][0]
                unit["page_number"] = number
                unit["unit_index"] = number - 1
                unit["tables"] = []
                unit["layout_metrics"] = {"text_table_candidate": False}
                unit["vector_metrics"] = {
                    "meaningful_drawing_item_count": 0,
                }
                if number > 150:
                    unit["text"] = ""
                    unit["text_chars"] = 0
                m["units"].append(unit)
            return m

        with patch("pymupdf.open") as reader, patch.object(
            audit, "build_manifest", side_effect=fake_builder
        ):
            reader.return_value.__enter__.return_value.is_pdf = True
            reader.return_value.__enter__.return_value.page_count = 298
            result = audit.audit_pdf_batched(
                path, drive_file_id="SYNTHETIC",
                expected_size=len(raw), expected_sha256=sha,
            )
        assert result["document"]["physical_pages"] == 298
        assert result["document"]["pages_covered"] == 298
        assert result["document"]["native_text_pages"] == 150
        assert result["document"]["no_native_text_pages"] == 148
        assert sum(b["native_text_pages"] + b["no_native_text_pages"]
                   for b in result["batches"]) == 298
        assert result["batches"][-1]["native_text_pages"] == 0
        assert result["batches"][-1]["no_native_text_pages"] == 23
        assert result["document"]["coverage_complete"] is True
        assert result["document"]["batch_count"] == 12
        assert result["document"]["batch_size"] == 25
        assert result["batches"][-1]["first_page"] == 276
        assert result["batches"][-1]["last_page"] == 298
        assert calls[0] == list(range(1, 26))
        assert calls[-1] == list(range(276, 299))
        assert result["status"] == "AUTO_HOLD_UNVERIFIED"
        assert "NO_STRUCTURED_TABLE_DETECTED" in result["issue_codes"]
        assert result["semantic_table_accuracy"] == "NOT_MEASURED"
        assert result["source"]["drive_sha_independently_verified"] is False
        assert result["external_ai_called"] is False
        assert result["database_access"] is False
        print("test_298_page_batched_coverage: PASS")



def test_report_json_is_independent_of_pdf_library_notice():
    import io
    import json
    import sys
    import tempfile
    from contextlib import redirect_stdout
    from pathlib import Path
    from unittest.mock import patch
    import audit_document_ingest_quality_v1 as audit

    def fake_audit(*args, **kwargs):
        print("Consider using the pymupdf_layout package.")
        return {
            "status": "AUTO_HOLD_UNVERIFIED",
            "document": {"physical_pages": 298, "pages_covered": 298},
        }

    with tempfile.TemporaryDirectory() as folder:
        report = Path(folder) / "report.json"
        args = [
            "audit_document_ingest_quality_v1.py",
            "--pdf", "/tmp/synthetic-only.pdf",
            "--drive-file-id", "SYNTHETIC",
            "--expected-size", "1024",
            "--report-json", str(report),
        ]
        stdout = io.StringIO()
        with patch.object(sys, "argv", args), patch.object(
            audit, "audit_pdf_batched", side_effect=fake_audit
        ), redirect_stdout(stdout):
            audit.main()
        assert "Consider using the pymupdf_layout" in stdout.getvalue()
        assert "REPORT_JSON_WRITTEN" in stdout.getvalue()
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["document"]["physical_pages"] == 298
        assert data["status"] == "AUTO_HOLD_UNVERIFIED"
    print("test_report_json_ignores_pdf_notice: PASS")



def test_real_canonical_text_sql_builder_preserves_table_metadata():
    # The writer builds SQL text only; do NOT run SQL or connect to a DB.
    from pathlib import Path
    from build_multimodal_chunks_v2 import build_chunks
    from ingest_canonical_text_staging_v1 import build_text_transaction_sql

    m = sample()
    m["units"][0]["vector_metrics"]["meaningful_drawing_item_count"] = 0
    chunks = build_chunks(m, target_chars=1800, overlap_chars=250)
    tables = [x for x in chunks
              if x["metadata"].get("evidence_origin") == "structured_table"]
    assert len(tables) == 1
    sql = build_text_transaction_sql(
        payload={"chunks": tables,
                 "source_manifest": {"document_sha256": "a" * 64},
                 "summary": {"chunk_count": len(tables),
                             "counts_by_origin": {"structured_table": 1}}},
        vectors=[[0.0] * 384],
        chunks_path=Path("synthetic-only-chunks.json"),
        title="synthetic-only", domain="test", topic="test",
        document_type="test", authority="", jurisdiction="HK",
        language="en", source_url="", canonical_source="TEST_ONLY",
    )
    assert '"evidence_origin":"structured_table"' in sql
    assert '"modality":"table"' in sql
    assert '"table_row_count":2' in sql
    assert '"table_column_count":2' in sql
    assert '"page_number":1' in sql
    assert "INSERT INTO chunks" in sql
    assert "COMMIT" in sql
    print("test_canonical_text_sql_metadata_preview: PASS")



def test_native_text_metrics_fail_closed():
    m = sample()
    r = inspect(m)
    assert r["document"]["native_text_pages"] == 1
    assert r["document"]["no_native_text_pages"] == 0
    assert r["pages"][0]["native_text_chars"] == 15

    m = sample()
    m["units"][0]["text"] = ""
    m["units"][0]["text_chars"] = 0
    r = inspect(m)
    assert r["document"]["native_text_pages"] == 0
    assert r["document"]["no_native_text_pages"] == 1

    for invalid in ("missing", "none", "string", "mismatch"):
        m = sample()
        if invalid == "missing":
            del m["units"][0]["text_chars"]
        elif invalid == "none":
            m["units"][0]["text_chars"] = None
        elif invalid == "string":
            m["units"][0]["text_chars"] = "15"
        else:
            m["units"][0]["text_chars"] = 1
        try:
            inspect(m)
        except IngestAuditRefused as exc:
            assert "native_text_metric_invalid" in str(exc)
        else:
            raise AssertionError("invalid native text metric was accepted")
    print("test_native_text_metric_coverage_and_fail_closed: PASS")


def main():
    test_native_text_metrics_fail_closed()
    test_real_canonical_text_sql_builder_preserves_table_metadata()
    test_report_json_is_independent_of_pdf_library_notice()
    test_bounded_full_document_coverage()
    m = sample()
    assert table_shape(m["units"][0]["tables"][0], 1, 612, 792) == []
    r = inspect(m)
    assert r["status"] == "MECHANICAL_CHECKS_PASS_LIMITED", r
    assert r["document"]["tables_detected"] == 1
    assert r["document"]["structured_table_chunk_count"] >= 1
    print("test_structured_table_preserved: PASS")

    m = sample()
    m["units"][0]["vector_metrics"]["meaningful_drawing_item_count"] = 0
    r = inspect(m)
    assert r["status"] == "MECHANICAL_CHECKS_PASS_LIMITED", r
    assert r["document"]["legacy_table_writer_metadata_checked"] == 1
    assert r["document"]["legacy_table_writer_metadata_mismatches"] == 0
    assert r["db_roundtrip_verified"] is False
    print("test_legacy_text_writer_metadata_preserved: PASS")

    import audit_document_ingest_quality_v1 as audit
    from unittest.mock import patch
    with patch.object(audit, "text_chunk_metadata", return_value={}):
        failed = inspect(m)
    assert failed["status"] == "AUTO_HOLD_UNVERIFIED"
    assert "LEGACY_TEXT_WRITER_TABLE_METADATA_MISMATCH" in failed["issue_codes"]
    assert failed["document"]["legacy_table_writer_metadata_mismatches"] == 1
    print("test_legacy_text_writer_metadata_loss_held: PASS")

    m = sample()
    m["units"][0]["tables"] = []
    r = inspect(m)
    assert "NO_STRUCTURED_TABLE_DETECTED" in r["issue_codes"]
    assert "TEXT_TABLE_CANDIDATE_WITHOUT_STRUCTURE" in r["issue_codes"]
    print("test_missing_table_auto_hold: PASS")

    m = sample()
    m["units"][0]["ocr_candidate"] = True
    assert "OCR_OR_VECTOR_CANDIDATE_NOT_PROCESSED" in inspect(m)["issue_codes"]
    print("test_ocr_auto_hold: PASS")

    m = sample()
    m["units"][0]["tables"][0]["rows"][1].pop()
    assert "TABLE_RAGGED_ROWS" in inspect(m)["issue_codes"]
    print("test_ragged_table_auto_hold: PASS")

    m = sample()
    m["units"][0]["page_number"] = 2
    try:
        inspect(m)
    except IngestAuditRefused:
        pass
    else:
        raise AssertionError("page safety gate did not refuse")
    print("test_wrong_page_refused: PASS")
    print("DOCUMENT INGEST QUALITY OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
