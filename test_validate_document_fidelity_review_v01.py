#!/usr/bin/env python3
"""G3-B evidence contract: 20 synthetic offline fail-closed regression cases."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent/"scripts"))
import validate_document_fidelity_review_v01 as gate

class FidelityTests(unittest.TestCase):
    def setUp(self):
        self.pdf=b"%PDF-1.7\nsample source\n"
        self.sha=hashlib.sha256(self.pdf).hexdigest()
        self.manifest={
            "document_code":"BD_PNBI_07","file_sha256":self.sha,
            "source_file_bytes":len(self.pdf),"physical_pdf_pages":73,
            "source_drive_file_id":"stable-id","source_drive_folder_id":"folder-id",
            "reviewed_physical_pages":[44,51,67],
            "status":"G3B_SAMPLE_COMPLETE; FULL_DOCUMENT_REVIEW_REQUIRED",
            "rows":[
                {"physical_pdf_page":44,"printed_page":11,"section":"Form 1",
                 "disposition":"STRUCTURED_TABLE_REVIEW_REQUIRED",
                 "observation":"Nested columns","extracted_text_nonwhitespace_characters":1049,
                 "embedded_pdf_image_xobjects":0},
                {"physical_pdf_page":51,"printed_page":18,"section":"Photo E001",
                 "disposition":"SAMPLE_PHOTO_PLACEHOLDER_NOT_SITE_EVIDENCE",
                 "observation":"Sample photo only","extracted_text_nonwhitespace_characters":189,
                 "embedded_pdf_image_xobjects":2},
                {"physical_pdf_page":67,"printed_page":34,"section":"Elevation",
                 "disposition":"GRAPHIC_ARROW_LABELS_ABSENT_FROM_TEXT_MULTIMODAL_REQUIRED",
                 "observation":"Photo arrow text missing",
                 "extracted_text_nonwhitespace_characters":104,
                 "embedded_pdf_image_xobjects":8}]}
    def validate(self,m=None,pdf=None,**changes):
        arguments=dict(expected_sha256=self.sha,expected_bytes=len(self.pdf),
                       expected_pages=73,expected_source_id="BD_PNBI_07",
                       expected_drive_file_id="stable-id")
        arguments.update(changes)
        return gate.validate_review(self.manifest if m is None else m,
                                    self.pdf if pdf is None else pdf,**arguments)
    def altered(self,fn):
        m=copy.deepcopy(self.manifest)
        fn(m)
        return m
    def test_01_safe_record_never_passes_document(self):
        r=self.validate()
        self.assertEqual(r["g3b_status"],"EVIDENCE_MANIFEST_VALID_REVIEW_REQUIRED")
        self.assertFalse(r["full_document_visual_review"])
        self.assertTrue(r["no_auto_registry_or_index"])
    def test_02_photo_and_diagram_flags(self):
        r=self.validate()
        self.assertEqual(r["risk_pages"]["SAMPLE_ONLY_NO_SITE_EVIDENCE"],[51])
        self.assertEqual(r["risk_pages"]["TEXT_ONLY_SEMANTICS_BLOCKED"],[67])
        self.assertEqual(r["g3c_status"],"LEGAL_CURRENTNESS_NOT_VERIFIED")
    def test_03_source_identity(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_ID_MISMATCH"):
            self.validate(self.altered(lambda m:m.update(document_code="BD_PNBI_08")))
    def test_04_manifest_sha(self):
        with self.assertRaisesRegex(ValueError,"MANIFEST_SHA_MISMATCH"):
            self.validate(self.altered(lambda m:m.update(file_sha256="0"*64)))
    def test_05_tampered_source_sha(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_SHA_MISMATCH"):
            self.validate(pdf=self.pdf.replace(b"source",b"SOURCe"))
    def test_06_not_pdf(self):
        bad=b"MALF-1.7\nsample source\n"
        sha=hashlib.sha256(bad).hexdigest()
        m=self.altered(lambda m:m.update(file_sha256=sha,source_file_bytes=len(bad)))
        with self.assertRaisesRegex(ValueError,"NOT_PDF"):
            self.validate(m,bad,expected_sha256=sha,expected_bytes=len(bad))
    def test_07_drive_identity(self):
        with self.assertRaisesRegex(ValueError,"DRIVE_ID_MISMATCH"):
            self.validate(self.altered(lambda m:m.update(source_drive_file_id="wrong")))
    def test_08_total_pages(self):
        with self.assertRaisesRegex(ValueError,"MANIFEST_PAGES_MISMATCH"):
            self.validate(self.altered(lambda m:m.update(physical_pdf_pages=74)))
    def test_09_unsorted_scope(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_UNSORTED_PAGES"):
            self.validate(self.altered(lambda m:m.update(reviewed_physical_pages=[51,44,67])))
    def test_10_duplicate_scope(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_UNSORTED_PAGES"):
            self.validate(self.altered(lambda m:m.update(reviewed_physical_pages=[44,44,67])))
    def test_11_page_out_of_range(self):
        with self.assertRaisesRegex(ValueError,"REVIEW_PAGE_OUT_OF_RANGE"):
            self.validate(self.altered(lambda m:m.update(reviewed_physical_pages=[44,51,74])))
    def test_12_incomplete_rows(self):
        with self.assertRaisesRegex(ValueError,"ROW_COUNT_MISMATCH"):
            self.validate(self.altered(lambda m:m["rows"].pop()))
    def test_13_row_order_conflict(self):
        with self.assertRaisesRegex(ValueError,"ROW_PAGE_ID_MISMATCH"):
            self.validate(self.altered(lambda m:m["rows"].reverse()))
    def test_14_missing_printed_page(self):
        with self.assertRaisesRegex(ValueError,"PRINTED_PAGE_NOT_RECORDED"):
            self.validate(self.altered(lambda m:m["rows"][0].pop("printed_page")))
    def test_15_printed_and_physical_are_separate(self):
        self.assertEqual(self.validate()["citation_page_field"],"physical_pdf_page")
    def test_16_unknown_disposition(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_DISPOSITION"):
            self.validate(self.altered(lambda m:m["rows"][0].update(disposition="PASS")))
    def test_17_unreviewed_status_cannot_be_pass(self):
        with self.assertRaisesRegex(ValueError,"UNSAFE_APPROVAL_STATUS"):
            self.validate(self.altered(lambda m:m.update(status="G3B_PASS")))
    def test_18_approval_claim_must_hold(self):
        with self.assertRaisesRegex(ValueError,"AUTO_APPROVAL_FORBIDDEN"):
            self.validate(self.altered(lambda m:m.update(status="APPROVED; FULL_DOCUMENT_REVIEW_REQUIRED")))
    def test_19_blank_observation(self):
        with self.assertRaisesRegex(ValueError,"MISSING_OBSERVATION"):
            self.validate(self.altered(lambda m:m["rows"][0].update(observation=" ")))
    def test_20_missing_text_metric(self):
        with self.assertRaisesRegex(ValueError,"TEXT_METRIC"):
            self.validate(self.altered(lambda m:m["rows"][0].pop("extracted_text_nonwhitespace_characters")))
    def test_21_missing_image_metric(self):
        with self.assertRaisesRegex(ValueError,"IMAGE_METRIC"):
            self.validate(self.altered(lambda m:m["rows"][0].pop("embedded_pdf_image_xobjects")))
    def test_27_prose_page_review_is_evidence_only(self):
        review = self.altered(
            lambda m: m["rows"][0].update(
                disposition="PROSE_TEXT_ORDER_VISUALLY_REVIEWED",
                observation="Rendered prose heading and reading order visually checked"))
        result = self.validate(review)
        self.assertEqual(result["risk_pages"]["PROSE_LAYOUT_REVIEWED_EVIDENCE_ONLY"], [44])
        self.assertEqual(result["g3b_status"], "EVIDENCE_MANIFEST_VALID_REVIEW_REQUIRED")

    def test_28_prose_review_must_not_claim_auto_approval(self):
        review = self.altered(
            lambda m: (m["rows"][0].update(
                disposition="PROSE_TEXT_ORDER_VISUALLY_REVIEWED"),
                m.update(status="APPROVED; FULL_DOCUMENT_REVIEW_REQUIRED")))
        with self.assertRaisesRegex(ValueError, "AUTO_APPROVAL_FORBIDDEN"):
            self.validate(review)

    def test_25_amendment_visual_highlight_is_review_required(self):
        review = self.altered(
            lambda m: m["rows"][2].update(
                disposition="VISUAL_AMENDMENT_HIGHLIGHT_NOT_PRESERVED_TEXT_ONLY",
                observation="2012 original and 2022 amended columns with yellow insertion marks"))
        result = self.validate(review)
        self.assertEqual(result["risk_pages"]["AMENDMENT_VERSION_CONTEXT_REQUIRED"], [67])
        self.assertEqual(result["g3b_status"], "EVIDENCE_MANIFEST_VALID_REVIEW_REQUIRED")
        self.assertFalse(result["full_document_visual_review"])

    def test_26_amendment_highlight_cannot_claim_pass(self):
        review = self.altered(
            lambda m: (m["rows"][2].update(
                disposition="VISUAL_AMENDMENT_HIGHLIGHT_NOT_PRESERVED_TEXT_ONLY"),
                m.update(status="G3B_PASS; FULL_DOCUMENT_REVIEW_REQUIRED")))
        with self.assertRaisesRegex(ValueError, "AUTO_APPROVAL_FORBIDDEN"):
            self.validate(review)

    def test_23_graphic_spatial_relation_is_blocked_even_with_text_labels(self):
        r = self.validate(self.altered(
            lambda m: m["rows"][2].update(
                disposition="GRAPHIC_SPATIAL_RELATION_NOT_PRESERVED_MULTIMODAL_REQUIRED",
                observation="Photo 3 string exists but arrow position is not reproducible from text")))
        self.assertEqual(r["risk_pages"]["TEXT_ONLY_SEMANTICS_BLOCKED"], [67])

    def test_24_old_graphic_label_missing_flag_still_supported(self):
        self.assertEqual(self.validate()["risk_pages"]["TEXT_ONLY_SEMANTICS_BLOCKED"], [67])

    def test_22_disposition_wrong_type(self):
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_DISPOSITION"):
            self.validate(self.altered(lambda m:m["rows"][0].update(disposition=[])))

if __name__=="__main__":
    unittest.main()
