#!/usr/bin/env python3
"""Read-only bounded raster check of PDF pages already flagged blank by Document v2.

A white render at 72 DPI is NOT proof of semantic emptiness, native-text
accuracy, or completeness at higher resolution. Never writes to a database.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

VERSION = "pdf-blank-render-probe-v1"
MAX_FILE_BYTES = 20_000_000
MAX_DOCUMENT_PAGES = 500
MAX_RENDER_PAGES = 150
MAX_PAGE_PIXELS = 2_000_000


class RenderProbeRefused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise RenderProbeRefused(reason)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def inspect_rendered_pages(path, *, expected_sha256, expected_size,
                           expected_total_pages, first_page, last_page):
    import pymupdf

    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "source_path_refused")
    require(type(expected_size) is int and 100 <= expected_size <= MAX_FILE_BYTES,
            "file_size_limit_refused")
    require(path.stat().st_size == expected_size, "source_size_mismatch")
    require(type(expected_sha256) is str
            and len(expected_sha256) == 64
            and all(ch in "0123456789abcdef" for ch in expected_sha256),
            "expected_sha256_invalid")
    actual_sha256 = sha256_file(path)
    require(actual_sha256 == expected_sha256, "source_sha256_mismatch")
    require(type(expected_total_pages) is int
            and 0 < expected_total_pages <= MAX_DOCUMENT_PAGES,
            "total_page_count_invalid")
    require(type(first_page) is int and type(last_page) is int
            and 1 <= first_page <= last_page <= expected_total_pages
            and last_page - first_page + 1 <= MAX_RENDER_PAGES,
            "render_range_refused")

    results = []
    nonwhite_pages = []
    with pymupdf.open(path) as doc:
        require(doc.is_pdf and doc.page_count == expected_total_pages,
                "document_identity_mismatch")
        for n in range(first_page, last_page + 1):
            page = doc.load_page(n - 1)
            rect = page.rect
            require(all(math.isfinite(z) for z in
                        (rect.width, rect.height))
                    and rect.width > 0 and rect.height > 0
                    and math.ceil(rect.width) * math.ceil(rect.height)
                    <= MAX_PAGE_PIXELS,
                    "page_render_pixel_limit_refused")
            pix = page.get_pixmap(
                matrix=pymupdf.Matrix(1.0, 1.0),
                colorspace=pymupdf.csGRAY,
                alpha=False,
                annots=True,
            )
            require(pix.n == 1 and pix.alpha == 0
                    and pix.width * pix.height <= MAX_PAGE_PIXELS
                    and pix.stride == pix.width,
                    "unexpected_render_format")
            samples = pix.samples
            require(len(samples) == pix.width * pix.height,
                    "unexpected_render_buffer_size")
            # Every pixel darker than pure white is treated as potentially
            # visible; no approximate threshold or content is suppressed.
            nonwhite = len(samples) - samples.count(255)
            if nonwhite:
                nonwhite_pages.append(n)
            results.append({
                "page": n,
                "nonwhite_pixels": nonwhite,
                "pixel_count": len(samples),
            })

    require(len(results) == last_page - first_page + 1
            and [x["page"] for x in results]
            == list(range(first_page, last_page + 1)),
            "incomplete_render_page_coverage")
    return {
        "version": VERSION,
        "status": ("AUTO_HOLD_RENDERED_NONWHITE"
                   if nonwhite_pages
                   else "RENDER_NO_NONWHITE_DETECTED_LIMITED"),
        "scope": "requested_page_range_only_not_entire_document",
        "document": {
            "source_sha256": actual_sha256,
            "source_size_bytes": expected_size,
            "physical_pages": expected_total_pages,
            "first_page": first_page,
            "last_page": last_page,
            "pages_rendered": len(results),
            "rendered_page_count_expected": last_page - first_page + 1,
            "render_scale": 1.0,
            "render_dpi": 72,
            "grayscale": True,
            "annotations_rendered": True,
            "nonwhite_detected_pages": nonwhite_pages,
            "no_nonwhite_detected_count": len(results) - len(nonwhite_pages),
            "all_rendered_pages_have_no_nonwhite": not bool(nonwhite_pages),
            "higher_resolution_render_verified": False,
            "independent_pdf_content_semantics_verified": False,
        },
        "pages": results,
        "external_ai_called": False,
        "ocr_performed": False,
        "database_access": False,
        "production_write": False,
        "drive_write": False,
        "notice": (
            "A 72-DPI fully white render is a bounded raster observation, "
            "not proof of absent annotations, hidden layers, page content "
            "or higher-resolution fine details. No semantic accuracy claim."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-total-pages", type=int, required=True)
    parser.add_argument("--first-page", type=int, required=True)
    parser.add_argument("--last-page", type=int, required=True)
    parser.add_argument("--report-json", required=True)
    a = parser.parse_args()

    # Report goes only to an existing private temporary directory.
    out = Path(a.report_json)
    require(out.parent.is_dir() and not out.is_symlink()
            and not out.exists(), "report_path_refused")
    result = inspect_rendered_pages(
        a.pdf, expected_sha256=a.expected_sha256,
        expected_size=a.expected_size,
        expected_total_pages=a.expected_total_pages,
        first_page=a.first_page, last_page=a.last_page,
    )
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print("RENDER_REPORT_JSON_WRITTEN")


if __name__ == "__main__":
    try:
        main()
    except (RenderProbeRefused, RuntimeError, ValueError) as err:
        raise SystemExit("RENDER_PROBE_REFUSED: " + str(err)) from None
