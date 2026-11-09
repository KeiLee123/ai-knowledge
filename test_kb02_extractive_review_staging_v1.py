#!/usr/bin/env python3
"""KB-02 offline tests: actual synthetic PDFs, mocked existing Staging QA calls."""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

import kb02_extractive_review_staging_v1 as b
import citation_integrity_staging_v1 as integrity

URL = ("https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
       "practice-notes-and-circular-letters/pnap/APP/APP149.pdf")
QUESTION = "What does the approved historic APP149 actually say about temporary absence?"
QUOTE_A = "Temporary absence of the authorized signatory requires notification."
QUOTE_B = "Appendix B is headed Notification of Nomination of Temporary Authorized Signatory."


def fixture(folder):
    pdf = pymupdf.open()
    p1 = pdf.new_page()
    p1.insert_text((40, 70), QUOTE_A)
    p2 = pdf.new_page()
    p2.insert_text((40, 70), QUOTE_B)
    data = pdf.tobytes()
    pdf.close()
    path = Path(folder) / "original.pdf"
    path.write_bytes(data)
    checksum = hashlib.sha256(data).hexdigest()
    source = {
        "source_id": "BD_PNAP_APP149", "title": "Historic APP149",
        "checksum": checksum, "approved_baseline": True,
        "official_url": URL, "revision_date": "NOT_VERIFIED",
        "currentness_verified": False,
    }
    packet = {
        "question": QUESTION, "source": dict(source),
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "environment": "staging", "guard_ok": True, "read_only": True,
        "production_write": False,
        "retrieval_coverage": {
            "complete_index_coverage": True, "indexed_chunks": 2,
            "retrieved_unique_chunks": 2,
        },
        "evidence": [
            {"id": "S1", "chunk_id": 121, "page": 1, "content": QUOTE_A,
             "source_url": URL + "#page=1"},
            {"id": "S2", "chunk_id": 125, "page": 2, "content": QUOTE_B,
             "source_url": URL + "#page=2"},
        ],
    }
    return path, source, packet


def selected(*ids):
    quotes = {"S1": QUOTE_A, "S2": QUOTE_B}
    return [{"evidence_id": sid, "quote": quotes[sid]} for sid in ids]


def composed(path, source, packet, question=QUESTION, choices=None):
    if choices is None:
        choices = selected("S1")
    packet["question"] = question
    with patch.object(b.qa, "build_packet", return_value=packet) as retrieval, \
         patch.object(b.qa, "approved_source", return_value=source) as approved:
        result = b.build_review_preview("BD_PNAP_APP149", question, choices, path)
    retrieval.assert_called_once_with("BD_PNAP_APP149", question.strip())
    if result["status"] == "EXTRACTIVE_QUOTES_REVIEW_REQUIRED":
        approved.assert_called_once_with("BD_PNAP_APP149")
    else:
        approved.assert_not_called()
    return result


def refused(fn, reason):
    try:
        fn()
    except b.ExtractiveRefused as error:
        assert str(error) == reason, (error, reason)
    else:
        raise AssertionError("unsafe extractive preview was accepted: " + reason)


def test_one_quote_proof_preserves_all_identity_and_review_limits():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        result = composed(path, source, packet)
        assert result["status"] == "EXTRACTIVE_QUOTES_REVIEW_REQUIRED"
        assert result["citations"] == ["S1"]
        assert result["verified_quotes"][0]["chunk_id"] == 121
        assert result["verified_quotes"][0]["physical_page"] == 1
        assert result["verified_quotes"][0]["source_sha256"] == source["checksum"]
        assert result["verified_quotes"][0]["source_url"] == URL + "#page=1"
        assert result["answer"].endswith("[S1] " + QUOTE_A)
        assert result["semantic_answer_support"] == "NOT_EVALUATED"
        assert result["material_conditions_checked"] is False
        assert result["current_legal_applicability"] == "NOT_VERIFIED"
        assert result["ai_answer_generated"] is False
        assert result["external_model_called"] is False
        assert result["production_write"] is False
        assert result["review_required"] is True


def test_two_selected_excerpts_preserve_source_specific_pages():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        result = composed(path, source, packet, choices=selected("S2", "S1"))
        assert result["citations"] == ["S2", "S1"]
        assert [x["physical_page"] for x in result["verified_quotes"]] == [2, 1]
        assert result["answer"].count(QUOTE_A) == 1
        assert result["answer"].count(QUOTE_B) == 1


def test_no_selection_avoids_automatic_similar_chunk_promotion():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        with patch.object(b, "verify_quote", side_effect=AssertionError("unexpected quote")):
            result = composed(path, source, packet, choices=[])
        assert result["status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
        assert result["citations"] == []
        assert result["verified_quotes"] == []
        assert result["review_required"] is True
        assert result["ai_answer_generated"] is False


def test_currentness_question_abstains_before_any_pdf_verification():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        question = "截至2026年11月10日，APP149 是否仍然有效？"
        with patch.object(b, "verify_quote", side_effect=AssertionError("must abstain")):
            result = composed(path, source, packet, question=question)
        assert result["status"] == "CURRENTNESS_UNVERIFIED_ABSTAIN"
        assert result["citations"] == []
        assert "未經獨立核實" in result["message"]
        assert "answer" not in result


def test_incomplete_coverage_cannot_be_presented_as_verified_response():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        packet["retrieval_coverage"]["complete_index_coverage"] = False
        with patch.object(b, "verify_quote", side_effect=AssertionError("must abstain")):
            result = composed(path, source, packet)
        assert result["status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
        assert not result["verified_quotes"]


def test_mismatched_pdf_or_chunk_fails_without_partial_response():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        packet["evidence"][1]["page"] = 1
        packet["evidence"][1]["source_url"] = URL + "#page=1"
        with patch.object(b.qa, "build_packet", return_value=packet), \
             patch.object(b.qa, "approved_source", return_value=source):
            try:
                b.build_review_preview("BD_PNAP_APP149", QUESTION, selected("S1", "S2"), path)
            except integrity.CitationRefused as error:
                assert str(error) == "quote_not_on_original_pdf_page"
            else:
                raise AssertionError("partial verified quote list escaped")
        packet["evidence"][1]["page"] = 2
        packet["evidence"][1]["source_url"] = URL + "#page=2"
        path.write_bytes(b"tampered PDF")
        with patch.object(b.qa, "build_packet", return_value=packet), \
             patch.object(b.qa, "approved_source", return_value=source):
            try:
                b.build_review_preview("BD_PNAP_APP149", QUESTION, selected("S1"), path)
            except integrity.CitationRefused as error:
                assert str(error) == "original_pdf_sha256_mismatch"
            else:
                raise AssertionError("tampered PDF accepted")


def test_invalid_source_question_and_selection_do_not_query_database():
    with patch.object(b.qa, "build_packet",
                      side_effect=AssertionError("unexpected DB query")):
        refused(lambda: b.build_review_preview("BAD", QUESTION, [], "/tmp/unused.pdf"),
                "source_not_allowed")
        refused(lambda: b.build_review_preview("BD_PNAP_APP149", 123, [], "/tmp/unused.pdf"),
                "invalid_question")
        refused(lambda: b.build_review_preview("BD_PNAP_APP149", QUESTION,
                                                [{"evidence_id": "S999", "quote": "too short"}],
                                                "/tmp/unused.pdf"),
                "invalid_selected_quote")
        refused(lambda: b.build_review_preview("BD_PNAP_APP149", QUESTION,
                                                selected("S1", "S1"), "/tmp/unused.pdf"),
                "duplicate_evidence_selection")
        refused(lambda: b.build_review_preview("BD_PNAP_APP149", QUESTION,
                                                [{"evidence_id": "S1", "quote": QUOTE_A,
                                                  "reviewed": True}], "/tmp/unused.pdf"),
                "invalid_selection_fields")


def test_guard_or_question_source_mismatch_fail_closed():
    with tempfile.TemporaryDirectory() as folder:
        path, source, packet = fixture(folder)
        with patch.object(b.qa, "build_packet", return_value=packet):
            packet["guard_ok"] = False
            refused(lambda: b.build_review_preview(
                "BD_PNAP_APP149", QUESTION, selected("S1"), path),
                "untrusted_staging_packet")
            packet["guard_ok"] = True
            packet["source"]["source_id"] = "BD_PNAP_APP145"
            refused(lambda: b.build_review_preview(
                "BD_PNAP_APP149", QUESTION, selected("S1"), path),
                "question_or_source_mismatch")


def test_offline_no_unauthorized_service_invocation():
    code = Path(b.__file__).read_text(encoding="utf-8")
    for forbidden in ("generate_draft(", "urlopen(", "subprocess.", "rclone ",
                      "DELETE FROM", "UPDATE documents", "INSERT INTO",
                      "0.0.0.0", "api.deepseek.com", "os.system("):
        assert forbidden not in code, forbidden


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("KB-02 BOUNDED EXTRACTIVE QUOTE PREVIEW: PASS")


if __name__ == "__main__":
    main()
