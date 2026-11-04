"""Docling PDF result to the existing document-manifest-v2 shape.

Only native-text PDFs with single-page item provenance and simple rectangular
tables qualify. Missing or ambiguous evidence raises ContractGap. Coordinates
are converted to PDF points, top-left origin, [x0, y0, x1, y1].
"""

import math
from pathlib import Path

from extract_document_v2 import SCHEMA_VERSION, normalize_text
from phase_b_shadow import CONFIG_VERSION
from phase_b_shadow.contract import ContractGap, Fixture, MAX_PDF_BYTES, MAX_PDF_PAGES

TEXT_LABELS = {"text", "paragraph", "title", "section_header", "list_item", "caption", "footnote", "page_header", "page_footer", "code", "formula"}


def _origin(bbox):
    value = getattr(bbox, "coord_origin", None)
    return getattr(value, "value", value)


def _bbox(bbox, width: float, height: float) -> list[float]:
    if bbox is None:
        raise ContractGap("missing bounding box")
    try:
        l, t, r, b = (float(getattr(bbox, field)) for field in ("l", "t", "r", "b"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractGap("invalid bounding box") from exc
    origin = _origin(bbox)
    if origin == "BOTTOMLEFT":
        t, b = height - t, height - b
    elif origin != "TOPLEFT":
        raise ContractGap("unknown coordinate origin")
    if not all(math.isfinite(v) for v in (l, t, r, b)) or not (0 <= l < r <= width and 0 <= t < b <= height):
        raise ContractGap("bounding box outside physical page")
    return [round(v, 3) for v in (l, t, r, b)]


def _table(item, page: dict, index: int) -> dict:
    data = getattr(item, "data", None)
    rows_count = getattr(data, "num_rows", None)
    cols_count = getattr(data, "num_cols", None)
    cells = getattr(data, "table_cells", None)
    orientation = getattr(getattr(data, "orientation", "rot_0"), "value", getattr(data, "orientation", "rot_0"))
    if orientation != "rot_0":
        raise ContractGap("rotated table cannot be represented by the v2 rows contract")
    if not isinstance(rows_count, int) or not isinstance(cols_count, int) or rows_count < 1 or cols_count < 1 or not isinstance(cells, list):
        raise ContractGap("missing table dimensions or cells")
    if rows_count * cols_count > 10000:
        raise ContractGap("table exceeds Phase B cell bound")
    rows = [[None] * cols_count for _ in range(rows_count)]
    evidence = []
    for cell in cells:
        row = getattr(cell, "start_row_offset_idx", None)
        col = getattr(cell, "start_col_offset_idx", None)
        if (not isinstance(row, int) or not isinstance(col, int) or not (0 <= row < rows_count)
                or not (0 <= col < cols_count) or getattr(cell, "row_span", 1) != 1
                or getattr(cell, "col_span", 1) != 1
                or getattr(cell, "end_row_offset_idx", None) != row + 1
                or getattr(cell, "end_col_offset_idx", None) != col + 1
                or rows[row][col] is not None):
            raise ContractGap("table span, offset or duplicate cell cannot be represented")
        value = getattr(cell, "text", None)
        if not isinstance(value, str):
            raise ContractGap("missing table cell text")
        box = _bbox(getattr(cell, "bbox", None), page["width"], page["height"])
        rows[row][col] = normalize_text(value)
        evidence.append({"row": row, "column": col, "bbox": box})
    if any(value is None for row in rows for value in row):
        raise ContractGap("incomplete table grid")
    return {"table_index": index, "detection_strategy": "docling-table-structure",
            "bbox": page["item_bbox"], "row_count": rows_count, "column_count": cols_count,
            "rows": rows, "cell_provenance": evidence,
            "bbox_coordinate_system": "pdf_points_top_left"}


def build_manifest(doc, fixture: Fixture, source: Path, parser_version: str, model_version: str,
                   model_bundle_sha256: str | None = None) -> dict:
    if not parser_version or not model_version:
        raise ContractGap("parser/model version is missing")
    pages = getattr(doc, "pages", None)
    if not isinstance(pages, dict) or not pages or len(pages) > 10:
        raise ContractGap("missing or excessive physical pages")
    if set(pages) != set(range(1, len(pages) + 1)):
        raise ContractGap("physical page sequence is incomplete")
    # A contiguous Docling page dictionary can still omit the PDF's last page.
    # Compare against the independently opened, SHA-pinned original bytes.
    try:
        import pymupdf
        with pymupdf.open(source) as original_pdf:
            source_page_count = len(original_pdf)
    except Exception as exc:
        raise ContractGap("source PDF page count could not be verified") from exc
    if source_page_count != len(pages):
        raise ContractGap("Docling page count differs from source PDF")
    units = {}
    for number, page in pages.items():
        size = getattr(page, "size", None)
        width, height = getattr(size, "width", None), getattr(size, "height", None)
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or width <= 0 or height <= 0:
            raise ContractGap("missing physical page geometry")
        units[number] = {"unit_index": number - 1, "unit_type": "page", "page_number": number,
                         "width": float(width), "height": float(height), "text": "", "text_chars": 0,
                         "tables": [], "images": [], "ocr_candidate": False, "vector_candidate": False,
                         "visual_candidate": False, "reading_order": [], "provenance": [],
                         "bbox_coordinate_system": "pdf_points_top_left"}
    for order, pair in enumerate(doc.iterate_items()):
        item = pair[0] if isinstance(pair, tuple) else pair
        label = getattr(getattr(item, "label", None), "value", getattr(item, "label", None))
        if label not in TEXT_LABELS and label != "table":
            raise ContractGap(f"unsupported evidence item: {label!r}")
        prov = getattr(item, "prov", None)
        if not isinstance(prov, list) or len(prov) != 1:
            raise ContractGap("item lacks unambiguous single-page provenance")
        page_no = getattr(prov[0], "page_no", None)
        if page_no not in units:
            raise ContractGap("item physical page is unavailable")
        unit = units[page_no]
        box = _bbox(getattr(prov[0], "bbox", None), unit["width"], unit["height"])
        unit["item_bbox"] = box
        unit["reading_order"].append({"order": order, "label": label, "bbox": box})
        unit["provenance"].append({"order": order, "page_number": page_no, "bbox": box, "origin": "docling_native_pdf"})
        if label == "table":
            unit["tables"].append(_table(item, unit, len(unit["tables"])))
        else:
            value = getattr(item, "text", None)
            if not isinstance(value, str) or not normalize_text(value):
                raise ContractGap("text item has no usable text")
            unit["text"] += ("\n" if unit["text"] else "") + normalize_text(value)
        del unit["item_bbox"]
    ordered = [units[n] for n in sorted(units)]
    for unit in ordered:
        unit["text_chars"] = len(unit["text"])
        unit["blank"] = not unit["text"] and not unit["tables"]
        if unit["blank"]:
            raise ContractGap(f"page {unit['page_number']} has no verified text/table evidence")
    table_pages = [u["page_number"] for u in ordered if u["tables"]]
    return {"schema_version": SCHEMA_VERSION, "extractor_version": "docling-shadow-v1",
            "source": {"filename": fixture.filename, "suffix": ".pdf", "mime_type": "application/pdf",
                       "size_bytes": source.stat().st_size, "sha256": fixture.sha256,
                       "source_id": fixture.source_id, "version_id": fixture.version_id},
            "document": {"kind": "pdf", "page_count": len(ordered), "identity": fixture.source_id,
                         "version_id": fixture.version_id},
            "selection": {"page_numbers": None}, "units": ordered,
            "summary": {"unit_count": len(ordered), "total_text_chars": sum(u["text_chars"] for u in ordered),
                        "total_tables": sum(len(u["tables"]) for u in ordered), "total_images": 0,
                        "ocr_candidate_units": [], "vector_candidate_units": [], "visual_candidate_units": [],
                        "blank_units": [], "text_table_candidate_units": [], "table_units": table_pages},
            "extraction": {"text_extractor": "docling", "table_extractor": "docling-table-structure",
                           "image_extractor": None, "vector_extractor": None, "ocr_performed": False,
                           "vision_model_used": False, "database_write_performed": False,
                           "parser_version": parser_version, "model_version": model_version,
                           "model_bundle_sha256": model_bundle_sha256,
                           "config_version": CONFIG_VERSION},
            "compatibility": {"status": "READY_SHADOW", "database_write_allowed": False,
                              "bbox_coordinate_system": "pdf_points_top_left"}}


def convert_pdf(source: Path, model_dir: Path):
    if not model_dir.is_dir() or not any(model_dir.iterdir()):
        raise ContractGap("offline Docling model directory is absent or empty")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(artifacts_path=model_dir, document_timeout=120,
                                 enable_remote_services=False, allow_external_plugins=False,
                                 do_ocr=False, do_table_structure=True, generate_page_images=False,
                                 generate_picture_images=False,
                                 accelerator_options=AcceleratorOptions(num_threads=1, device=AcceleratorDevice.CPU))
    try:
        result = DocumentConverter(allowed_formats=[InputFormat.PDF],
                                   format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}).convert(
                                       source, max_num_pages=MAX_PDF_PAGES,
                                       max_file_size=MAX_PDF_BYTES)
    except OSError:
        raise
    except Exception as exc:
        raise ContractGap(f"Docling conversion failed: {type(exc).__name__}") from exc
    if getattr(getattr(result, "status", None), "value", None) != "success":
        raise ContractGap("Docling conversion is not complete success")
    return result.document
