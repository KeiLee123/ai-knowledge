#!/usr/bin/env python3
"""KB-02: bounded offline-style extractive review preview using guarded Staging evidence.

This is NOT an AI-answer engine, relevance evaluator or product-facing endpoint.
Only trusted guarded QA + original-PDF verified literal quotes can be displayed.
No unreviewed compliance interpretation, external LLM, DB/Drive write or UI change.
"""

import re

import beta_ask_staging_v1 as qa
from citation_integrity_staging_v1 import verify_quote

MAX_SELECTED_QUOTES = 3
MAX_QUOTE_CHARS = 1500


class ExtractiveRefused(ValueError):
    """Stable failure reason for invalid preview requests, never raw source text."""


def require(value, reason):
    if not value:
        raise ExtractiveRefused(reason)


def _validate_selections(selections):
    require(isinstance(selections, list)
            and len(selections) <= MAX_SELECTED_QUOTES, "invalid_selection_count")
    used = set()
    for choice in selections:
        require(isinstance(choice, dict)
                and set(choice) == {"evidence_id", "quote"},
                "invalid_selection_fields")
        sid, quote = choice["evidence_id"], choice["quote"]
        require(isinstance(sid, str)
                and re.fullmatch(r"S[1-9][0-9]*", sid),
                "invalid_selected_evidence_id")
        require(sid not in used, "duplicate_evidence_selection")
        used.add(sid)
        require(isinstance(quote, str) and 16 <= len(quote) <= MAX_QUOTE_CHARS
                and "\x00" not in quote, "invalid_selected_quote")


def _base_response(status, message, packet):
    return {
        "schema_version": "kb02-extractive-review-v1",
        "environment": "staging",
        "status": status,
        "message": message,
        "question": packet["question"],
        "citations": [],
        "verified_quotes": [],
        "semantic_answer_support": "NOT_EVALUATED",
        "material_conditions_checked": False,
        "current_legal_applicability": "NOT_VERIFIED",
        "ai_answer_generated": False,
        "external_model_called": False,
        "production_write": False,
        "review_required": True,
    }


def build_review_preview(source_id, question, selections, original_pdf_path):
    """Compose *selected verbatim excerpts*, not a legal or professional answer.

    The private caller supplies selections, not a trusted evidence packet or
    source metadata. The existing guarded QA builds a fresh read-only packet,
    whose S-IDs, Chunk IDs and source SHA must match the original PDF again.
    The selection MUST NOT be inferred from similarity ranking or an LLM.
    """
    require(isinstance(source_id, str) and source_id in qa.ALLOWED,
            "source_not_allowed")
    require(isinstance(question, str) and 5 <= len(question.strip()) <= 1200,
            "invalid_question")
    _validate_selections(selections)
    # Existing staging checkout / source registry / checksum / DB read-only gates.
    packet = qa.build_packet(source_id, question.strip())
    require(isinstance(packet, dict)
            and packet.get("environment") == "staging"
            and packet.get("read_only") is True
            and packet.get("guard_ok") is True
            and packet.get("production_write") is False
            and packet.get("answer_status") == "EVIDENCE_ONLY_REVIEW_REQUIRED",
            "untrusted_staging_packet")
    require(packet.get("question") == question.strip()
            and isinstance(packet.get("source"), dict)
            and packet["source"].get("source_id") == source_id,
            "question_or_source_mismatch")
    currentness = qa.currentness_abstention(packet)
    if currentness is not None:
        return _base_response(currentness["status"], currentness["answer"], packet)
    if packet.get("retrieval_coverage", {}).get("complete_index_coverage") is not True:
        return _base_response(
            "EVIDENCE_ONLY_REVIEW_REQUIRED",
            "索引覆蓋尚未完整，不能展示為已核實的引文式回答；請核對完整原文。",
            packet,
        )
    if not selections:
        return _base_response(
            "EVIDENCE_ONLY_REVIEW_REQUIRED",
            "尚未選定可核對的原文引文；搜尋候選片段不代表已回答問題。",
            packet,
        )
    trusted = qa.approved_source(source_id)
    checked = []
    # ALL selected quotes must pass: never show partial "verified" output.
    for choice in selections:
        checked.append(verify_quote(
            packet, trusted, choice["evidence_id"], choice["quote"],
            original_pdf_path))
    result = _base_response(
        "EXTRACTIVE_QUOTES_REVIEW_REQUIRED",
        "以下僅是已核對來源和頁碼的原文摘錄。"
        "與問題的直接相關性、例外及現行法律適用性仍須人工核對。",
        packet,
    )
    result["verified_quotes"] = checked
    result["citations"] = [item["evidence_id"] for item in checked]
    # No paraphrase or conclusion is added; citation IDs are outside the quote.
    result["answer"] = result["message"] + "\n" + "\n".join(
        "[" + item["evidence_id"] + "] " + item["quote"] for item in checked
    )
    return result
