#!/usr/bin/env python3
"""Read-only Document v2 table quality diagnosis; NOT table semantic accuracy.

Reuse existing Extractor, Router, and Chunk Builder, producing redacted counts.
No AI, database, Drive, Production or Anki connection, and no human review.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from build_multimodal_chunks_v2 import build_chunks
from extract_document_v2 import build_manifest
from route_document_v2 import assess_manifest

VERSION = "document-ingest-quality-audit-v1"
MAX_PDF_BYTES = 20_000_000
MAX_PAGES = 150


class IngestAuditRefused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise IngestAuditRefused(reason)


def table_shape(table, page_number, width, height):
    """Validate structure and bbox without claiming cell OCR is correct."""
    issues = []
    rows = table.get("rows")
    nrows = table.get("row_count")
    ncols = table.get("column_count")
    index = table.get("table_index")
    if not isinstance(rows, list) or not rows:
        return ["TABLE_ROWS_MISSING"]
    if (type(nrows) is not int or type(ncols) is not int
            or nrows <= 0 or ncols <= 0 or len(rows) != nrows
            or type(index) is not int or index < 0):
        return ["TABLE_DIMENSIONS_INVALID"]
    if any(not isinstance(row, list) or len(row) != ncols for row in rows):
        issues.append("TABLE_RAGGED_ROWS")
    nonempty = sum(bool(str(cell).strip()) for row in rows
                   for cell in row if cell is not None)
    if not nonempty:
        issues.append("TABLE_ALL_CELLS_EMPTY")
    bbox = table.get("bbox")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   for v in bbox)
            or not (0 <= bbox[0] < bbox[2] <= width + 1
                    and 0 <= bbox[1] < bbox[3] <= height + 1)):
        issues.append("TABLE_BBOX_INVALID")
    return issues


def analyze_manifest(manifest, *, drive_file_id, expected_size,
                     expected_sha256=None):
    require(manifest.get("schema_version") == "document-manifest-v2",
            "manifest_schema_invalid")
    source = manifest.get("source") or {}
    doc = manifest.get("document") or {}
    pages = manifest.get("units") or []
    sha = source.get("sha256")
    require(type(sha) is str and len(sha) == 64
            and all(c in "0123456789abcdef" for c in sha),
            "manifest_source_sha_invalid")
    require(source.get("size_bytes") == expected_size,
            "source_size_mismatch")
    if expected_sha256 is not None:
        require(sha == expected_sha256, "source_sha_mismatch")
    count = doc.get("page_count")
    require(doc.get("kind") == "pdf" and type(count) is int
            and 0 < count <= MAX_PAGES,
            "pdf_page_count_refused")
    require(len(pages) == count and
            [p.get("page_number") for p in pages] == list(range(1, count+1)),
            "physical_pages_not_contiguous")
    extraction = manifest.get("extraction") or {}
    require(extraction.get("database_write_performed") is False
            and extraction.get("ocr_performed") is False
            and extraction.get("vision_model_used") is False,
            "unexpected_side_effects_or_model")
    router = assess_manifest(manifest, allow_partial=False)
    require(router.get("safety", {}).get("database_write_performed") is False,
            "router_side_effect_refused")
    chunks = build_chunks(manifest, target_chars=1800, overlap_chars=250)
    table_chunk_groups = {}
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        page = chunk.get("page_start")
        require(type(page) is int and 1 <= page <= count
                and chunk.get("page_end") == page
                and meta.get("page_number") == page,
                "chunk_page_provenance_invalid")
        if meta.get("evidence_origin") == "structured_table":
            require(meta.get("modality") == "table"
                    and meta.get("evidence_tier") == "primary"
                    and isinstance(chunk.get("content"), str)
                    and bool(chunk["content"].strip()),
                    "structured_table_chunk_invalid")
            table_chunk_groups.setdefault(
                (page, meta.get("table_index")), []).append(meta)
    issues = []
    page_reports = []
    expected_table_keys = set()
    detected_tables = 0
    table_rows = 0
    for p in pages:
        pg = p["page_number"]
        require(type(p.get("width")) in (int, float)
                and type(p.get("height")) in (int, float)
                and p["width"] > 0 and p["height"] > 0,
                "page_geometry_invalid")
        tables = p.get("tables") or []
        require(isinstance(tables, list), "table_list_invalid")
        local_issues = []
        if p.get("table_extraction_errors"):
            local_issues.append("TABLE_EXTRACTOR_REPORTED_ERROR")
        if (p.get("layout_metrics") or {}).get("text_table_candidate") and not tables:
            local_issues.append("TEXT_TABLE_CANDIDATE_WITHOUT_STRUCTURE")
        if p.get("ocr_candidate") or p.get("vector_candidate"):
            local_issues.append("OCR_OR_VECTOR_CANDIDATE_NOT_PROCESSED")
        for table in tables:
            require(isinstance(table, dict), "table_object_invalid")
            detected_tables += 1
            table_rows += table.get("row_count") if type(table.get("row_count")) is int else 0
            key = (pg, table.get("table_index"))
            require(key not in expected_table_keys, "duplicate_table_index")
            expected_table_keys.add(key)
            local_issues.extend(table_shape(
                table, pg, p["width"], p["height"]))
            subchunks = table_chunk_groups.get(key) or []
            if not subchunks:
                local_issues.append("STRUCTURED_TABLE_NOT_IN_CHUNKS")
            elif any(m.get("table_row_count") != table.get("row_count")
                     or m.get("table_column_count") != table.get("column_count")
                     or m.get("table_detection_strategy") != table.get("detection_strategy")
                     for m in subchunks):
                local_issues.append("TABLE_CHUNK_METADATA_MISMATCH")
        page_reports.append({
            "page": pg,
            "native_text_chars": p.get("text_chars"),
            "tables_detected": len(tables),
            "table_rows": [t.get("row_count") for t in tables],
            "table_columns": [t.get("column_count") for t in tables],
            "issue_codes": sorted(set(local_issues)),
        })
        issues.extend(local_issues)
    if expected_table_keys != set(table_chunk_groups):
        issues.append("UNEXPECTED_STRUCTURED_TABLE_CHUNK")
    if not detected_tables:
        issues.append("NO_STRUCTURED_TABLE_DETECTED")
    route = (router.get("decision") or {}).get("recommended_pipeline")
    if detected_tables and route == "legacy-v1":
        issues.append("LEGACY_ROUTE_MAY_DROP_TABLE_STRUCTURE")
    if route not in ("legacy-v1", "multimodal-v2"):
        issues.append("ROUTER_DECISION_UNKNOWN")
    return {
        "version": VERSION,
        "test_scope": "existing_pdf_extract_route_chunks_only",
        "status": "AUTO_HOLD_UNVERIFIED" if issues else "MECHANICAL_CHECKS_PASS_LIMITED",
        "source": {
            "drive_file_id": drive_file_id,
            "observed_sha256": sha,
            "size_bytes": source["size_bytes"],
            "drive_sha_independently_verified": expected_sha256 is not None,
            "official_legal_version_verified": False,
        },
        "document": {
            "physical_pages": count,
            "tables_detected": detected_tables,
            "table_rows_total": table_rows,
            "structured_table_chunk_count": sum(
                len(v) for v in table_chunk_groups.values()),
            "all_chunk_count": len(chunks),
            "router_recommendation": route,
        },
        "pages": page_reports,
        "issue_codes": sorted(set(issues)),
        "semantic_table_accuracy": "NOT_MEASURED",
        "ocr_or_vision_performed": False,
        "database_access": False,
        "external_ai_called": False,
        "production_write": False,
        "drive_write": False,
        "human_review_required": False,
        "notice": ("Mechanical structural checks are not proof of table cell, "
                   "number, unit or semantic accuracy. Auto-hold uncertain content."),
    }


def audit_pdf(path, *, drive_file_id, expected_size, expected_sha256=None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "source_path_refused")
    require(type(expected_size) is int and
            100 <= expected_size <= MAX_PDF_BYTES,
            "expected_size_refused")
    require(path.stat().st_size == expected_size, "source_size_mismatch")
    if expected_sha256 is not None:
        require(type(expected_sha256) is str and len(expected_sha256) == 64,
                "expected_sha_shape_invalid")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256,
                "source_sha_mismatch")
    return analyze_manifest(
        build_manifest(path),
        drive_file_id=drive_file_id,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--drive-file-id", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    require(bool(args.drive_file_id.strip()), "drive_file_id_missing")
    result = audit_pdf(
        args.pdf, drive_file_id=args.drive_file_id,
        expected_size=args.expected_size,
        expected_sha256=args.expected_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (IngestAuditRefused, RuntimeError, ValueError) as exc:
        raise SystemExit("INGEST_AUDIT_REFUSED: " + str(exc)) from None
