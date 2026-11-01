#!/usr/bin/env python3
"""Synthetic PDF raster guard regression: never uses user documents or DB."""
import tempfile
from pathlib import Path

import pymupdf

from verify_pdf_blank_pages_v1 import (
    RenderProbeRefused, inspect_rendered_pages,
    sha256_file,
)


def refuses(func, code):
    try:
        func()
    except RenderProbeRefused as exc:
        assert code in str(exc), (code, str(exc))
        return
    raise AssertionError("expected refusal: " + code)


def test_blank_and_visible_pages():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "synthetic.pdf"
        document = pymupdf.open()
        document.new_page(width=400, height=400)  # Pure white
        second = document.new_page(width=400, height=400)
        second.draw_rect(pymupdf.Rect(30, 30, 200, 190),
                         fill=(0, 0, 0), color=(0, 0, 0))
        third = document.new_page(width=400, height=400)
        third.draw_line(pymupdf.Point(30, 30),
                        pymupdf.Point(200, 200),
                        color=(0, 0, 0), width=1)
        document.save(path)
        document.close()
        sha = sha256_file(path)
        size = path.stat().st_size

        def verify(**kwargs):
            return inspect_rendered_pages(
                path, expected_sha256=sha, expected_size=size,
                expected_total_pages=3, first_page=1, last_page=3,
                **kwargs,
            )

        report = verify()
        assert report["status"] == "AUTO_HOLD_RENDERED_NONWHITE"
        assert report["document"]["pages_rendered"] == 3
        assert report["document"]["nonwhite_detected_pages"] == [2, 3]
        assert report["document"]["no_nonwhite_detected_count"] == 1
        assert report["pages"][0]["nonwhite_pixels"] == 0
        assert report["pages"][1]["nonwhite_pixels"] > 0
        assert report["pages"][2]["nonwhite_pixels"] > 0
        assert report["document"]["higher_resolution_render_verified"] is False
        assert report["ocr_performed"] is False
        assert report["database_access"] is False
        assert report["external_ai_called"] is False
        print("test_render_white_black_and_hairline_pages: PASS")

        blank = inspect_rendered_pages(
            path, expected_sha256=sha, expected_size=size,
            expected_total_pages=3, first_page=1, last_page=1,
        )
        assert blank["status"] == "RENDER_NO_NONWHITE_DETECTED_LIMITED"
        assert blank["document"]["pages_rendered"] == 1
        assert blank["document"]["nonwhite_detected_pages"] == []
        assert blank["document"]["independent_pdf_content_semantics_verified"] is False
        print("test_bounded_white_render_limited_status: PASS")

        refuses(
            lambda: inspect_rendered_pages(
                path, expected_sha256="0" * 64, expected_size=size,
                expected_total_pages=3, first_page=1, last_page=1),
            "source_sha256_mismatch",
        )
        refuses(
            lambda: inspect_rendered_pages(
                path, expected_sha256=sha, expected_size=size,
                expected_total_pages=4, first_page=1, last_page=1),
            "document_identity_mismatch",
        )
        refuses(
            lambda: inspect_rendered_pages(
                path, expected_sha256=sha, expected_size=size,
                expected_total_pages=3, first_page=1, last_page=4),
            "render_range_refused",
        )
        print("test_render_source_identity_and_page_bounds: PASS")


if __name__ == "__main__":
    test_blank_and_visible_pages()
    print("PDF RENDER BLANKNESS OFFLINE CONTRACT: PASS")
