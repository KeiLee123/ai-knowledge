#!/usr/bin/env python3

import argparse
import hashlib
import json
import mimetypes
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = "document-manifest-v2"
EXTRACTOR_VERSION = "phase-a-2"

OCR_TEXT_CHAR_THRESHOLD = 40

TEXT_TABLE_MIN_WORDS = 150
TEXT_TABLE_MIN_AVG_WORDS_PER_ROW = 12.0
TEXT_TABLE_MIN_X_ANCHORS = 4
TEXT_TABLE_X_ANCHOR_MIN_OCCURRENCES = 5


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def normalize_text(text: str) -> str:
    text = (
        (text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
    ).strip()


def bbox_to_list(rect):
    if rect is None:
        return None

    try:
        values = [
            rect.x0,
            rect.y0,
            rect.x1,
            rect.y1,
        ]

    except AttributeError:
        try:
            values = list(rect)
        except Exception:
            return None

    if len(values) != 4:
        return None

    return [
        round(float(x), 3)
        for x in values
    ]


def safe_cell(value):
    if value is None:
        return ""

    return normalize_text(
        str(value)
    )


def parse_page_spec(spec):
    if not spec:
        return None

    pages = set()

    for token in spec.split(","):
        token = token.strip()

        if not token:
            continue

        if "-" in token:
            start_text, end_text = (
                token.split("-", 1)
            )

            start = int(
                start_text.strip()
            )

            end = int(
                end_text.strip()
            )

            if (
                start < 1
                or end < start
            ):
                raise ValueError(
                    f"Invalid page range: {token}"
                )

            pages.update(
                range(start, end + 1)
            )

        else:
            page_number = int(token)

            if page_number < 1:
                raise ValueError(
                    f"Invalid page number: {token}"
                )

            pages.add(
                page_number
            )

    if not pages:
        raise ValueError(
            "Page selection is empty"
        )

    return sorted(pages)


def is_near_white(fill):
    if fill is None:
        return False

    try:
        values = list(fill)
    except Exception:
        return False

    return (
        bool(values)
        and all(
            float(value) >= 0.95
            for value in values
        )
    )


def summarize_drawings(page):
    try:
        drawings = (
            page.get_drawings()
            or []
        )
    except Exception:
        drawings = []

    meaningful = []

    for drawing in drawings:
        background_only = (
            drawing.get("type") == "f"
            and is_near_white(
                drawing.get("fill")
            )
            and drawing.get("color")
            is None
        )

        if not background_only:
            meaningful.append(
                drawing
            )

    item_count = sum(
        len(
            drawing.get(
                "items",
                [],
            )
        )
        for drawing in meaningful
    )

    return {
        "drawing_count":
            len(drawings),
        "meaningful_drawing_count":
            len(meaningful),
        "meaningful_drawing_item_count":
            item_count,
    }


def text_layout_metrics(page):
    try:
        words = (
            page.get_text(
                "words"
            )
            or []
        )
    except Exception:
        words = []

    if not words:
        return {
            "word_count": 0,
            "visual_row_count": 0,
            "avg_words_per_visual_row":
                0.0,
            "x_anchor_count": 0,
            "text_table_candidate":
                False,
        }

    row_counts = Counter(
        round(
            float(word[1]),
            1,
        )
        for word in words
    )

    x_counts = Counter(
        round(
            float(word[0]),
            1,
        )
        for word in words
    )

    visual_row_count = len(
        row_counts
    )

    avg_words_per_row = (
        len(words)
        / visual_row_count
        if visual_row_count
        else 0.0
    )

    x_anchor_count = sum(
        1
        for count in x_counts.values()
        if (
            count
            >= TEXT_TABLE_X_ANCHOR_MIN_OCCURRENCES
        )
    )

    candidate = (
        len(words)
        >= TEXT_TABLE_MIN_WORDS
        and avg_words_per_row
        >= TEXT_TABLE_MIN_AVG_WORDS_PER_ROW
        and x_anchor_count
        >= TEXT_TABLE_MIN_X_ANCHORS
    )

    return {
        "word_count":
            len(words),
        "visual_row_count":
            visual_row_count,
        "avg_words_per_visual_row":
            round(
                avg_words_per_row,
                3,
            ),
        "x_anchor_count":
            x_anchor_count,
        "text_table_candidate":
            candidate,
    }


def table_to_manifest(
    table,
    table_index,
    strategy,
):
    extracted = (
        table.extract()
        or []
    )

    rows = [
        [
            safe_cell(cell)
            for cell in row
        ]
        for row in extracted
    ]

    column_count = max(
        (
            len(row)
            for row in rows
        ),
        default=0,
    )

    return {
        "table_index":
            table_index,
        "detection_strategy":
            strategy,
        "bbox":
            bbox_to_list(
                getattr(
                    table,
                    "bbox",
                    None,
                )
            ),
        "row_count":
            len(rows),
        "column_count":
            column_count,
        "rows":
            rows,
    }


def extract_pdf_tables(
    page,
    layout_metrics,
):
    tables = []
    errors = []

    if not hasattr(
        page,
        "find_tables",
    ):
        return tables, errors

    try:
        finder = (
            page.find_tables()
        )

        raw_tables = (
            getattr(
                finder,
                "tables",
                finder,
            )
            or []
        )

        for table in raw_tables:
            tables.append(
                table_to_manifest(
                    table,
                    len(tables),
                    "lines",
                )
            )

    except Exception as exc:
        errors.append({
            "strategy":
                "lines",
            "error":
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
        })

    if (
        not tables
        and layout_metrics[
            "text_table_candidate"
        ]
    ):
        try:
            finder = (
                page.find_tables(
                    strategy="text",
                    min_words_vertical=10,
                    min_words_horizontal=3,
                )
            )

            raw_tables = (
                getattr(
                    finder,
                    "tables",
                    finder,
                )
                or []
            )

            for table in raw_tables:
                tables.append(
                    table_to_manifest(
                        table,
                        len(tables),
                        "text",
                    )
                )

        except Exception as exc:
            errors.append({
                "strategy":
                    "text",
                "error":
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
            })

    return tables, errors


def extract_pdf_images(page):
    images = []

    try:
        image_info = (
            page.get_image_info(
                xrefs=True
            )
            or []
        )

    except TypeError:
        image_info = (
            page.get_image_info()
            or []
        )

    except Exception:
        image_info = []

    seen = set()

    for info in image_info:
        xref = info.get(
            "xref"
        )

        bbox = bbox_to_list(
            info.get(
                "bbox"
            )
        )

        dedupe_key = (
            xref,
            tuple(bbox)
            if bbox
            else None,
        )

        if dedupe_key in seen:
            continue

        seen.add(
            dedupe_key
        )

        transform = (
            info.get(
                "transform"
            )
        )

        images.append({
            "asset_index":
                len(images),
            "xref":
                (
                    xref
                    if isinstance(
                        xref,
                        int,
                    )
                    and xref > 0
                    else None
                ),
            "bbox":
                bbox,
            "width":
                info.get(
                    "width"
                ),
            "height":
                info.get(
                    "height"
                ),
            "colorspace":
                (
                    info.get(
                        "cs-name"
                    )
                    or info.get(
                        "colorspace"
                    )
                ),
            "bits_per_component":
                info.get(
                    "bpc"
                ),
            "transform":
                (
                    list(transform)
                    if transform
                    else None
                ),
        })

    if images:
        return images

    try:
        raw_images = (
            page.get_images(
                full=True
            )
            or []
        )

    except Exception:
        raw_images = []

    for image in raw_images:
        xref = (
            image[0]
            if image
            else None
        )

        rects = []

        if xref:
            try:
                rects = (
                    page.get_image_rects(
                        xref
                    )
                    or []
                )

            except Exception:
                rects = []

        if not rects:
            rects = [None]

        for rect in rects:
            images.append({
                "asset_index":
                    len(images),
                "xref":
                    xref,
                "bbox":
                    bbox_to_list(
                        rect
                    ),
                "width":
                    (
                        image[2]
                        if len(image) > 2
                        else None
                    ),
                "height":
                    (
                        image[3]
                        if len(image) > 3
                        else None
                    ),
                "colorspace":
                    None,
                "bits_per_component":
                    (
                        image[4]
                        if len(image) > 4
                        else None
                    ),
                "transform":
                    None,
            })

    return images


def extract_pdf(
    path: Path,
    selected_pages=None,
):
    try:
        import pymupdf

    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required "
            "for PDF extraction"
        ) from exc

    doc = pymupdf.open(
        path
    )

    page_count = len(
        doc
    )

    if selected_pages is None:
        page_numbers = list(
            range(
                1,
                page_count + 1,
            )
        )

    else:
        invalid = [
            page_number
            for page_number
            in selected_pages
            if page_number
            > page_count
        ]

        if invalid:
            raise ValueError(
                "Selected page exceeds "
                f"document page count "
                f"({page_count}): "
                + ", ".join(
                    str(x)
                    for x in invalid
                )
            )

        page_numbers = (
            selected_pages
        )

    units = []

    total_tables = 0
    total_images = 0
    total_text_chars = 0

    ocr_candidates = []
    vector_candidates = []
    visual_candidates = []
    blank_units = []
    text_table_candidate_units = []
    table_units = []

    for page_number in page_numbers:
        page_index = (
            page_number - 1
        )

        page = doc[
            page_index
        ]

        text = normalize_text(
            page.get_text(
                "text"
            )
        )

        layout_metrics = (
            text_layout_metrics(
                page
            )
        )

        drawing_metrics = (
            summarize_drawings(
                page
            )
        )

        tables, table_errors = (
            extract_pdf_tables(
                page,
                layout_metrics,
            )
        )

        images = (
            extract_pdf_images(
                page
            )
        )

        total_text_chars += (
            len(text)
        )

        total_tables += (
            len(tables)
        )

        total_images += (
            len(images)
        )

        low_text = (
            len(
                text.strip()
            )
            < OCR_TEXT_CHAR_THRESHOLD
        )

        has_images = bool(
            images
        )

        has_vector_content = (
            drawing_metrics[
                "meaningful_drawing_count"
            ]
            > 0
        )

        blank = (
            not text.strip()
            and not has_images
            and not has_vector_content
        )

        ocr_candidate = (
            low_text
            and has_images
        )

        vector_candidate = (
            low_text
            and has_vector_content
            and not has_images
        )

        visual_candidate = (
            has_images
            or has_vector_content
        )

        if ocr_candidate:
            ocr_candidates.append(
                page_number
            )

        if vector_candidate:
            vector_candidates.append(
                page_number
            )

        if visual_candidate:
            visual_candidates.append(
                page_number
            )

        if blank:
            blank_units.append(
                page_number
            )

        if layout_metrics[
            "text_table_candidate"
        ]:
            text_table_candidate_units.append(
                page_number
            )

        if tables:
            table_units.append(
                page_number
            )

        units.append({
            "unit_index":
                page_index,
            "unit_type":
                "page",
            "page_number":
                page_number,
            "width":
                round(
                    float(
                        page.rect.width
                    ),
                    3,
                ),
            "height":
                round(
                    float(
                        page.rect.height
                    ),
                    3,
                ),
            "text":
                text,
            "text_chars":
                len(text),
            "layout_metrics":
                layout_metrics,
            "vector_metrics":
                drawing_metrics,
            "tables":
                tables,
            "table_extraction_errors":
                table_errors,
            "images":
                images,
            "blank":
                blank,
            "ocr_candidate":
                ocr_candidate,
            "vector_candidate":
                vector_candidate,
            "visual_candidate":
                visual_candidate,
        })

    return {
        "document_kind":
            "pdf",
        "page_count":
            page_count,
        "selected_pages":
            (
                page_numbers
                if selected_pages
                is not None
                else None
            ),
        "units":
            units,
        "summary": {
            "unit_count":
                len(units),
            "total_text_chars":
                total_text_chars,
            "total_tables":
                total_tables,
            "total_images":
                total_images,
            "ocr_candidate_units":
                ocr_candidates,
            "vector_candidate_units":
                vector_candidates,
            "visual_candidate_units":
                visual_candidates,
            "blank_units":
                blank_units,
            "text_table_candidate_units":
                text_table_candidate_units,
            "table_units":
                table_units,
        },
        "extraction": {
            "text_extractor":
                "pymupdf",
            "table_extractor":
                (
                    "pymupdf.find_tables"
                    " lines + gated text fallback"
                ),
            "image_extractor":
                "pymupdf.image-info",
            "vector_extractor":
                "pymupdf.get_drawings",
        },
    }


def extract_docx(
    path: Path,
):
    try:
        from docx import (
            Document
        )

    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required "
            "for DOCX extraction"
        ) from exc

    doc = Document(
        path
    )

    paragraphs = []

    for index, paragraph in enumerate(
        doc.paragraphs
    ):
        text = normalize_text(
            paragraph.text
        )

        if not text:
            continue

        paragraphs.append({
            "paragraph_index":
                index,
            "style":
                (
                    paragraph.style.name
                    if paragraph.style
                    else None
                ),
            "text":
                text,
        })

    tables = []

    for table_index, table in enumerate(
        doc.tables
    ):
        rows = []

        for row in table.rows:
            rows.append([
                normalize_text(
                    cell.text
                )
                for cell
                in row.cells
            ])

        column_count = max(
            (
                len(row)
                for row in rows
            ),
            default=0,
        )

        tables.append({
            "table_index":
                table_index,
            "detection_strategy":
                "docx-structure",
            "bbox":
                None,
            "row_count":
                len(rows),
            "column_count":
                column_count,
            "rows":
                rows,
        })

    images = []
    rel_seen = set()

    for rel_id, rel in (
        doc.part.rels.items()
    ):
        target = getattr(
            rel,
            "target_part",
            None,
        )

        content_type = getattr(
            target,
            "content_type",
            None,
        )

        if (
            content_type
            and content_type.startswith(
                "image/"
            )
        ):
            if rel_id in rel_seen:
                continue

            rel_seen.add(
                rel_id
            )

            partname = str(
                getattr(
                    target,
                    "partname",
                    "",
                )
            )

            images.append({
                "asset_index":
                    len(images),
                "relationship_id":
                    rel_id,
                "partname":
                    partname or None,
                "content_type":
                    content_type,
                "bbox":
                    None,
                "width":
                    None,
                "height":
                    None,
            })

    text = "\n\n".join(
        item["text"]
        for item in paragraphs
    )

    low_text = (
        len(
            text.strip()
        )
        < OCR_TEXT_CHAR_THRESHOLD
    )

    ocr_candidate = (
        low_text
        and bool(images)
    )

    blank = (
        not text.strip()
        and not images
        and not tables
    )

    unit = {
        "unit_index": 0,
        "unit_type":
            "document",
        "page_number":
            None,
        "text":
            text,
        "text_chars":
            len(text),
        "paragraphs":
            paragraphs,
        "tables":
            tables,
        "images":
            images,
        "blank":
            blank,
        "ocr_candidate":
            ocr_candidate,
        "vector_candidate":
            False,
        "visual_candidate":
            bool(images),
    }

    return {
        "document_kind":
            "docx",
        "page_count":
            None,
        "selected_pages":
            None,
        "units":
            [unit],
        "summary": {
            "unit_count": 1,
            "total_text_chars":
                len(text),
            "total_tables":
                len(tables),
            "total_images":
                len(images),
            "ocr_candidate_units":
                (
                    [0]
                    if ocr_candidate
                    else []
                ),
            "vector_candidate_units":
                [],
            "visual_candidate_units":
                (
                    [0]
                    if images
                    else []
                ),
            "blank_units":
                (
                    [0]
                    if blank
                    else []
                ),
            "text_table_candidate_units":
                [],
            "table_units":
                (
                    [0]
                    if tables
                    else []
                ),
        },
        "extraction": {
            "text_extractor":
                "python-docx",
            "table_extractor":
                "python-docx",
            "image_extractor":
                (
                    "python-docx."
                    "relationships"
                ),
            "vector_extractor":
                None,
        },
    }


def extract_plain_text(
    path: Path,
):
    text = normalize_text(
        path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    )

    blank = (
        not text.strip()
    )

    unit = {
        "unit_index": 0,
        "unit_type":
            "document",
        "page_number":
            None,
        "text":
            text,
        "text_chars":
            len(text),
        "tables":
            [],
        "images":
            [],
        "blank":
            blank,
        "ocr_candidate":
            False,
        "vector_candidate":
            False,
        "visual_candidate":
            False,
    }

    return {
        "document_kind":
            path.suffix.lower().lstrip(
                "."
            ),
        "page_count":
            None,
        "selected_pages":
            None,
        "units":
            [unit],
        "summary": {
            "unit_count": 1,
            "total_text_chars":
                len(text),
            "total_tables": 0,
            "total_images": 0,
            "ocr_candidate_units":
                [],
            "vector_candidate_units":
                [],
            "visual_candidate_units":
                [],
            "blank_units":
                (
                    [0]
                    if blank
                    else []
                ),
            "text_table_candidate_units":
                [],
            "table_units":
                [],
        },
        "extraction": {
            "text_extractor":
                "python.text",
            "table_extractor":
                None,
            "image_extractor":
                None,
            "vector_extractor":
                None,
        },
    }


def build_manifest(
    path: Path,
    selected_pages=None,
):
    suffix = (
        path.suffix.lower()
    )

    if suffix == ".pdf":
        extracted = extract_pdf(
            path,
            selected_pages=
                selected_pages,
        )

    elif suffix == ".docx":
        if selected_pages:
            raise RuntimeError(
                "--pages is only "
                "supported for PDF"
            )

        extracted = (
            extract_docx(
                path
            )
        )

    elif suffix in {
        ".txt",
        ".md",
    }:
        if selected_pages:
            raise RuntimeError(
                "--pages is only "
                "supported for PDF"
            )

        extracted = (
            extract_plain_text(
                path
            )
        )

    else:
        raise RuntimeError(
            "Unsupported file type: "
            + (
                suffix
                or "<none>"
            )
        )

    mime_type, _ = (
        mimetypes.guess_type(
            path.name
        )
    )

    return {
        "schema_version":
            SCHEMA_VERSION,
        "extractor_version":
            EXTRACTOR_VERSION,
        "source": {
            "filename":
                path.name,
            "suffix":
                suffix,
            "mime_type":
                mime_type,
            "size_bytes":
                path.stat().st_size,
            "sha256":
                sha256_file(
                    path
                ),
        },
        "document": {
            "kind":
                extracted[
                    "document_kind"
                ],
            "page_count":
                extracted[
                    "page_count"
                ],
        },
        "selection": {
            "page_numbers":
                extracted.get(
                    "selected_pages"
                ),
        },
        "units":
            extracted[
                "units"
            ],
        "summary":
            extracted[
                "summary"
            ],
        "extraction": {
            **extracted[
                "extraction"
            ],
            "ocr_performed":
                False,
            "vision_model_used":
                False,
            "database_write_performed":
                False,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase A canonical document "
            "extractor. Reads a file and "
            "emits a structured JSON "
            "manifest. No OCR, AI calls, "
            "embeddings, or database writes "
            "are performed."
        )
    )

    parser.add_argument(
        "file",
        help=(
            "PDF, DOCX, TXT or MD file"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Write JSON manifest to this "
            "path instead of stdout"
        ),
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help=(
            "Emit compact JSON instead of "
            "pretty-printed JSON"
        ),
    )

    parser.add_argument(
        "--pages",
        help=(
            "PDF page selection for "
            "diagnostics, e.g. "
            "'1,2,149-152'. "
            "Omit to extract all pages."
        ),
    )

    args = parser.parse_args()

    path = Path(
        args.file
    )

    if not path.exists():
        raise SystemExit(
            f"File not found: {path}"
        )

    if not path.is_file():
        raise SystemExit(
            f"Not a file: {path}"
        )

    try:
        selected_pages = (
            parse_page_spec(
                args.pages
            )
            if args.pages
            else None
        )

        manifest = (
            build_manifest(
                path,
                selected_pages=
                    selected_pages,
            )
        )

    except Exception as exc:
        raise SystemExit(
            "Extraction failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    if args.compact:
        payload = json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    else:
        payload = json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        )

    if args.output:
        output = Path(
            args.output
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            payload + "\n",
            encoding="utf-8",
        )

        print(
            output
        )

    else:
        print(
            payload
        )


if __name__ == "__main__":
    main()
