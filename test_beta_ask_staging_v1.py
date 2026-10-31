#!/usr/bin/env python3
"""Offline quality/security contracts for the Private Beta Staging Q&A entrypoint."""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import beta_ask_staging_v1 as b


def rejects(action, message=None):
    try:
        action()
    except b.BetaRefused as exc:
        if message:
            assert message in str(exc), str(exc)
        return
    raise AssertionError("unsafe result accepted")


def sample_row(chunk=115, content="Enforcement Authority paragraph 9"):
    return {
        "chunk_id": chunk, "page_start": 3, "page_end": 3,
        "evidence_origin": "native_text", "evidence_tier": "primary",
        "retrieval_role": "text-primary", "cosine_distance": 0.16,
        "content": content,
    }


def source():
    return {
        "source_id": "BD_PNAP_APP145",
        "title": "Fire Safety (Buildings) Ordinance Cap. 572",
        "official_url": "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnap/APP/APP145.pdf",
        "canonical_source": "Current/APP/APP145.pdf",
        "checksum": "a" * 64,
        "revision_date": "NOT_VERIFIED",
    }


def test_allowlist_and_official_source_contract():
    rejects(lambda: b.approved_source("BD_PNAP_APP999"),
            "private_beta_source_not_allowed")
    config = {
        "enabled": True,
        "title": "APP145",
        "canonical_url": source()["official_url"],
        "canonical_text_ingestion": {
            "enabled": True,
            "controller_environment": "staging",
            "source": "Current/APP/APP145.pdf",
            "db_container": b.STAGING_DB_CONTAINER,
            "remote": "gdrive-bd-write:",
            "allow_production_write": False,
        },
    }
    with patch.object(b, "load_registry", return_value={
        "sources": {"BD_PNAP_APP145": config},
    }), patch.object(b, "load_expected_baseline",
                    return_value={"sha256": "a" * 64}):
        actual = b.approved_source("BD_PNAP_APP145")
        assert actual["checksum"] == "a" * 64
        assert actual["official_url"] == source()["official_url"]
        config["canonical_url"] = "https://www.bd.gov.hk.evil.test/APP/APP145.pdf"
        rejects(lambda: b.approved_source("BD_PNAP_APP145"),
                "official_source_url_refused")
        config["canonical_url"] = source()["official_url"]
        config["canonical_text_ingestion"]["source"] = "Current/APP/APP999.pdf"
        rejects(lambda: b.approved_source("BD_PNAP_APP145"),
                "canonical_staging_config_refused")


def test_missing_and_untrusted_evidence_fail_closed():
    rejects(lambda: b.validated_evidence([]), "no_evidence")
    row = sample_row()
    for altered in (
        {"evidence_tier": "supplementary"},
        {"retrieval_role": "multimodal-supplementary"},
        {"evidence_origin": "vision"},
        {"page_start": None},
        {"page_start": 0},
        {"content": ""},
    ):
        rejects(lambda: b.validated_evidence([{**row, **altered}]))
    good = b.validated_evidence([row])
    assert good[0]["id"] == "S1"
    assert good[0]["page"] == 3


def test_top_five_rescues_known_realistic_rank_three_passage():
    rows = [
        sample_row(117, "Submission of Plans for Approval and fees"),
        sample_row(111, "Introduction and application"),
        sample_row(115, "Paragraph 9: Director of Buildings and Director of Fire Services"),
    ]
    evidence = b.validated_evidence(rows)
    assert evidence[2]["id"] == "S3"
    assert evidence[2]["chunk_id"] == 115
    assert "Director of Buildings" not in evidence[0]["content"]


def test_model_answer_requires_exact_existing_citations():
    evidence = b.validated_evidence([sample_row()])
    result = b.validate_model_result(json.dumps({
        "status": "ANSWER",
        "answer": "Director of Buildings is responsible for construction. [S1]",
        "citations": ["S1"],
    }), evidence)
    assert result["status"] == "DRAFT_REVIEW_REQUIRED"
    for payload in (
        {"status": "ANSWER", "answer": "Unsupported answer", "citations": ["S1"]},
        {"status": "ANSWER", "answer": "Fake [S2]", "citations": ["S2"]},
        {"status": "ANSWER", "answer": "Fake [S2]", "citations": ["S1"]},
        {"status": "ANSWER", "answer": "Fake [S1]", "citations": []},
        {"status": "ANSWER", "answer": "Fake [S1]", "citations": ["S1", "S1"]},
        {"status": "FAILED", "answer": "Fake [S1]", "citations": ["S1"]},
    ):
        rejects(lambda p=payload: b.validate_model_result(json.dumps(p), evidence))
    rejects(lambda: b.validate_model_result("not-json", evidence))


def test_insufficient_evidence_refuses_model_claims():
    response = b.validate_model_result(json.dumps({
        "status": "INSUFFICIENT_EVIDENCE",
        "answer": "An unsupported claim",
        "citations": ["S99"],
    }), b.validated_evidence([sample_row()]))
    assert response["status"] == "INSUFFICIENT_EVIDENCE"
    assert "不足" in response["answer"]
    assert response["citations"] == []


def test_staging_runtime_guard_refuses_wrong_checkout():
    rejects(lambda: b.check_checkout(Path("/opt/ai-knowledge")),
            "staging_checkout_only")


def test_build_packet_reuses_staging_only_read_primitives():
    with patch.object(b, "check_checkout", return_value={"guard_ok": True}), \
         patch.object(b, "approved_source", return_value=source()), \
         patch.object(b, "build_integrity_sql", return_value="SELECT integrity"), \
         patch.object(b, "run_staging_query", side_effect=['{"ok":true}', "rows"]), \
         patch.object(b, "parse_integrity_payload",
                      return_value={"document_count": 1}), \
         patch.object(b, "validate_integrity",
                      return_value={"integrity_ok": True, "chunk_count": 8}), \
         patch.object(b, "embed_query", return_value=[0.0] * 384), \
         patch.object(b, "build_retrieval_sql", return_value="SELECT evidence"), \
         patch.object(b, "parse_rows",
                      return_value=[sample_row()]):
        result = b.build_packet(
            "BD_PNAP_APP145", "Who is the enforcement authority?", 5)
        assert result["read_only"] is True
        assert result["production_write"] is False
        assert result["evidence"][0]["chunk_id"] == 115
        assert result["answer_status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
        assert result["retrieval_coverage"] == {"indexed_chunks": 8,
                                                "retrieved_unique_chunks": 1,
                                                "complete_index_coverage": False}
    rejects(lambda: b.build_packet("BD_PNAP_APP145", "short", 99),
            "top_k_out_of_range")



def test_approved_eight_chunk_beta_default_and_coverage_guard():
    # The observed APP149 question ranked crucial 6(a)/6(b) at sixth place.
    # For the present two eight-chunk sources, default to all indexed chunks.
    assert b.DEFAULT_TOP_K == 8
    rows = [sample_row(119 + i, "PUBLIC APP149 chunk " + str(i))
            for i in range(8)]
    evidence = b.validated_evidence(rows)
    complete = b.retrieval_coverage({"chunk_count": 8}, evidence)
    assert complete == {
        "indexed_chunks": 8,
        "retrieved_unique_chunks": 8,
        "complete_index_coverage": True,
    }
    partial = b.retrieval_coverage({"chunk_count": 8}, evidence[:5])
    assert partial["complete_index_coverage"] is False
    assert partial["retrieved_unique_chunks"] == 5
    rejects(lambda: b.retrieval_coverage({"chunk_count": 8}, evidence[:7] + evidence[:1]),
            "duplicate_or_invalid_evidence_chunks")
    rejects(lambda: b.retrieval_coverage({"chunk_count": 0}, evidence),
            "indexed_chunk_count_unavailable")

    with patch.object(b, "check_checkout", return_value={"guard_ok": True}), \
         patch.object(b, "approved_source", return_value=source()), \
         patch.object(b, "build_integrity_sql", return_value="SELECT integrity"), \
         patch.object(b, "run_staging_query", side_effect=['{"ok":true}', "rows"]), \
         patch.object(b, "parse_integrity_payload", return_value={"document_count": 1}), \
         patch.object(b, "validate_integrity",
                      return_value={"integrity_ok": True, "chunk_count": 8}), \
         patch.object(b, "embed_query", return_value=[0.0] * 384), \
         patch.object(b, "build_retrieval_sql", return_value="SELECT evidence") as sql, \
         patch.object(b, "parse_rows", return_value=rows):
        packet = b.build_packet("BD_PNAP_APP145", "Who is the enforcement authority?")
        assert packet["retrieval_coverage"]["complete_index_coverage"] is True
        assert [item["chunk_id"] for item in packet["evidence"]] == list(range(119, 127))
        sql.assert_called_once_with("a" * 64, [0.0] * 384, 8)


def test_external_generation_requires_opt_in_before_any_query():
    with patch.object(sys, "argv", [
        "beta_ask_staging_v1.py", "--source", "BD_PNAP_APP145",
        "--generate-answer", "Who is the enforcement authority?",
    ]), patch.object(b, "build_packet",
                    side_effect=AssertionError("must not query DB")):
        rejects(b.main, "external_api_requires_explicit_confirmation")


def test_model_key_and_model_guard_before_network():
    packet = {"evidence": b.validated_evidence([sample_row()]),
              "question": "Who is the enforcement authority?",
              "source": source()}
    with patch.object(b.urllib.request, "urlopen",
                      side_effect=AssertionError("no network")):
        rejects(lambda: b.generate_draft(packet, api_key="", model="deepseek-flash"),
                "explicit_beta_api_key_required")
        rejects(lambda: b.generate_draft(packet, api_key="fake", model="unknown"),
                "model_not_allowlisted")
        rejects(lambda: b.generate_draft(packet, api_key="fake", model="deepseek-flash"),
                "incomplete_index_coverage_for_ai_draft")



def test_unverified_currentness_question_abstains_before_model():
    # The fifth real VPS query reported this metadata, but its operator-side
    # if-statement did NOT prove the product itself would refuse the answer.
    question = (
        "截至2026年10月31日，第572章消防安全（建築物）條例"
        "的現行規定是否與 APP145 完全相同？"
        "最新修訂日期及法定改善期限是甚麼？"
    )
    packet = {
        "question": question,
        "source": source(),
        "integrity": {"integrity_ok": True},
        "retrieval_coverage": {
            "indexed_chunks": 8, "retrieved_unique_chunks": 8,
            "complete_index_coverage": True,
        },
        "evidence": b.validated_evidence([sample_row()]),
    }
    decision = b.currentness_abstention(packet)
    assert decision["status"] == "CURRENTNESS_UNVERIFIED_ABSTAIN"
    assert decision["citations"] == []
    assert "未經獨立核實" in decision["answer"]
    assert b.currentness_abstention({
        **packet, "question": "根據 APP145 第 9 段，哪兩個執法機關分別負責甚麼？"
    }) is None

    for unsafe in (
        question,
        "As of October 2026 what is the current legal requirement?",
        "Is APP145 still valid and in force today?",
        "法定改善限期是幾多天？",
    ):
        assert b.currentness_abstention({**packet, "question": unsafe}) is not None
    # A revision_date value alone cannot mark the document verified.
    not_verified = {**source(), "revision_date": "2026-10-31"}
    assert b.currentness_abstention({
        **packet, "source": not_verified
    }) is not None

    with patch.object(b.urllib.request, "urlopen",
                      side_effect=AssertionError("NO_EXTERNAL_API")):
        rejects(lambda: b.generate_draft(
            packet, api_key="fake", model="deepseek-flash"
        ), "currentness_unverified_requires_abstention")
    print("Source currentness draft guard: PASS")


def test_real_fifth_question_cli_abstains_without_external_model():
    question = (
        "截至2026年10月31日，第572章消防安全（建築物）條例"
        "的現行規定是否與 APP145 完全相同？"
        "最新修訂日期及法定改善期限是甚麼？"
    )
    packet = {
        "question": question,
        "source": source(),
        "integrity": {"integrity_ok": True},
        "retrieval_coverage": {
            "indexed_chunks": 8, "retrieved_unique_chunks": 8,
            "complete_index_coverage": True,
        },
        "evidence": b.validated_evidence([sample_row()]),
    }
    # Both no-provider path and explicitly requested paid path must abstain.
    for extra in ([], ["--generate-answer", "--confirm-external-api"]):
        stdout = io.StringIO()
        argv = ["beta_ask_staging_v1.py", "--source", "BD_PNAP_APP145",
                *extra, question]
        with patch.object(sys, "argv", argv), \
             patch.object(b, "build_packet", return_value=packet), \
             patch.object(b, "generate_draft",
                          side_effect=AssertionError("NO_EXTERNAL_AI")), \
             redirect_stdout(stdout):
            b.main()
        output = stdout.getvalue()
        assert "SOURCE SAFETY ABSTENTION — NO AI ANSWER GENERATED" in output
        assert "STATUS: CURRENTNESS_UNVERIFIED_ABSTAIN" in output
        assert "ANSWER (HUMAN REVIEW REQUIRED)" not in output
        assert "Document revision/current applicability: NOT VERIFIED" in output
        assert "production_write=false" in output
    print("Real fifth-question product refusal: PASS")


def test_frozen_and_production_non_mutation_contract():
    text = Path(b.__file__).read_text(encoding="utf-8")
    assert "/opt/ai-knowledge-staging" in text
    assert "/opt/ai-knowledge/" not in text
    assert "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr" not in text
    assert "answer_knowledge" not in text
    assert "graph_search_v1.py" not in text
    assert "docker run" not in text
    assert "systemctl " not in text
    assert "UPDATE documents" not in text
    assert "DELETE FROM" not in text
    assert "INSERT INTO" not in text
    assert "0.0.0.0" not in text
    assert "source_monitor_schedule_v1.yaml" not in text


def main():
    for key, fn in sorted(globals().items()):
        if key.startswith("test_") and callable(fn):
            fn()
            print(key + ": PASS")
    print("PRIVATE BETA STAGING QA CONTRACT: PASS")


if __name__ == "__main__":
    main()
