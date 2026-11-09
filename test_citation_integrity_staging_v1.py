#!/usr/bin/env python3
"""Offline KB-01: real PDF page extraction; all PDFs and packets synthetic."""

import hashlib
import tempfile
from pathlib import Path

import pymupdf

import citation_integrity_staging_v1 as v

URL = ("https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
       "practice-notes-and-circular-letters/pnap/APP/APP149.pdf")
QUOTE = "The authorized signatory may be temporarily absent from duties."
OTHER = "Appendix B contains a different form for the applicant."


def fixture(root):
    pdf = pymupdf.open()
    for content in (QUOTE, OTHER):
        page = pdf.new_page()
        page.insert_text((50, 70), content)
    blob = pdf.tobytes()
    pdf.close()
    path = Path(root) / "approved-original.pdf"
    path.write_bytes(blob)
    checksum = hashlib.sha256(blob).hexdigest()
    trusted = {"source_id": "BD_PNAP_APP149", "approved_baseline": True,
               "checksum": checksum, "official_url": URL,
               "revision_date": "NOT_VERIFIED", "currentness_verified": False}
    packet = {
        "environment": "staging", "read_only": True,
        "production_write": False, "guard_ok": True,
        "source": dict(trusted),
        "evidence": [
            {"id": "S1", "chunk_id": 121, "page": 1,
             "content": "5. " + QUOTE + " Appendix A.",
             "source_url": URL + "#page=1"},
            {"id": "S2", "chunk_id": 125, "page": 2,
             "content": OTHER, "source_url": URL + "#page=2"},
        ],
    }
    return path, trusted, packet


def rejects(fn, reason):
    try:
        fn()
    except v.CitationRefused as exc:
        assert str(exc) == reason, (str(exc), reason)
    else:
        raise AssertionError("Citation integrity gate accepted: " + reason)


def test_real_pdf_quote_match_returns_mechanical_only():
    with tempfile.TemporaryDirectory() as root:
        path, trusted, packet = fixture(root)
        out = v.verify_quote(packet, trusted, "S1", QUOTE, path)
        assert out["integrity_status"] == "MECHANICAL_PDF_PAGE_QUOTE_MATCH"
        assert out["source_sha256"] == trusted["checksum"]
        assert out["source_url"] == URL + "#page=1"
        assert out["physical_page"] == 1
        assert out["chunk_id"] == 121
        assert out["semantic_answer_support"] == "NOT_EVALUATED"
        assert out["current_legal_applicability"] == "NOT_VERIFIED"
        assert out["ai_answer_generated"] is False
        assert out["production_write"] is False
        assert v.verify_quote(packet, trusted, "S2", OTHER, path)["physical_page"] == 2


def test_sha_page_and_chunk_refusals():
    with tempfile.TemporaryDirectory() as root:
        path, trusted, packet = fixture(root)
        changed = dict(trusted, checksum="0" * 64)
        rejects(lambda: v.verify_quote(packet, changed, "S1", QUOTE, path),
                "packet_source_identity_mismatch")
        packet["source"]["checksum"] = "0" * 64
        rejects(lambda: v.verify_quote(packet, changed, "S1", QUOTE, path),
                "original_pdf_sha256_mismatch")
        packet["source"]["checksum"] = trusted["checksum"]
        packet["evidence"][0]["page"] = 2
        packet["evidence"][0]["source_url"] = URL + "#page=2"
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "quote_not_on_original_pdf_page")
        packet["evidence"][0]["page"] = 3
        packet["evidence"][0]["source_url"] = URL + "#page=3"
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "page_outside_original_pdf")
        packet["evidence"][0]["page"] = 1
        packet["evidence"][0]["source_url"] = URL + "#page=1"
        rejects(lambda: v.verify_quote(packet, trusted, "S1", OTHER, path),
                "quote_not_in_indexed_chunk")
        rejects(lambda: v.verify_quote(packet, trusted, "S99", QUOTE, path),
                "evidence_missing_or_ambiguous")


def test_no_forged_authority_and_no_unsafe_pdf_source():
    with tempfile.TemporaryDirectory() as root:
        path, trusted, packet = fixture(root)
        rejects(lambda: v.verify_quote(packet, dict(trusted, approved_baseline=False),
                                       "S1", QUOTE, path),
                "trusted_approved_source_required")
        rejects(lambda: v.verify_quote(packet, dict(trusted, source_id="BD_PNAP_APP999"),
                                       "S1", QUOTE, path),
                "source_not_allowlisted")
        rejects(lambda: v.verify_quote(packet, dict(trusted, official_url=URL.replace(
                    "www.bd.gov.hk", "www.bd.gov.hk.evil.test")), "S1", QUOTE, path),
                "invalid_official_url")
        packet["status"] = "CURRENTNESS_UNVERIFIED_ABSTAIN"
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "currentness_abstention_preserved")
        packet.pop("status")
        packet["production_write"] = True
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "staging_readonly_packet_required")
        packet["production_write"] = False
        proxy = Path(root) / "link.pdf"
        proxy.symlink_to(path)
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, proxy),
                "symlink_pdf_refused")


def test_auto_source_selection_requires_explicit_matching_identity():
    with tempfile.TemporaryDirectory() as root:
        path, trusted, packet = fixture(root)
        packet["sources"] = [{"source_id": "BD_PNAP_APP145",
                              "sha256": "a" * 64, "official_url": URL.replace("149", "145")},
                             {"source_id": trusted["source_id"],
                              "sha256": trusted["checksum"], "official_url": URL}]
        packet["source"] = {"source_id": "AUTO_APPROVED"}
        packet["evidence"][0]["source_id"] = trusted["source_id"]
        assert v.verify_quote(packet, trusted, "S1", QUOTE, path)["source_id"] == trusted["source_id"]
        packet["evidence"][0]["source_id"] = "BD_PNAP_APP145"
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "evidence_source_mismatch")
        del packet["evidence"][0]["source_id"]
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "evidence_source_id_missing")


def test_reject_pdf_byte_tamper_and_corrupt_pdf():
    with tempfile.TemporaryDirectory() as root:
        path, trusted, packet = fixture(root)
        path.write_bytes(b"corrupted pdf")
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "original_pdf_sha256_mismatch")
        blob = b"not a real pdf"
        trusted["checksum"] = hashlib.sha256(blob).hexdigest()
        packet["source"]["checksum"] = trusted["checksum"]
        path.write_bytes(blob)
        rejects(lambda: v.verify_quote(packet, trusted, "S1", QUOTE, path),
                "original_pdf_parse_failed")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("KB-01 OFFLINE PDF CITATION INTEGRITY: PASS")


if __name__ == "__main__":
    main()
