#!/usr/bin/env python3
"""KB-03 security & real synthetic-PDF loopback contract: no models or DB writes."""

import hashlib
import http.client
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pymupdf

import beta_private_ui_staging_v1 as ui

TOKEN = "kb03-isolated-test-token"
URL = ("https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
       "practice-notes-and-circular-letters/pnap/APP/APP149.pdf")
Q = "What does the approved APP149 say about temporary absence?"
QUOTE = "The authorized signatory may be temporarily absent from work duties."


def fixture(directory):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 70), QUOTE)
    original_bytes = doc.tobytes()
    doc.close()
    pdf_dir = directory / "approved-pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "APP149.pdf").write_bytes(original_bytes)
    checksum = hashlib.sha256(original_bytes).hexdigest()
    source = {
        "source_id": "BD_PNAP_APP149", "title": "APP149 Synthetic",
        "checksum": checksum, "approved_baseline": True,
        "official_url": URL, "currentness_verified": False,
        "revision_date": "NOT_VERIFIED",
    }
    return pdf_dir, source


def packet(source, question):
    return {
        "environment": "staging", "database": "jason-os-knowledge-db-staging",
        "read_only": True, "production_write": False, "guard_ok": True,
        "question": question, "source": dict(source),
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "retrieval_coverage": {
            "indexed_chunks": 1, "retrieved_unique_chunks": 1,
            "complete_index_coverage": True,
        },
        "evidence": [{
            "id": "S1", "chunk_id": 121, "page": 1,
            "content": QUOTE, "distance": 0.10,
        }],
    }


def request(port, path, body, token=TOKEN, origin=True, method="POST"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {
        "Content-Type": "application/json",
        "X-Jason-OS-Beta-Token": token,
    }
    if origin:
        headers["Origin"] = "http://127.0.0.1:" + str(port)
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    status, headers, data = resp.status, dict(resp.getheaders()), resp.read()
    conn.close()
    return status, headers, data


def serve(pdf_dir, func):
    server = ui.build_server(0, token=TOKEN, pdf_dir=pdf_dir,
                             feedback_path=pdf_dir.parent / "feedback" / "feedback.jsonl")
    assert server.server_address[0] == "127.0.0.1"
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        func(server.server_address[1], server)
    finally:
        server.shutdown()
        server.server_close()
        th.join(timeout=2)


def test_genuine_local_pdf_quote_preview_and_feedback_compatibility():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        pdf_dir, src = fixture(base)
        def run(port, server):
            status, headers, html = request(port, "/", None, method="GET")
            assert status == 200
            assert b"/api/quote-preview" in html
            assert b"__NONCE__" not in html
            assert "no-store" in headers["Cache-Control"]
            status, _, raw = request(port, "/api/ask",
                                     {"source": "BD_PNAP_APP149", "question": Q})
            assert status == 200, raw
            response = json.loads(raw)
            assert response["status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
            assert response["evidence"][0]["source_evidence_id"] == "S1"
            assert response["ai_answer_generated"] is False
            rid = response["request_id"]
            status, headers, raw = request(port, "/api/quote-preview", {
                "request_id": rid, "evidence_id": "S1", "quote": QUOTE,
            })
            assert status == 200, raw
            out = json.loads(raw)
            assert out["status"] == "EXTRACTIVE_QUOTES_REVIEW_REQUIRED"
            assert out["display_evidence_id"] == "S1"
            assert out["source_id"] == "BD_PNAP_APP149"
            assert out["physical_page"] == 1
            assert out["chunk_id"] == 121
            assert out["source_sha256"] == src["checksum"]
            assert out["quote"] == QUOTE
            assert out["source_url"] == URL + "#page=1"
            assert out["semantic_answer_support"] == "NOT_EVALUATED"
            assert out["current_legal_applicability"] == "NOT_VERIFIED"
            assert out["review_required"] is True
            assert out["ai_answer_generated"] is False
            assert out["production_write"] is False
            assert "no-store" in headers["Cache-Control"]
            status, _, raw = request(port, "/api/feedback", {
                "request_id": rid, "source": "BD_PNAP_APP149",
                "type": "other", "comment": "Quote passage needs more context",
            })
            assert status == 201, raw
            saved = base / "feedback" / "feedback.jsonl"
            assert saved.is_file()
            assert Q not in saved.read_text(encoding="utf-8")
        with patch.object(ui.qa, "build_packet",
                          side_effect=lambda sid, q: packet(src, q)) as db, \
             patch.object(ui.qa, "approved_source", return_value=src):
            serve(pdf_dir, run)
        assert db.call_count == 2  # ask + independently guarded re-query


def test_preview_auth_origin_shape_and_stale_request_fail_closed():
    with tempfile.TemporaryDirectory() as folder:
        pdf_dir, source = fixture(Path(folder))
        def run(port, server):
            query = {"request_id": "invalid", "evidence_id": "S1", "quote": QUOTE}
            for tok, orig, expected in (
                ("bad", True, 401), (TOKEN, False, 403),
            ):
                status, _, _ = request(port, "/api/quote-preview", query,
                                       token=tok, origin=orig)
                assert status == expected
            status, _, raw = request(port, "/api/quote-preview", query)
            assert status == 400 and b"invalid_quote_preview_request" in raw
            status, _, raw = request(port, "/api/quote-preview", {
                "request_id": "a" * 16, "evidence_id": "S1", "quote": QUOTE,
            })
            assert status == 400 and b"unknown_quote_preview_request" in raw
            assert not server.recent_requests
        serve(pdf_dir, run)


def test_client_cannot_supply_proof_or_choose_another_source():
    with tempfile.TemporaryDirectory() as folder:
        pdf_dir, source = fixture(Path(folder))
        def run(port, server):
            status, _, raw = request(port, "/api/ask",
                                     {"source": "BD_PNAP_APP149", "question": Q})
            assert status == 200, raw
            rid = json.loads(raw)["request_id"]
            for data in (
                {"request_id": rid, "evidence_id": "S1", "quote": QUOTE,
                 "guard_ok": True},
                {"request_id": rid, "evidence_id": "S999", "quote": QUOTE},
                {"request_id": rid, "evidence_id": "S1", "quote": "not exact"},
                {"request_id": rid, "evidence_id": "S1",
                 "quote": QUOTE, "source_id": "BD_PNAP_APP145"},
            ):
                status, _, _ = request(port, "/api/quote-preview", data)
                assert status == 400
            status, _, raw = request(port, "/api/quote-preview", {
                "request_id": rid, "evidence_id": "S1",
                "quote": "This is a long invented quote which is nowhere in the source.",
            })
            assert status == 400 and b"quote_not_in_indexed_chunk" in raw
        with patch.object(ui.qa, "build_packet",
                          side_effect=lambda sid, q: packet(source, q)), \
             patch.object(ui.qa, "approved_source", return_value=source):
            serve(pdf_dir, run)


def test_currentness_and_missing_original_fail_closed():
    with tempfile.TemporaryDirectory() as folder:
        pdf_dir, source = fixture(Path(folder))
        def run(port, server):
            q = "截至2026年11月11日，APP149 是否仍然有效？"
            status, _, raw = request(port, "/api/ask",
                                     {"source": "BD_PNAP_APP149", "question": q})
            assert status == 200, raw
            response = json.loads(raw)
            assert response["status"] == "CURRENTNESS_UNVERIFIED_ABSTAIN"
            status, _, raw = request(port, "/api/quote-preview", {
                "request_id": response["request_id"], "evidence_id": "S1",
                "quote": QUOTE,
            })
            assert status == 400 and b"quote_preview_not_permitted_for_abstention" in raw
            status, _, raw = request(port, "/api/ask",
                                     {"source": "BD_PNAP_APP149", "question": Q})
            rid = json.loads(raw)["request_id"]
            (pdf_dir / "APP149.pdf").unlink()
            status, _, raw = request(port, "/api/quote-preview", {
                "request_id": rid, "evidence_id": "S1", "quote": QUOTE,
            })
            assert status == 400 and b"approved_pdf_copy_unavailable" in raw
        with patch.object(ui.qa, "build_packet",
                          side_effect=lambda sid, q: packet(source, q)):
            serve(pdf_dir, run)


def test_auto_source_global_id_maps_to_internal_source_id():
    with tempfile.TemporaryDirectory() as folder:
        pdf_dir, source = fixture(Path(folder))
        other = dict(source, source_id="BD_PNAP_APP145",
                     official_url=URL.replace("APP149", "APP145"))
        def make_packet(sid, q):
            obj = packet(source if sid.endswith("149") else other, q)
            if sid.endswith("145"):
                obj["evidence"][0]["distance"] = 0.01
            else:
                obj["evidence"][0]["distance"] = 0.20
            return obj
        def run(port, server):
            status, _, raw = request(port, "/api/ask", {"question": Q})
            assert status == 200, raw
            result = json.loads(raw)
            assert result["source"]["source_id"] == "AUTO_APPROVED"
            assert result["evidence"][1]["source_id"] == "BD_PNAP_APP149"
            assert result["evidence"][1]["id"] == "S2"
            assert result["evidence"][1]["source_evidence_id"] == "S1"
            rid = result["request_id"]
            status, _, raw = request(port, "/api/quote-preview", {
                "request_id": rid, "evidence_id": "S2", "quote": QUOTE,
            })
            assert status == 200, raw
            preview = json.loads(raw)
            assert preview["display_evidence_id"] == "S2"
            assert preview["source_id"] == "BD_PNAP_APP149"
        with patch.object(ui.qa, "build_packet", side_effect=make_packet), \
             patch.object(ui.qa, "approved_source", return_value=source):
            serve(pdf_dir, run)


def test_html_csp_quote_render_no_unsafe_sink_or_storage():
    html = ui.PAGE_PATH.read_text(encoding="utf-8")
    assert "/api/quote-preview" in html
    assert "quoteField.value" in html
    assert 'lastRequest.request_id !== rid' in html
    assert 'preview.source_url' in html
    assert 'element("pre", "", preview.quote)' in html
    assert 'split(/\\s+/)' in html
    assert "innerHTML" not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "https://" not in html
    assert "document.createElement" in html
    code = Path(ui.__file__).read_text(encoding="utf-8")
    assert "APPROVED_PDF_DIR" in code
    assert "qa.generate_draft(" not in code
    assert "0.0.0.0" not in code


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("KB-03 PRIVATE BETA QUOTE UI CONTRACT: PASS")


if __name__ == "__main__":
    main()
