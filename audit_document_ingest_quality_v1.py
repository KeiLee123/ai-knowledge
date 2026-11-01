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
from ingest_canonical_text_staging_v1 import text_chunk_metadata
from route_document_v2 import assess_manifest

VERSION = "document-ingest-quality-audit-v1"
MAX_PDF_BYTES = 20_000_000
MAX_PAGES = 150  # Existing single-manifest ceiling remains unchanged.
MAX_DOCUMENT_PAGES = 500  # Separate capped streaming/partial audit scope.
DEFAULT_BATCH_SIZE = 25


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
            and 0 < count <= MAX_DOCUMENT_PAGES,
            "pdf_page_count_refused")
    selection = (manifest.get("selection") or {}).get("page_numbers")
    if selection is None:
        require(count <= MAX_PAGES and len(pages) == count,
                "unbatched_page_limit_refused")
        expected_pages = list(range(1, count + 1))
    else:
        require(isinstance(selection, list)
                and 0 < len(selection) <= DEFAULT_BATCH_SIZE
                and all(type(page) is int and 1 <= page <= count
                        for page in selection)
                and selection == sorted(set(selection)),
                "invalid_batch_page_selection")
        expected_pages = selection
    require([p.get("page_number") for p in pages] == expected_pages,
            "physical_pages_not_contiguous")
    extraction = manifest.get("extraction") or {}
    require(extraction.get("database_write_performed") is False
            and extraction.get("ocr_performed") is False
            and extraction.get("vision_model_used") is False,
            "unexpected_side_effects_or_model")
    router = assess_manifest(manifest, allow_partial=selection is not None)
    require(router.get("safety", {}).get("database_write_performed") is False,
            "router_side_effect_refused")
    route = (router.get("decision") or {}).get("recommended_pipeline")
    chunks = build_chunks(manifest, target_chars=1800, overlap_chars=250)
    table_chunk_groups = {}
    legacy_table_writer_metadata_checked = 0
    legacy_table_writer_metadata_mismatches = 0
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
            if route == "legacy-v1":
                # Reuse the real pure metadata adapter in the canonical text
                # writer; never connect to DB or precompute embeddings here.
                writer_meta = text_chunk_metadata(chunk)
                keys = (
                    "evidence_origin", "modality", "evidence_tier",
                    "page_number", "table_index", "table_row_count",
                    "table_column_count", "table_detection_strategy",
                    "table_bbox",
                )
                if all(writer_meta.get(key) == meta.get(key)
                       for key in keys):
                    legacy_table_writer_metadata_checked += 1
                else:
                    legacy_table_writer_metadata_mismatches += 1
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
        # Extractor's documented field is text_chars; do not silently count
        # missing statistics as zero in the final quality report.
        chars = p.get("text_chars")
        native_text = p.get("text")
        require(type(chars) is int and chars >= 0
                and isinstance(native_text, str)
                and len(native_text) == chars,
                "native_text_metric_invalid")
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
            "native_text_chars": chars,
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
    if legacy_table_writer_metadata_mismatches:
        issues.append("LEGACY_TEXT_WRITER_TABLE_METADATA_MISMATCH")
    if route not in ("legacy-v1", "multimodal-v2"):
        issues.append("ROUTER_DECISION_UNKNOWN")
    native_text_pages = sum(
        p["native_text_chars"] > 0 for p in page_reports)
    no_native_text_pages = sum(
        p["native_text_chars"] == 0 for p in page_reports)
    require(native_text_pages + no_native_text_pages == len(pages),
            "native_text_coverage_incomplete")
    return {
        "version": VERSION,
        "test_scope": "existing_pdf_extract_route_chunks_only",
        "status": "AUTO_HOLD_UNVERIFIED" if issues else "MECHANICAL_CHECKS_PASS_LIMITED",
        "source": {
            "drive_file_id": drive_file_id,
            "observed_sha256": sha,
            "size_bytes": source["size_bytes"],
            "expected_sha256_matched": expected_sha256 is not None,
            "drive_sha_independently_verified": False,
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
            "legacy_table_writer_metadata_checked":
                legacy_table_writer_metadata_checked,
            "legacy_table_writer_metadata_mismatches":
                legacy_table_writer_metadata_mismatches,
            "native_text_pages": native_text_pages,
            "no_native_text_pages": no_native_text_pages,
        },
        "pages": page_reports,
        "issue_codes": sorted(set(issues)),
        "semantic_table_accuracy": "NOT_MEASURED",
        "db_roundtrip_verified": False,
        "legacy_writer_metadata_preview_only": True,
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


def audit_pdf_batched(path, *, drive_file_id, expected_size,
                      expected_sha256=None, batch_size=DEFAULT_BATCH_SIZE):
    """Read-only bounded, COMPLETE page coverage; never promote partial data."""
    import pymupdf

    require(type(batch_size) is int and batch_size == DEFAULT_BATCH_SIZE,
            "batch_size_refused")
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "source_path_refused")
    require(type(expected_size) is int
            and 100 <= expected_size <= MAX_PDF_BYTES
            and path.stat().st_size == expected_size, "source_size_mismatch")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 is not None:
        require(sha == expected_sha256, "source_sha_mismatch")
    with pymupdf.open(path) as pdf:
        require(pdf.is_pdf, "not_a_pdf")
        count = pdf.page_count
    require(0 < count <= MAX_DOCUMENT_PAGES,
            "document_page_limit_refused")

    batches = []
    reviewed_pages = set()
    all_issues = set()
    issue_pages_by_code = {}
    total_tables = 0
    total_rows = 0
    total_chunks = 0
    total_table_chunks = 0
    total_native_text_pages = 0
    total_no_native_text_pages = 0
    total_legacy_writer_checked = 0
    total_legacy_writer_mismatches = 0
    routing_counts = {}
    for start in range(1, count + 1, batch_size):
        pages = list(range(start, min(start + batch_size, count + 1)))
        manifest = build_manifest(path, selected_pages=pages)
        result = analyze_manifest(
            manifest, drive_file_id=drive_file_id,
            expected_size=expected_size, expected_sha256=sha)
        require(result["source"]["observed_sha256"] == sha and
                result["document"]["physical_pages"] == count,
                "batch_source_identity_invalid")
        seen = [p["page"] for p in result["pages"]]
        require(seen == pages and not (set(seen) & reviewed_pages),
                "batch_coverage_overlap_or_missing")
        reviewed_pages.update(seen)

        total_tables += result["document"]["tables_detected"]
        total_rows += result["document"]["table_rows_total"]
        total_chunks += result["document"]["all_chunk_count"]
        total_table_chunks += result["document"]["structured_table_chunk_count"]
        total_native_text_pages += result["document"]["native_text_pages"]
        total_no_native_text_pages += result["document"]["no_native_text_pages"]
        require(
            result["document"]["native_text_pages"] +
            result["document"]["no_native_text_pages"] == len(pages),
            "batch_native_text_coverage_incomplete")
        total_legacy_writer_checked += result["document"]["legacy_table_writer_metadata_checked"]
        total_legacy_writer_mismatches += result["document"]["legacy_table_writer_metadata_mismatches"]
        route = result["document"]["router_recommendation"]
        routing_counts[route] = routing_counts.get(route, 0) + 1

        for p in result["pages"]:
            for issue in p["issue_codes"]:
                issue_pages_by_code.setdefault(issue, []).append(p["page"])
        # Zero-table batches are expected in mixed documents; only zero
        # tables across the WHOLE document is a blocker.
        issues = sorted(set(result["issue_codes"]) -
                        {"NO_STRUCTURED_TABLE_DETECTED"})
        all_issues.update(issues)
        batches.append({
            "first_page": pages[0], "last_page": pages[-1],
            "pages_processed": len(pages),
            "tables_detected": result["document"]["tables_detected"],
            "structured_table_chunks":
                result["document"]["structured_table_chunk_count"],
            "native_text_pages": result["document"]["native_text_pages"],
            "no_native_text_pages": result["document"]["no_native_text_pages"],
            "issue_codes": issues,
        })
    require(reviewed_pages == set(range(1, count + 1)),
            "incomplete_document_page_coverage")
    require(total_native_text_pages + total_no_native_text_pages == count,
            "document_native_text_coverage_incomplete")
    if total_tables == 0:
        all_issues.add("NO_STRUCTURED_TABLE_DETECTED")

    return {
        "version": VERSION,
        "audit_mode": "bounded_batches_full_document_coverage",
        "status": ("AUTO_HOLD_UNVERIFIED" if all_issues
                   else "MECHANICAL_CHECKS_PASS_LIMITED"),
        "source": {
            "drive_file_id": drive_file_id,
            "observed_sha256": sha,
            "size_bytes": expected_size,
            "expected_sha256_matched": expected_sha256 is not None,
            "drive_sha_independently_verified": False,
            "official_legal_version_verified": False,
        },
        "document": {
            "physical_pages": count,
            "pages_covered": len(reviewed_pages),
            "coverage_complete": True,
            "batch_size": batch_size,
            "batch_count": len(batches),
            "tables_detected": total_tables,
            "table_rows_total": total_rows,
            "structured_table_chunk_count": total_table_chunks,
            "all_chunk_count": total_chunks,
            "native_text_pages": total_native_text_pages,
            "no_native_text_pages": total_no_native_text_pages,
            "legacy_table_writer_metadata_checked":
                total_legacy_writer_checked,
            "legacy_table_writer_metadata_mismatches":
                total_legacy_writer_mismatches,
            "router_batch_counts": routing_counts,
        },
        "batches": batches,
        "issue_codes": sorted(all_issues),
        "issue_pages_by_code": {
            key: sorted(set(values))
            for key, values in sorted(issue_pages_by_code.items())
        },
        "semantic_table_accuracy": "NOT_MEASURED",
        "db_roundtrip_verified": False,
        "legacy_writer_metadata_preview_only": True,
        "ocr_or_vision_performed": False,
        "database_access": False,
        "external_ai_called": False,
        "production_write": False,
        "drive_write": False,
        "human_review_required": False,
        "notice": ("Full page coverage proves only that every page was "
                   "processed by the native extractor; table values, "
                   "missing cells, OCR quality and legal meaning "
                   "are not independently verified."),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--drive-file-id", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--expected-sha256")
    parser.add_argument(
        "--report-json",
        help="Write machine-readable JSON to this local file, separate from "
             "PDF library stdout notices. Prefer a private temporary path.",
    )
    args = parser.parse_args()
    require(bool(args.drive_file_id.strip()), "drive_file_id_missing")
    result = audit_pdf_batched(
        args.pdf, drive_file_id=args.drive_file_id,
        expected_size=args.expected_size,
        expected_sha256=args.expected_sha256,
    )
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False) + "\n"
    if args.report_json:
        output = Path(args.report_json)
        require(output.parent.is_dir() and
                not output.is_symlink() and
                (not output.exists() or output.is_file()),
                "report_path_refused")
        output.write_text(payload, encoding="utf-8")
        print("REPORT_JSON_WRITTEN")
    else:
        print(payload, end="")


if __name__ == "__main__":
    try:
        main()
    except (IngestAuditRefused, RuntimeError, ValueError) as exc:
        raise SystemExit("INGEST_AUDIT_REFUSED: " + str(exc)) from None
