#!/usr/bin/env python3
"""Private Beta v0.1: loopback-only web UI for existing Staging source Q&A.

Only a local/SSH-forwarded, token-authenticated UI is supported. Queries reuse
beta_ask_staging_v1 (including deterministic currentness abstention). No LLM,
Production/Drive writes, public listener, or auto-starting service.
Feedback is the sole permitted local Staging write, append-only JSONL.
"""

import argparse
import datetime
import hmac
import json
import math
import os
import secrets
import stat
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import beta_ask_staging_v1 as qa
import kb02_extractive_review_staging_v1 as kb02
from citation_integrity_staging_v1 import CitationRefused

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE_PATH = Path(__file__).with_suffix(".html")
FEEDBACK_PATH = Path("/var/lib/jason-os/private-beta-staging/feedback.jsonl")
# Manually provisioned, checksum-verified original PDF copies. No Drive/network
# access from the browser server; KB-01 enforces exact approved SHA on every use.
APPROVED_PDF_DIR = Path("/var/lib/jason-os/private-beta-staging/approved-pdfs")
MAX_REQUEST_BYTES = 4096
MAX_FEEDBACK_CHARS = 1000
FEEDBACK_TYPES = frozenset(("answer_wrong", "source_outdated", "card_idea", "other"))


class UIRefused(ValueError):
    pass


AUTO_SCOPE = "AUTO_APPROVED"


def ask_evidence(data):
    """Question-first auto search across only the two approved Beta sources.

    Keep the existing one-source path for backward-compatible manual filters.
    The frozen retrieval primitives and their per-source integrity checks stay
    unchanged. Global ranking is by comparable cosine distance, not a verdict
    on semantic correctness or current legal applicability.
    """
    if not isinstance(data, dict) or set(data) not in (
            {"question"}, {"question", "source"}):
        raise UIRefused("invalid_query_fields")
    question = data["question"]
    source_id = data.get("source", AUTO_SCOPE)
    if not isinstance(source_id, str) or (
            source_id != AUTO_SCOPE and source_id not in qa.ALLOWED):
        raise UIRefused("source_not_allowed")
    if not isinstance(question, str) or not 5 <= len(question.strip()) <= 1200:
        raise UIRefused("invalid_question_length")
    question = question.strip()
    scope = qa.ALLOWED if source_id == AUTO_SCOPE else (source_id,)
    # Fail closed: no partial result if a required approved source cannot pass
    # its existing checksum/index/Staging checks. Never silently omit it.
    packets = [qa.build_packet(sid, question) for sid in scope]
    descriptions = []
    ranked = []
    for expected_source_id, packet in zip(scope, packets):
        ref = packet["source"]
        if ref["source_id"] != expected_source_id:
            raise UIRefused("unexpected_source")
        coverage = packet["retrieval_coverage"]
        descriptions.append({
            "source_id": ref["source_id"],
            "title": ref["title"],
            "official_url": ref["official_url"],
            "revision_date": ref["revision_date"],
            "sha256": ref["checksum"],
            "coverage": coverage,
        })
        for item in packet["evidence"]:
            distance = item.get("distance")
            if source_id == AUTO_SCOPE:
                if type(distance) not in (int, float) or not math.isfinite(distance):
                    raise UIRefused("invalid_retrieval_distance")
            ranked.append((distance if distance is not None else 0,
                           ref["source_id"], item["chunk_id"], ref, item))
    if source_id == AUTO_SCOPE:
        ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    evidence = []
    for rank, (_, sid, _, ref, item) in enumerate(ranked, 1):
        evidence.append({
            "id": "S" + str(rank),
            # S-ID inside its own source packet; AUTO global IDs may differ.
            "source_evidence_id": item["id"],
            "chunk_id": item["chunk_id"],
            "page": item["page"],
            "content": item["content"],
            "source_id": sid,
            "source_title": ref["title"],
            "source_url": ref["official_url"] + "#page=" + str(item["page"]),
        })
    decision = next((result for p in packets
                     if (result := qa.currentness_abstention(p)) is not None), None)
    total = sum(d["coverage"]["indexed_chunks"] for d in descriptions)
    retrieved = sum(d["coverage"]["retrieved_unique_chunks"] for d in descriptions)
    combined_coverage = {
        "indexed_chunks": total,
        "retrieved_unique_chunks": retrieved,
        "complete_index_coverage": all(
            d["coverage"]["complete_index_coverage"] for d in descriptions),
    }
    selected = descriptions[0] if source_id != AUTO_SCOPE else {
        "source_id": AUTO_SCOPE,
        "title": "自動搜尋已核准的 APP145／APP149",
        "official_url": "",
        "revision_date": "NOT_VERIFIED",
        "sha256": "",
    }
    return {
        "request_id": secrets.token_hex(8),
        "environment": "staging",
        "status": decision["status"] if decision else "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "message": decision["answer"] if decision else (
            "已從核准來源取回候選原文片段，尚未評估其是否足以回答問題。"
            "請核對完整條文、其他可能相關的官方文件、版本及適用性。"
        ),
        "source": selected,  # request/feedback scope, including AUTO_APPROVED
        "sources": descriptions,  # actual approved documents, each with coverage
        "coverage": combined_coverage,
        "evidence": evidence,
        "ai_answer_generated": False,
        "production_write": False,
    }


def preview_selected_quote(data, recent_requests, pdf_dir=APPROVED_PDF_DIR):
    """User-selected quote verified by a new trusted Staging read-only query.

    Browser supplies only request_id, its global display S-ID and literal
    quote. Scope, question, source-local evidence ID, Chunk and PDF path
    are derived server-side from the previous authenticated /api/ask result.
    """
    if (not isinstance(data, dict)
            or set(data) != {"request_id", "evidence_id", "quote"}):
        raise UIRefused("invalid_quote_preview_fields")
    rid, eid, quote = data["request_id"], data["evidence_id"], data["quote"]
    if not isinstance(rid, str) or len(rid) != 16:
        raise UIRefused("invalid_quote_preview_request")
    if not isinstance(eid, str) or not eid.startswith("S"):
        raise UIRefused("invalid_quote_preview_evidence")
    if (not isinstance(quote, str) or not 16 <= len(quote) <= 1500
            or "\x00" in quote):
        raise UIRefused("invalid_quote_preview_text")
    session = recent_requests.get(rid)
    if not isinstance(session, dict):
        raise UIRefused("unknown_quote_preview_request")
    if session.get("status") != "EVIDENCE_ONLY_REVIEW_REQUIRED":
        raise UIRefused("quote_preview_not_permitted_for_abstention")
    evidence = session.get("evidence", {}).get(eid)
    if not isinstance(evidence, dict):
        raise UIRefused("unknown_quote_preview_evidence")
    sid = evidence.get("source_id")
    local_eid = evidence.get("source_evidence_id")
    if sid not in qa.ALLOWED or not isinstance(local_eid, str):
        raise UIRefused("quote_preview_untrusted_source")
    original_dir = Path(pdf_dir)
    if original_dir.is_symlink() or not original_dir.is_dir():
        raise UIRefused("approved_pdf_cache_unavailable")
    original = original_dir / ("APP" + sid.rsplit("APP", 1)[-1] + ".pdf")
    if original.is_symlink() or not original.is_file():
        raise UIRefused("approved_pdf_copy_unavailable")
    result = kb02.build_review_preview(
        sid, session["question"], [{"evidence_id": local_eid, "quote": quote}],
        original)
    if (result.get("status") != "EXTRACTIVE_QUOTES_REVIEW_REQUIRED"
            or len(result.get("verified_quotes", [])) != 1
            or result.get("semantic_answer_support") != "NOT_EVALUATED"
            or result.get("ai_answer_generated") is not False
            or result.get("production_write") is not False):
        raise UIRefused("quote_preview_not_verified")
    proof = result["verified_quotes"][0]
    if (proof.get("source_id") != sid
            or proof.get("evidence_id") != local_eid
            or proof.get("chunk_id") != evidence.get("chunk_id")
            or proof.get("physical_page") != evidence.get("page")):
        raise UIRefused("quote_preview_chunk_identity_changed")
    return {
        "schema_version": "kb03-private-quote-preview-v1",
        "status": "EXTRACTIVE_QUOTES_REVIEW_REQUIRED",
        "display_evidence_id": eid,
        "source_id": proof["source_id"],
        "chunk_id": proof["chunk_id"],
        "physical_page": proof["physical_page"],
        "source_sha256": proof["source_sha256"],
        "source_url": proof["source_url"],
        "quote": proof["quote"],
        "message": result["message"],
        "semantic_answer_support": "NOT_EVALUATED",
        "current_legal_applicability": "NOT_VERIFIED",
        "review_required": True,
        "ai_answer_generated": False,
        "production_write": False,
    }


def append_feedback(data, path=FEEDBACK_PATH):
    """Append feedback only to an owner-private Staging file (never Drive/DB)."""
    parent = path.parent
    if parent.is_symlink():
        raise UIRefused("feedback_directory_symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = parent.stat()
    if (not stat.S_ISDIR(folder.st_mode)
            or folder.st_uid != os.geteuid()
            or stat.S_IMODE(folder.st_mode) & 0o077):
        raise UIRefused("feedback_directory_not_private")
    flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        file_stat = os.fstat(fd)
        if (not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid != os.geteuid()
                or stat.S_IMODE(file_stat.st_mode) & 0o077):
            raise UIRefused("feedback_file_not_private")
        line = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.write(fd, line)
    finally:
        os.close(fd)


class PrivateBetaHandler(BaseHTTPRequestHandler):
    server_version = "JasonOSPrivateBeta/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):
        # No access logs: queries and session tokens must not leak to journals.
        pass

    def respond(self, code, payload, content_type="application/json; charset=utf-8",
                nonce=None):
        body = (payload if isinstance(payload, bytes)
                else json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if nonce:
            policy = ("default-src 'none'; base-uri 'none'; form-action 'none'; "
                      "frame-ancestors 'none'; connect-src 'self'; "
                      "style-src 'nonce-" + nonce + "'; "
                      "script-src 'nonce-" + nonce + "'")
            self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (
            "127.0.0.1:" + str(port), "localhost:" + str(port)
        )

    def allowed_origin(self):
        port = self.server.server_address[1]
        return self.headers.get("Origin") in (
            "http://127.0.0.1:" + str(port),
            "http://localhost:" + str(port),
        )

    def authenticated(self):
        token = self.headers.get("X-Jason-OS-Beta-Token", "")
        return hmac.compare_digest(token, self.server.ui_token)

    def do_GET(self):
        if not self.allowed_host():
            return self.respond(403, {"error": "invalid_local_host"})
        if self.path != "/":
            return self.respond(404, {"error": "not_found"})
        nonce = secrets.token_urlsafe(24)
        html = PAGE_PATH.read_text(encoding="utf-8").replace("__NONCE__", nonce)
        self.respond(200, html.encode("utf-8"), "text/html; charset=utf-8", nonce)

    def read_data(self):
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise UIRefused("json_required")
        raw_length = self.headers.get("Content-Length")
        if not raw_length or not raw_length.isascii() or not raw_length.isdigit():
            raise UIRefused("content_length_required")
        length = int(raw_length)
        if not 1 <= length <= MAX_REQUEST_BYTES:
            raise UIRefused("request_too_large")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, ValueError):
            raise UIRefused("invalid_json") from None
        if not isinstance(data, dict):
            raise UIRefused("invalid_json_object")
        return data

    def do_POST(self):
        if not self.allowed_host() or not self.allowed_origin():
            return self.respond(403, {"error": "local_origin_required"})
        if self.path not in ("/api/ask", "/api/quote-preview", "/api/feedback"):
            return self.respond(404, {"error": "not_found"})
        if not self.authenticated():
            return self.respond(401, {"error": "session_token_required"})
        try:
            data = self.read_data()
            if self.path == "/api/ask":
                result = ask_evidence(data)
                # A request ID is an in-memory reference, not a stored raw question.
                self.server.recent_requests[result["request_id"]] = {
                    "scope": result["source"]["source_id"],
                    "question": data["question"].strip(),
                    "status": result["status"],
                    "evidence": {
                        ev["id"]: {
                            "source_id": ev["source_id"],
                            "source_evidence_id": ev["source_evidence_id"],
                            "chunk_id": ev["chunk_id"],
                            "page": ev["page"],
                        } for ev in result["evidence"]
                    },
                }
                if len(self.server.recent_requests) > 64:
                    self.server.recent_requests.pop(next(iter(self.server.recent_requests)))
                return self.respond(200, result)
            if self.path == "/api/quote-preview":
                return self.respond(200, preview_selected_quote(
                    data, self.server.recent_requests, self.server.pdf_dir))
            if set(data) != {"request_id", "source", "type", "comment"}:
                raise UIRefused("invalid_feedback_fields")
            rid = data["request_id"]
            source = data["source"]
            kind = data["type"]
            comment = data["comment"]
            if (not isinstance(rid, str)
                    or self.server.recent_requests.get(rid, {}).get("scope") != source
                    or kind not in FEEDBACK_TYPES
                    or not isinstance(comment, str)
                    or not 5 <= len(comment.strip()) <= MAX_FEEDBACK_CHARS):
                raise UIRefused("invalid_feedback")
            record = {
                "schema_version": "private-beta-feedback-v0.1",
                "environment": "staging",
                "created_at_utc": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
                "request_id": rid,
                "source_id": source,
                "type": kind,
                "comment": comment.strip(),
                "status": "NEW",
            }
            append_feedback(record, self.server.feedback_path)
            return self.respond(201, {"saved": True, "request_id": rid})
        except (UIRefused, qa.BetaRefused, kb02.ExtractiveRefused, CitationRefused) as exc:
            # Only stable safe reason codes. No backend exception details.
            return self.respond(400, {"error": str(exc)})
        except (OSError, RuntimeError, KeyError, TypeError):
            return self.respond(503, {"error": "staging_backend_unavailable"})


def build_server(port, token=None, feedback_path=FEEDBACK_PATH, pdf_dir=APPROVED_PDF_DIR):
    if type(port) is not int or not 0 <= port <= 65535:
        raise UIRefused("invalid_port")
    server = HTTPServer((HOST, port), PrivateBetaHandler)
    server.ui_token = token or secrets.token_urlsafe(32)
    server.recent_requests = {}
    server.feedback_path = feedback_path
    server.pdf_dir = pdf_dir
    return server


def main():
    parser = argparse.ArgumentParser(description="Local-only Private Beta Staging UI")
    parser.add_argument("--serve", action="store_true", help="explicit local-only start")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not args.serve or not 1024 <= args.port <= 65535:
        parser.error("--serve and an unprivileged TCP port are required")
    # Reuse the existing clean checkout, Staging DB and safety gates.
    qa.check_checkout()
    if not PAGE_PATH.is_file():
        raise SystemExit("PRIVATE_BETA_REFUSED: missing_ui_template")
    server = build_server(args.port)
    print("PRIVATE BETA — STAGING / LOCAL ONLY", flush=True)
    print("Open through SSH forwarding: http://127.0.0.1:" + str(args.port), flush=True)
    print("Session token (copy into browser, never share):", server.ui_token, flush=True)
    print("AI generation DISABLED; only local feedback JSONL is writable.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
