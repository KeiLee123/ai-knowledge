#!/usr/bin/env python3
"""Synthetic offline G3-A PDF-page coverage checks; no network, no Drive writes."""
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import pnbi_g3a_readonly_quality_probe_v1 as g3


class G3AReadOnlyTests(unittest.TestCase):
    def test_exact_original_matches(self):
        payload = b"%PDF-testdata"
        expected = (hashlib.sha256(payload).hexdigest(), len(payload), 2)
        with patch.dict(g3.EXPECTED, {1: expected}):
            g3.verify_exact_original(1, payload)

    def test_wrong_size_holds(self):
        with self.assertRaisesRegex(ValueError, "BYTE_COUNT_MISMATCH"):
            g3.verify_exact_original(1, b"%PDF-bad")

    def test_wrong_hash_holds(self):
        original = b"%PDF-original"
        corrupted = b"%PDF-corrupt!"
        self.assertEqual(len(original), len(corrupted))
        expected = (hashlib.sha256(original).hexdigest(), len(original), 1)
        with patch.dict(g3.EXPECTED, {1: expected}):
            with self.assertRaisesRegex(ValueError, "SHA256_MISMATCH"):
                g3.verify_exact_original(1, corrupted)

    def test_fake_pdf_header_holds(self):
        payload = b"fake-pdf"
        expected = (hashlib.sha256(payload).hexdigest(), len(payload), 1)
        with patch.dict(g3.EXPECTED, {1: expected}):
            with self.assertRaisesRegex(ValueError, "NOT_PDF"):
                g3.verify_exact_original(1, payload)

    def test_poppler_form_feed_trailing_empty(self):
        self.assertEqual(g3.split_extracted_pages("page1\fpage2\f", 2),
                         ["page1", "page2"])

    def test_poppler_form_feed_trailing_newline(self):
        self.assertEqual(g3.split_extracted_pages("page1\fpage2\f\n", 2),
                         ["page1", "page2"])

    def test_poppler_form_feed_no_trailing(self):
        self.assertEqual(g3.split_extracted_pages("page1\fpage2", 2),
                         ["page1", "page2"])

    def test_poppler_page_count_mismatch_holds(self):
        with self.assertRaisesRegex(ValueError, "PAGE_COUNT_MISMATCH"):
            g3.split_extracted_pages("page1\fpage2", 4)

    def test_zeros_and_low_text_are_review_flags(self):
        result = g3.page_metrics(["", "  \t\n ", "Short", "Long text " * 10])
        self.assertEqual(result["zero"], [1, 2])
        self.assertEqual(result["low"], [3])
        self.assertEqual(result["nonempty"], 2)
        self.assertEqual(result["counts"][2], 5)

    def test_no_false_positive_for_whitespace(self):
        self.assertEqual(g3.page_metrics(["\n\f  "])["zero"], [1])

    def test_complete_pdf_and_text_identity(self):
        data = b"%PDF-valid-test"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 2)
        with patch.dict(g3.EXPECTED, {1: expected}), \
             patch.object(g3.g1, "run_poppler", side_effect=[
                 "Encrypted: no\nPages: 2\n", "Official PNBI-1 document\fContent for page two\f"]):
            result = g3.inspect(1, data)
        self.assertEqual(result["number"], 1)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["nonempty"], 2)

    def test_physical_page_count_changed_holds(self):
        data = b"%PDF-valid-test"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 3)
        with patch.dict(g3.EXPECTED, {1: expected}), \
             patch.object(g3.g1, "run_poppler", return_value="Encrypted: no\nPages: 2\n"):
            with self.assertRaisesRegex(ValueError, "PHYSICAL_PAGE_COUNT_CHANGED"):
                g3.inspect(1, data)

    def test_wrong_doc_identity_holds(self):
        data = b"%PDF-valid-test"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 2)
        with patch.dict(g3.EXPECTED, {1: expected}), \
             patch.object(g3.g1, "run_poppler", side_effect=[
                 "Encrypted: no\nPages: 2\n", "PNBI-10 document\fMore text\f"]):
            with self.assertRaisesRegex(ValueError, "SOURCE_ID_TEXT_UNVERIFIED"):
                g3.inspect(1, data)

    def test_encrypted_pdf_holds(self):
        data = b"%PDF-valid-test"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 2)
        with patch.dict(g3.EXPECTED, {1: expected}), \
             patch.object(g3.g1, "run_poppler", return_value="Encrypted: yes\nPages: 2\n"):
            with self.assertRaisesRegex(ValueError, "ENCRYPTED"):
                g3.inspect(1, data)

    def test_out_of_scope_holds(self):
        with self.assertRaisesRegex(ValueError, "NOT_APPROVED_PNBI"):
            g3.inspect(11, b"%PDF-original")


if __name__ == "__main__":
    unittest.main()
