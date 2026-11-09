#!/usr/bin/env python3
"""KB-01: offline, read-only original-PDF quote integrity for guarded Staging evidence.

The caller MUST pass trusted_source from beta_ask_staging_v1.approved_source,
not metadata supplied by an end user. A matching quote proves only PDF/page
text provenance, never semantic answer support or present-day applicability.
No retrieval changes, Drive download, SQL, model calls, or write operations.
"""

import hashlib
import hmac
import os
import re
import stat
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf

ALLOWED = frozenset(("BD_PNAP_APP145", "BD_PNAP_APP149"))
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_QUOTE_CHARS = 1500


class CitationRefused(ValueError):
    """An integrity gate failed. Reason codes must not contain source text."""


def require(ok, reason):
    if not ok:
        raise CitationRefused(reason)


def normalize(text):
    """Normalize Unicode/whitespace only: never silently rewrite legal text."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _source_identity(source):
    require(isinstance(source, dict) and source.get("approved_baseline") is True,
            "trusted_approved_source_required")
    sid = source.get("source_id")
    require(sid in ALLOWED, "source_not_allowlisted")
    checksum = source.get("checksum")
    require(isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum),
            "invalid_source_checksum")
    url = source.get("official_url")
    require(isinstance(url, str), "invalid_official_url")
    parsed = urlsplit(url)
    code = sid.rsplit("APP", 1)[-1]
    require(parsed.scheme == "https" and parsed.netloc == "www.bd.gov.hk"
            and not parsed.query and not parsed.fragment
            and parsed.path.endswith("/APP/APP" + code + ".pdf"),
            "invalid_official_url")
    return sid, checksum, url


def _checked_evidence(packet, sid, checksum, url, evidence_id):
    require(isinstance(packet, dict) and packet.get("environment") == "staging"
            and packet.get("production_write") is False,
            "staging_readonly_packet_required")
    require(packet.get("read_only") is True
            and packet.get("guard_ok") is True,
            "staging_guard_not_confirmed")
    require(packet.get("status") != "CURRENTNESS_UNVERIFIED_ABSTAIN",
            "currentness_abstention_preserved")
    sources = packet.get("sources")
    if sources is None:
        sources = [packet.get("source")]
    require(isinstance(sources, list), "invalid_packet_sources")
    matching = [s for s in sources if isinstance(s, dict)
                and s.get("source_id") == sid]
    require(len(matching) == 1, "source_missing_or_ambiguous")
    ref = matching[0]
    require((ref.get("checksum", ref.get("sha256")) == checksum
             and ref.get("official_url") == url),
            "packet_source_identity_mismatch")
    evidence = packet.get("evidence")
    require(isinstance(evidence, list), "invalid_packet_evidence")
    require(isinstance(evidence_id, str)
            and re.fullmatch(r"S[1-9][0-9]*", evidence_id),
            "invalid_evidence_id")
    matches = [ev for ev in evidence if isinstance(ev, dict)
               and ev.get("id") == evidence_id]
    require(len(matches) == 1, "evidence_missing_or_ambiguous")
    ev = matches[0]
    ev_source = ev.get("source_id")
    if ev_source is None:
        require(len(sources) == 1, "evidence_source_id_missing")
    else:
        require(ev_source == sid, "evidence_source_mismatch")
    require(type(ev.get("chunk_id")) is int and ev["chunk_id"] > 0,
            "invalid_chunk_id")
    require(type(ev.get("page")) is int and ev["page"] > 0,
            "invalid_physical_page")
    require(isinstance(ev.get("content"), str) and ev["content"].strip(),
            "invalid_chunk_content")
    if ev.get("source_url") is not None:
        require(ev["source_url"] == url + "#page=" + str(ev["page"]),
                "source_page_url_mismatch")
    return ev


def _read_original_pdf(path):
    require(isinstance(path, (str, Path)), "invalid_pdf_path")
    path = Path(path)
    require(not path.is_symlink(), "symlink_pdf_refused")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise CitationRefused("original_pdf_unavailable") from None
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_PDF_BYTES,
                "invalid_pdf_file_size_or_type")
        data = f.read(MAX_PDF_BYTES + 1)
    require(0 < len(data) <= MAX_PDF_BYTES, "invalid_pdf_file_size_or_type")
    return data


def verify_quote(packet, trusted_source, evidence_id, quote, original_pdf_path):
    """Verify a user/reviewer-selected literal quote against immutable PDF page.

    trusted_source MUST come from the existing guarded allowlist/Source Registry
    path. The packet MUST be from existing guarded Staging retrieval. The PDF
    MUST be a locally provided copy of the approved original (no fetching).
    """
    sid, checksum, url = _source_identity(trusted_source)
    ev = _checked_evidence(packet, sid, checksum, url, evidence_id)
    require(isinstance(quote, str) and 16 <= len(quote) <= MAX_QUOTE_CHARS
            and "\x00" not in quote, "invalid_quote_length_or_text")
    literal = normalize(quote)
    require(literal and literal in normalize(ev["content"]),
            "quote_not_in_indexed_chunk")
    data = _read_original_pdf(original_pdf_path)
    require(hmac.compare_digest(hashlib.sha256(data).hexdigest(), checksum),
            "original_pdf_sha256_mismatch")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            require(not pdf.is_encrypted, "encrypted_original_pdf_refused")
            require(ev["page"] <= pdf.page_count, "page_outside_original_pdf")
            physical_text = pdf.load_page(ev["page"] - 1).get_text("text")
    except CitationRefused:
        raise
    except (RuntimeError, ValueError):
        raise CitationRefused("original_pdf_parse_failed") from None
    require(literal in normalize(physical_text), "quote_not_on_original_pdf_page")
    return {
        "schema_version": "citation-integrity-v1",
        "integrity_status": "MECHANICAL_PDF_PAGE_QUOTE_MATCH",
        "evidence_id": evidence_id,
        "chunk_id": ev["chunk_id"],
        "source_id": sid,
        "source_sha256": checksum,
        "physical_page": ev["page"],
        "source_url": url + "#page=" + str(ev["page"]),
        "quote": quote,
        "semantic_answer_support": "NOT_EVALUATED",
        "current_legal_applicability": "NOT_VERIFIED",
        "ai_answer_generated": False,
        "production_write": False,
    }
