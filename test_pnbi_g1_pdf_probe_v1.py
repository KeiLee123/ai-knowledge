#!/usr/bin/env python3
"""Offline G1 negative-contract tests; no network, no local PDF writes."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import pnbi_g1_pdf_probe_v1 as g1


class Header:
    def __init__(self, content_type, length=None):
        self.content_type = content_type
        self.length = length

    def get_content_type(self):
        return self.content_type

    def get(self, key):
        return self.length if key == "Content-Length" else None


class Response:
    def __init__(self, url, payload, content_type, length=None):
        self.url, self.payload, self.headers = url, payload, Header(content_type, length)

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, max_size):
        return self.payload[:max_size]


class Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout=None):
        return self.response


URL = "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/signed/PNBI001se.pdf"
PDF = b"%PDF-1.7\n%%EOF\n"


class G1Tests(unittest.TestCase):
    def test_valid_header_download(self):
        self.assertEqual(g1.fetch_pdf(Opener(Response(URL, PDF, "application/pdf", str(len(PDF)))), URL), PDF)

    def test_reject_redirect(self):
        with self.assertRaisesRegex(ValueError, "PDF_REDIRECT"):
            g1.fetch_pdf(Opener(Response("https://evil.example/file.pdf", PDF, "application/pdf")), URL)

    def test_reject_non_pdf_mime(self):
        with self.assertRaisesRegex(ValueError, "PDF_MIME"):
            g1.fetch_pdf(Opener(Response(URL, PDF, "text/html")), URL)

    def test_reject_fake_header(self):
        with self.assertRaisesRegex(ValueError, "NOT_PDF_HEADER"):
            g1.fetch_pdf(Opener(Response(URL, b"%Bad", "application/pdf")), URL)

    def test_reject_length_mismatch(self):
        with self.assertRaisesRegex(ValueError, "LENGTH_MISMATCH"):
            g1.fetch_pdf(Opener(Response(URL, PDF, "application/pdf", str(len(PDF) + 1))), URL)

    def test_reject_oversize(self):
        with patch.object(g1, "MAX_PDF_BYTES", 5):
            with self.assertRaisesRegex(ValueError, "PDF_ACTUAL_SIZE"):
                g1.fetch_pdf(Opener(Response(URL, PDF, "application/pdf")), URL)

    def test_pdfinfo_normal(self):
        self.assertEqual(g1.pdf_page_count("Encrypted: no\nPages: 6\n"), 6)

    def test_pdfinfo_encrypted(self):
        with self.assertRaisesRegex(ValueError, "ENCRYPTED"):
            g1.pdf_page_count("Encrypted: yes (print:yes)\nPages: 6\n")

    def test_pdfinfo_missing_pages(self):
        with self.assertRaisesRegex(ValueError, "NO_PAGES"):
            g1.pdf_page_count("Encrypted: no\n")

    def test_pdfinfo_zero_pages(self):
        with self.assertRaisesRegex(ValueError, "INVALID_PAGE_COUNT"):
            g1.pdf_page_count("Encrypted: no\nPages: 0\n")

    def test_source_id_positive(self):
        g1.validate_document_id("Practice Note PNBI-1, mandatory building", 1)
        g1.validate_document_id("PNBI 01", 1)
        g1.validate_document_id("PNBI—10", 10)

    def test_source_id_wrong_number(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_ID_TEXT_UNVERIFIED"):
            g1.validate_document_id("PNBI-10", 1)

    def test_source_id_absent_hold(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_ID_TEXT_UNVERIFIED"):
            g1.validate_document_id("scanned signature no OCR", 1)

    def test_source_id_unicode_spaces(self):
        g1.validate_document_id("PNBI\n–\n2", 2)

    def test_aggregate_failure_not_pass(self):
        with patch.object(g1, "fetch_official_index", return_value={1: URL}), \
             patch.object(g1, "fetch_pdf", return_value=PDF), \
             patch.object(g1, "run_poppler", side_effect=["Pages: 4\nEncrypted: no\n", "PNBI-2"]):
            with self.assertRaisesRegex(ValueError, "SOURCE_ID_TEXT_UNVERIFIED"):
                g1.inspect_one(1, opener=object())


if __name__ == "__main__":
    unittest.main()
