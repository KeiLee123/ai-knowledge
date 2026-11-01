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


def main():
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
    assert r["status"] == "AUTO_HOLD_UNVERIFIED"
    assert "LEGACY_ROUTE_MAY_DROP_TABLE_STRUCTURE" in r["issue_codes"]
    print("test_legacy_route_auto_hold: PASS")

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
