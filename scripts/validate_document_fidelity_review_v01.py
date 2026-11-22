#!/usr/bin/env python3
"""G3-B fail-closed evidence manifest validator (offline, no visual/production approval)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ALLOWED_DISPOSITIONS = {
    "STRUCTURED_TABLE_REVIEW_REQUIRED": "STRUCTURED_TABLE_REVIEW_REQUIRED",
    "SAMPLE_PHOTO_PLACEHOLDER_NOT_SITE_EVIDENCE": "SAMPLE_ONLY_NO_SITE_EVIDENCE",
    "GRAPHIC_ARROW_LABELS_ABSENT_FROM_TEXT_MULTIMODAL_REQUIRED": "TEXT_ONLY_SEMANTICS_BLOCKED",
    "GRAPHIC_SPATIAL_RELATION_NOT_PRESERVED_MULTIMODAL_REQUIRED": "TEXT_ONLY_SEMANTICS_BLOCKED",
    "VISUAL_AMENDMENT_HIGHLIGHT_NOT_PRESERVED_TEXT_ONLY": "AMENDMENT_VERSION_CONTEXT_REQUIRED",
    "PROSE_TEXT_ORDER_VISUALLY_REVIEWED": "PROSE_LAYOUT_REVIEWED_EVIDENCE_ONLY",
}

def require(condition, code):
    if not condition:
        raise ValueError("G3B_" + code + "_HOLD")

def validate_review(manifest, pdf_bytes, *, expected_sha256, expected_bytes,
                    expected_pages, expected_source_id, expected_drive_file_id):
    """Validate record binding and review risk flags; NEVER authorize source activation."""
    require(type(manifest) is dict, "MANIFEST_SHAPE")
    require(type(expected_sha256) is str and
            re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None, "EXPECTED_SHA")
    require(type(expected_bytes) is int and expected_bytes > 0, "EXPECTED_BYTES")
    require(type(expected_pages) is int and expected_pages > 0, "EXPECTED_PAGES")
    require(type(expected_source_id) is str and bool(expected_source_id.strip()), "EXPECTED_SOURCE")
    require(type(expected_drive_file_id) is str and bool(expected_drive_file_id.strip()), "EXPECTED_DRIVE_FILE")
    require(manifest.get("document_code") == expected_source_id, "SOURCE_ID_MISMATCH")
    require(manifest.get("file_sha256") == expected_sha256, "MANIFEST_SHA_MISMATCH")
    require(manifest.get("source_file_bytes") == expected_bytes, "MANIFEST_SIZE_MISMATCH")
    require(manifest.get("physical_pdf_pages") == expected_pages, "MANIFEST_PAGES_MISMATCH")
    require(manifest.get("source_drive_file_id") == expected_drive_file_id, "DRIVE_ID_MISMATCH")
    require(type(manifest.get("source_drive_folder_id")) is str and
            bool(manifest["source_drive_folder_id"].strip()), "FOLDER_ID_REQUIRED")
    require(len(pdf_bytes) == expected_bytes, "SOURCE_BYTES_MISMATCH")
    require(pdf_bytes.startswith(b"%PDF-"), "NOT_PDF")
    require(hashlib.sha256(pdf_bytes).hexdigest() == expected_sha256, "SOURCE_SHA_MISMATCH")
    pages, rows = manifest.get("reviewed_physical_pages"), manifest.get("rows")
    require(type(pages) is list and len(pages) > 0, "EMPTY_REVIEW_SCOPE")
    require(all(type(n) is int and 1 <= n <= expected_pages for n in pages), "REVIEW_PAGE_OUT_OF_RANGE")
    require(pages == sorted(set(pages)), "DUPLICATE_OR_UNSORTED_PAGES")
    require(type(rows) is list and len(rows) == len(pages), "ROW_COUNT_MISMATCH")
    require(all(type(row) is dict for row in rows), "ROW_SHAPE")
    require([row.get("physical_pdf_page") for row in rows] == pages, "ROW_PAGE_ID_MISMATCH")
    risks = {}
    for row in rows:
        printed = row.get("printed_page")
        require("printed_page" in row, "PRINTED_PAGE_NOT_RECORDED")
        require(printed is None or (type(printed) is int and printed > 0), "PRINTED_PAGE_INVALID")
        require(type(row.get("section")) is str and bool(row["section"].strip()), "MISSING_SECTION")
        require(type(row.get("observation")) is str and bool(row["observation"].strip()), "MISSING_OBSERVATION")
        disposition = row.get("disposition")
        require(type(disposition) is str and disposition in ALLOWED_DISPOSITIONS,
                "UNSUPPORTED_DISPOSITION")
        require(type(row.get("extracted_text_nonwhitespace_characters")) is int and
                row["extracted_text_nonwhitespace_characters"] >= 0, "TEXT_METRIC")
        require(type(row.get("embedded_pdf_image_xobjects")) is int and
                row["embedded_pdf_image_xobjects"] >= 0, "IMAGE_METRIC")
        risks.setdefault(ALLOWED_DISPOSITIONS[disposition], []).append(row["physical_pdf_page"])
    status = manifest.get("status")
    require(type(status) is str and "FULL_DOCUMENT_REVIEW_REQUIRED" in status,
            "UNSAFE_APPROVAL_STATUS")
    require("G3B_PASS" not in status and "APPROVED" not in status,
            "AUTO_APPROVAL_FORBIDDEN")
    return {
        "source_id": expected_source_id, "sha256": expected_sha256,
        "reviewed_pages": len(pages), "total_physical_pages": expected_pages,
        "full_document_visual_review": False,
        "g3b_status": "EVIDENCE_MANIFEST_VALID_REVIEW_REQUIRED",
        "g3c_status": "LEGAL_CURRENTNESS_NOT_VERIFIED",
        "risk_pages": risks, "citation_page_field": "physical_pdf_page",
        "printed_page_field": "printed_page", "no_auto_registry_or_index": True,
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--expected-pages", type=int, required=True)
    parser.add_argument("--expected-source-id", required=True)
    parser.add_argument("--expected-drive-file-id", required=True)
    args = parser.parse_args(argv)
    require(args.manifest.stat().st_size <= 2_000_000, "MANIFEST_TOO_LARGE")
    require(args.pdf.stat().st_size <= 25_000_000, "PDF_TOO_LARGE")
    with args.manifest.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    with args.pdf.open("rb") as handle:
        data = handle.read(25_000_001)
    outcome = validate_review(
        manifest, data, expected_sha256=args.expected_sha256,
        expected_bytes=args.expected_bytes, expected_pages=args.expected_pages,
        expected_source_id=args.expected_source_id,
        expected_drive_file_id=args.expected_drive_file_id)
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    print("G3B_EVIDENCE_VALIDATION_ONLY; REVIEW_REQUIRED; NO_DRIVE_WRITE; "
          "NO_DB_WRITE; NO_REGISTRY; NO_PRODUCTION")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        print("G3B_HOLD: " + str(error), file=sys.stderr)
        sys.exit(1)
