#!/usr/bin/env python3
"""Offline security, UX and no-provider tests for the local Private Beta UI."""
import http.client
import json
import os
import stat
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import beta_private_ui_staging_v1 as ui

TOKEN = "test-token-not-a-secret"
APP145_URL = (
    "https://www.bd.gov.hk/doc/en/resources/codes-and-references/"
    "practice-notes-and-circular-letters/pnap/APP/APP145.pdf"
)


def sample_packet(question):
    return {
        "question": question,
        "source": {
            "source_id": "BD_PNAP_APP145",
            "title": "Fire Safety (Buildings) Ordinance Cap. 572",
            "official_url": APP145_URL,
            "revision_date": "NOT_VERIFIED",
            "checksum": "a" * 64,
        },
        "retrieval_coverage": {
            "indexed_chunks": 8,
            "retrieved_unique_chunks": 8,
            "complete_index_coverage": True,
        },
        "evidence": [
            {
                "id": "S1", "chunk_id": 115, "page": 3,
                "content": "Director of Buildings and Director of Fire Services"
            },
        ],
    }


def http_request(port, method, path, body=None, token=TOKEN, origin=True,
                 host_override=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {
        "Content-Type": "application/json",
        "X-Jason-OS-Beta-Token": token,
    }
    if origin:
        headers["Origin"] = "http://127.0.0.1:" + str(port)
    if host_override:
        headers["Host"] = host_override
    conn.request(method, path,
                 body=json.dumps(body, ensure_ascii=False) if body is not None else None,
                 headers=headers)
    resp = conn.getresponse()
    status, headers = resp.status, dict(resp.getheaders())
    data = resp.read()
    conn.close()
    return status, headers, data


def with_local_server(test_fn):
    with tempfile.TemporaryDirectory() as root:
        feedback = Path(root) / "private-feedback" / "feedback.jsonl"
        server = ui.build_server(0, token=TOKEN, feedback_path=feedback)
        assert server.server_address[0] == "127.0.0.1"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            test_fn(server.server_address[1], feedback)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_runtime_binding_and_private_entrypoint():
    assert ui.HOST == "127.0.0.1"
    assert ui.DEFAULT_PORT >= 1024
    assert "staging" in str(ui.FEEDBACK_PATH)
    assert "/opt/ai-knowledge" not in str(ui.FEEDBACK_PATH)
    assert "0.0.0.0" not in Path(ui.__file__).read_text(encoding="utf-8")
    html = ui.PAGE_PATH.read_text(encoding="utf-8")
    assert "<html lang=\"zh-Hant\">" in html
    assert "innerHTML" not in html
    assert "localStorage" not in html
    assert 'type="password"' in html
    assert "https://" not in html
    assert "nonce=\"__NONCE__\"" in html

    def run(port, feedback_path):
        status, headers, body = http_request(port, "GET", "/", token="")
        assert status == 200
        assert b"Knowledge Brain" in body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "script-src 'nonce-" in headers["Content-Security-Policy"]
        assert b"__NONCE__" not in body
        assert "no-store" in headers["Cache-Control"]
        assert not feedback_path.exists()
        status, _, _ = http_request(port, "GET", "/", host_override="evil.test")
        assert status == 403
    with_local_server(run)


def test_auth_origin_and_allowed_query_fields():
    def run(port, feedback_path):
        data = {"source": "BD_PNAP_APP145", "question": "Who is the enforcement authority?"}
        status, _, _ = http_request(port, "POST", "/api/ask", data, token="invalid")
        assert status == 401
        status, _, _ = http_request(port, "POST", "/api/ask", data, origin=False)
        assert status == 403
        status, _, _ = http_request(port, "POST", "/api/ask", data,
                                    host_override="evil.test")
        assert status == 403
        for invalid in (
            {"source": "BD_PNAP_APP999", "question": "valid question"},
            {"source": "BD_PNAP_APP145", "question": "valid question",
             "generate_answer": True},
            {"source": "BD_PNAP_APP145", "question": "no"},
        ):
            status, _, body = http_request(port, "POST", "/api/ask", invalid)
            assert status == 400, body
        assert not feedback_path.exists()
    with_local_server(run)


def test_evidence_uses_existing_staging_and_currentness_guard():
    safe = "根據 APP145 第9段，兩位執法機關如何分工？"
    unsafe = (
        "截至2026年10月31日，第572章消防安全（建築物）條例"
        "的現行規定是否與 APP145 完全相同？最新法定期限是甚麼？"
    )
    def run(port, feedback_path):
        with patch.object(ui.qa, "build_packet",
                          side_effect=lambda source, q: sample_packet(q)) as build, \
             patch.object(ui.qa, "generate_draft",
                          side_effect=AssertionError("external AI must not run")):
            for question, expected in (
                (safe, "EVIDENCE_ONLY_REVIEW_REQUIRED"),
                (unsafe, "CURRENTNESS_UNVERIFIED_ABSTAIN")
            ):
                status, _, raw = http_request(port, "POST", "/api/ask", {
                    "source": "BD_PNAP_APP145", "question": question,
                })
                assert status == 200, raw
                response = json.loads(raw)
                assert response["status"] == expected
                assert response["ai_answer_generated"] is False
                assert response["production_write"] is False
                assert response["coverage"]["complete_index_coverage"] is True
                assert response["evidence"][0]["source_url"] == APP145_URL + "#page=3"
                assert response["source"]["revision_date"] == "NOT_VERIFIED"
                assert len(response["request_id"]) == 16
            assert build.call_count == 2
        assert not feedback_path.exists()
    with_local_server(run)


def test_feedback_append_is_private_and_not_a_query_log():
    def run(port, feedback_path):
        with patch.object(ui.qa, "build_packet",
                          side_effect=lambda source, q: sample_packet(q)):
            status, _, raw = http_request(port, "POST", "/api/ask", {
                "source": "BD_PNAP_APP145",
                "question": "According to APP145, what is the enforcement authority?",
            })
        assert status == 200
        rid = json.loads(raw)["request_id"]
        feedback = {
            "request_id": rid, "source": "BD_PNAP_APP145",
            "type": "answer_wrong",
            "comment": "The source paragraph should be more prominent.",
        }
        status, _, _ = http_request(port, "POST", "/api/feedback",
                                    {**feedback, "request_id": "0" * 16})
        assert status == 400
        assert not feedback_path.exists()
        status, _, raw = http_request(port, "POST", "/api/feedback", feedback)
        assert status == 201, raw
        assert feedback_path.exists()
        assert stat.S_IMODE(feedback_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(feedback_path.stat().st_mode) == 0o600
        content = feedback_path.read_text(encoding="utf-8")
        item = json.loads(content.strip())
        assert item["status"] == "NEW"
        assert item["request_id"] == rid
        assert item["environment"] == "staging"
        assert "enforcement authority?" not in content
        assert "The source paragraph" in item["comment"]
        assert "api_key" not in content
    with_local_server(run)


def test_feedback_symlink_refused():
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root) / "private"
        directory.mkdir(mode=0o700)
        protected = Path(root) / "protected.jsonl"
        protected.write_text("DO NOT CHANGE", encoding="utf-8")
        (directory / "feedback.jsonl").symlink_to(protected)
        try:
            ui.append_feedback({"type": "other"}, directory / "feedback.jsonl")
        except (OSError, ui.UIRefused):
            pass
        else:
            raise AssertionError("symlink feedback was written")
        assert protected.read_text(encoding="utf-8") == "DO NOT CHANGE"


def test_no_hidden_api_or_production_side_effects():
    code = Path(ui.__file__).read_text(encoding="utf-8")
    assert "qa.build_packet(" in code
    assert "qa.currentness_abstention(" in code
    for unsafe in ("generate_draft(", "api.deepseek.com", "0.0.0.0",
                   "subprocess.Popen", "systemctl", "DELETE FROM",
                   "UPDATE documents", "INSERT INTO",
                   "gdrive-bd-write:", "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"):
        assert unsafe not in code, unsafe


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("PRIVATE BETA LOCAL UI CONTRACT: PASS")


if __name__ == "__main__":
    main()
