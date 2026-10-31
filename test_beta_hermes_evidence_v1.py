#!/usr/bin/env python3
"""Offline Staging evidence serialization contract: no model/API or network."""
import json
from io import StringIO
from unittest.mock import patch

import beta_hermes_evidence_v1 as h
from beta_ask_staging_v1 import BetaRefused


def packet():
    return {
        "environment": "staging",
        "read_only": True,
        "production_write": False,
        "guard_ok": True,
        "source": {
            "source_id": "BD_PNAP_APP149",
            "title": "Authorized Signatories",
            "official_url": (
                "https://www.bd.gov.hk/doc/en/resources/"
                "codes-and-references/practice-notes-and-circular-letters/"
                "pnap/APP/APP149.pdf"
            ),
            "approved_baseline": True,
            "checksum": "a" * 64,
        },
        "integrity": {"integrity_ok": True},
        "question": "What are the conditions for a temporary AS?",
        "evidence": [{
            "id": "S1",
            "page": 2,
            "chunk_id": 121,
            "distance": 0.1,
            "content": "Original paragraph 6: temporary AS nomination.",
        }],
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
    }


def rejected(p, reason):
    try:
        h.serialize_evidence(p)
    except BetaRefused as exc:
        assert reason in str(exc), str(exc)
        return
    raise AssertionError("Unsafe evidence packet was accepted")


def test_original_source_and_checksum_are_preserved():
    original = packet()
    result = h.serialize_evidence(original)
    assert result["source_id"] == original["source"]["source_id"]
    assert result["approved_pdf_sha256"] == "a" * 64
    assert result["evidence"][0]["pdf_page"] == 2
    assert result["evidence"][0]["chunk_id"] == 121
    assert result["evidence"][0]["official_pdf_page_url"].endswith("APP149.pdf#page=2")
    assert result["evidence"][0]["text"] == original["evidence"][0]["content"]
    assert result["revision_date"] == "NOT_VERIFIED"
    assert result["current_legal_applicability"] == "NOT_VERIFIED"
    assert result["answer"] is None
    assert result["answer_status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
    assert result["read_only"] is True
    assert "distance" not in result["evidence"][0]


def test_limit_and_truncation_are_explicit():
    p = packet()
    p["evidence"][0]["content"] = "x" * (h.MAX_CHARS_PER_CHUNK + 17)
    result = h.serialize_evidence(p)
    item = result["evidence"][0]
    assert len(item["text"]) == h.MAX_CHARS_PER_CHUNK
    assert item["truncated"] is True


def test_staging_security_rejections():
    variants = [
        ("environment", "production", "staging_only"),
        ("read_only", False, "read_only_required"),
        ("production_write", True, "production_write_refused"),
        ("guard_ok", False, "staging_guard_required"),
        ("answer_status", "READY", "unexpected_retrieval_status"),
    ]
    for key, value, expected in variants:
        p = packet()
        p[key] = value
        rejected(p, expected)

    p = packet()
    p["source"]["source_id"] = "BD_PNAP_APP999"
    rejected(p, "source_not_allowlisted")

    p = packet()
    p["source"]["approved_baseline"] = False
    rejected(p, "source_baseline_not_approved")

    p = packet()
    p["integrity"]["integrity_ok"] = False
    rejected(p, "staging_index_integrity_required")

    p = packet()
    p["evidence"] = []
    rejected(p, "no_verified_evidence")


def test_invalid_pages_and_source_ids_rejected():
    p = packet()
    p["evidence"][0]["page"] = None
    rejected(p, "invalid_evidence_record")

    p = packet()
    p["evidence"][0]["id"] = "S3"
    rejected(p, "nonconsecutive_source_ids")

    p = packet()
    p["evidence"][0]["content"] = ""
    rejected(p, "invalid_evidence_record")


def test_cli_success_json_no_llm_call():
    p = packet()
    with patch.object(h, "build_packet", return_value=p) as query, \
         patch("sys.argv", ["beta_hermes_evidence_v1.py", "--source", "BD_PNAP_APP149",
                            "--question", "What are the conditions for a temporary AS?"]), \
         patch("sys.stdout", new_callable=StringIO) as stdout:
        h.main()
        output = json.loads(stdout.getvalue())
        assert output["source_id"] == "BD_PNAP_APP149"
        assert output["answer"] is None
        assert output["evidence"][0]["id"] == "S1"
        query.assert_called_once_with(
            "BD_PNAP_APP149", "What are the conditions for a temporary AS?", 5)


def test_cli_fail_closed_and_no_details_leaked():
    with patch.object(h, "build_packet",
                      side_effect=RuntimeError("sensitive-path/token-secret")), \
         patch("sys.argv", ["beta_hermes_evidence_v1.py", "--source", "BD_PNAP_APP145",
                            "--question", "Test question?"]), \
         patch("sys.stdout", new_callable=StringIO) as stdout:
        try:
            h.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("Expected fail closed")
        output = stdout.getvalue()
        assert "sensitive-path" not in output
        result = json.loads(output)
        assert result["status"] == "REFUSED"
        assert result["answer"] is None


def test_no_network_or_prod_or_frozen_dependency():
    from pathlib import Path
    body = Path(h.__file__).read_text(encoding="utf-8")
    for unsafe in (
        "answer_knowledge.py",
        "graph_search_v1.py",
        "urllib.request",
        "requests.post",
        "API_SERVER_KEY",
        "JASON_BETA_LLM_API_KEY",
        "0.0.0.0",
        "psycopg2",
        "subprocess.run",
    ):
        assert unsafe not in body, unsafe


def main():
    funcs = sorted(
        (name, value) for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    for name, fn in funcs:
        fn()
        print(name + ": PASS")
    print("HERMES EVIDENCE CONTRACT: PASS")


if __name__ == "__main__":
    main()
