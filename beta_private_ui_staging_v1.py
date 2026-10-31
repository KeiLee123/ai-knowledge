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
import os
import secrets
import stat
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import beta_ask_staging_v1 as qa

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE_PATH = Path(__file__).with_suffix(".html")
FEEDBACK_PATH = Path("/var/lib/jason-os/private-beta-staging/feedback.jsonl")
MAX_REQUEST_BYTES = 4096
MAX_FEEDBACK_CHARS = 1000
FEEDBACK_TYPES = frozenset(("answer_wrong", "source_outdated", "card_idea", "other"))


class UIRefused(ValueError):
    pass


def ask_evidence(data):
    if not isinstance(data, dict) or set(data) != {"question", "source"}:
        raise UIRefused("invalid_query_fields")
    source_id, question = data["source"], data["question"]
    if not isinstance(source_id, str) or source_id not in qa.ALLOWED:
        raise UIRefused("source_not_allowed")
    if not isinstance(question, str) or not 5 <= len(question.strip()) <= 1200:
        raise UIRefused("invalid_question_length")
    packet = qa.build_packet(source_id, question.strip())
    decision = qa.currentness_abstention(packet)
    ref = packet["source"]
    response = {
        "request_id": secrets.token_hex(8),
        "environment": "staging",
        "status": decision["status"] if decision else "EVIDENCE_ONLY_REVIEW_REQUIRED",
        "message": decision["answer"] if decision else (
            "已找到原始文件片段，但尚未生成 AI 答案。"
            "請核對每項專業判斷、文件版本及適用性。"
        ),
        "source": {
            "source_id": ref["source_id"],
            "title": ref["title"],
            "official_url": ref["official_url"],
            "revision_date": ref["revision_date"],
            "sha256": ref["checksum"],
        },
        "coverage": packet["retrieval_coverage"],
        "evidence": [
            {
                "id": e["id"], "chunk_id": e["chunk_id"],
                "page": e["page"], "content": e["content"],
                "source_url": ref["official_url"] + "#page=" + str(e["page"]),
            }
            for e in packet["evidence"]
        ],
        "ai_answer_generated": False,
        "production_write": False,
    }
    return response


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
        if self.path not in ("/api/ask", "/api/feedback"):
            return self.respond(404, {"error": "not_found"})
        if not self.authenticated():
            return self.respond(401, {"error": "session_token_required"})
        try:
            data = self.read_data()
            if self.path == "/api/ask":
                result = ask_evidence(data)
                # A request ID is an in-memory reference, not a stored raw question.
                self.server.recent_requests[result["request_id"]] = result["source"]["source_id"]
                if len(self.server.recent_requests) > 64:
                    self.server.recent_requests.pop(next(iter(self.server.recent_requests)))
                return self.respond(200, result)
            if set(data) != {"request_id", "source", "type", "comment"}:
                raise UIRefused("invalid_feedback_fields")
            rid = data["request_id"]
            source = data["source"]
            kind = data["type"]
            comment = data["comment"]
            if (not isinstance(rid, str)
                    or self.server.recent_requests.get(rid) != source
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
        except (UIRefused, qa.BetaRefused) as exc:
            # Only stable safe reason codes. No backend exception details.
            return self.respond(400, {"error": str(exc)})
        except (OSError, RuntimeError, KeyError, TypeError):
            return self.respond(503, {"error": "staging_backend_unavailable"})


def build_server(port, token=None, feedback_path=FEEDBACK_PATH):
    if type(port) is not int or not 0 <= port <= 65535:
        raise UIRefused("invalid_port")
    server = HTTPServer((HOST, port), PrivateBetaHandler)
    server.ui_token = token or secrets.token_urlsafe(32)
    server.recent_requests = {}
    server.feedback_path = feedback_path
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
