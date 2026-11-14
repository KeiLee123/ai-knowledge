#!/usr/bin/env python3
"""Owner-only, local Staging feedback triage (no HTTP, network or Production writes).

The browser feedback JSONL is immutable input. Review decisions live in a separate
private append-only event log; GitHub issue IDs are local references only.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path

ROOT = Path("/var/lib/jason-os/private-beta-staging")
QUEUE = ROOT / "feedback.jsonl"
REVIEWS = ROOT / "feedback-reviews.jsonl"
STATES = ("NEW", "TRIAGED", "IN_PROGRESS", "RESOLVED", "WONT_FIX")
PRIORITIES = ("LOW", "MEDIUM", "HIGH")
TYPES = ("answer_wrong", "source_outdated", "card_idea", "other")
TRANSITIONS = {
    "NEW": {"TRIAGED"},
    "TRIAGED": {"IN_PROGRESS", "RESOLVED", "WONT_FIX"},
    "IN_PROGRESS": {"TRIAGED", "RESOLVED", "WONT_FIX"},
    "RESOLVED": set(),
    "WONT_FIX": set(),
}
SCHEMA = "private-beta-feedback-review-v0.1"
MAX_LINE_BYTES = 16384


class ReviewRefused(ValueError):
    """Expected fail-closed state, never include private feedback in errors."""


def ensure_private_parent(parent):
    if parent.is_symlink() or not parent.is_dir():
        raise ReviewRefused("private_directory_unavailable")
    s = parent.stat()
    if (not stat.S_ISDIR(s.st_mode) or s.st_uid != os.geteuid()
            or stat.S_IMODE(s.st_mode) & 0o077):
        raise ReviewRefused("private_directory_permission_invalid")


def open_private(path, flags):
    ensure_private_parent(path.parent)
    if path.is_symlink():
        raise ReviewRefused("private_file_symlink")
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    s = os.fstat(fd)
    if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid()
            or stat.S_IMODE(s.st_mode) & 0o077):
        os.close(fd)
        raise ReviewRefused("private_file_permission_invalid")
    return fd


def read_rows(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), "r", encoding="utf-8") as f:
        rows = []
        for line in f:
            if not line.endswith("\n") or len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ReviewRefused("invalid_jsonl_line")
            try:
                rows.append((json.loads(line), hashlib.sha256(line.encode("utf-8")).hexdigest()))
            except (ValueError, TypeError):
                raise ReviewRefused("invalid_jsonl_line") from None
        return rows


def load_queue(path=QUEUE):
    try:
        fd = open_private(path, os.O_RDONLY)
    except FileNotFoundError:
        raise ReviewRefused("feedback_queue_missing") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        rows = read_rows(fd)
    finally:
        os.close(fd)
    for obj, _ in rows:
        if (not isinstance(obj, dict)
                or obj.get("schema_version") != "private-beta-feedback-v0.1"
                or obj.get("environment") != "staging"
                or obj.get("status") != "NEW"
                or obj.get("type") not in TYPES
                or not isinstance(obj.get("comment"), str)
                or not 5 <= len(obj["comment"]) <= 1000
                or obj.get("source_id") not in ("AUTO_APPROVED", "BD_PNAP_APP145", "BD_PNAP_APP149")
                or not isinstance(obj.get("created_at_utc"), str)
                or not isinstance(obj.get("request_id"), str)
                or len(obj["request_id"]) != 16):
            raise ReviewRefused("invalid_feedback_record")
    return rows


def fold_reviews(queue, events):
    latest = {}
    for obj, _ in events:
        if (not isinstance(obj, dict)
                or set(obj) != {"schema_version", "environment", "at_utc",
                               "item", "fingerprint", "state", "priority", "issue"}
                or obj.get("schema_version") != SCHEMA
                or obj.get("environment") != "staging"
                or type(obj.get("item")) is not int
                or not 1 <= obj["item"] <= len(queue)
                or obj.get("fingerprint") != queue[obj["item"] - 1][1]
                or obj.get("state") not in STATES[1:]
                or obj.get("priority") not in PRIORITIES
                or (obj.get("issue") is not None and
                    (type(obj["issue"]) is not int or not 1 <= obj["issue"] <= 1_000_000_000))
                or not isinstance(obj.get("at_utc"), str)):
            raise ReviewRefused("invalid_review_event")
        item = obj["item"]
        old = latest.get(item, {}).get("state", "NEW")
        if obj["state"] not in TRANSITIONS[old]:
            raise ReviewRefused("invalid_review_transition")
        if obj["state"] in ("IN_PROGRESS", "RESOLVED") and obj["issue"] is None:
            raise ReviewRefused("issue_required")
        latest[item] = obj
    return latest


def read_reviews(path=REVIEWS):
    try:
        fd = open_private(path, os.O_RDONLY)
    except FileNotFoundError:
        ensure_private_parent(path.parent)
        return []
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        return read_rows(fd)
    finally:
        os.close(fd)


def snapshot(queue_path=QUEUE, review_path=REVIEWS):
    rows = load_queue(queue_path)
    latest = fold_reviews(rows, read_reviews(review_path))
    return rows, latest


def update(item, state, priority, issue=None, apply=False,
           queue_path=QUEUE, review_path=REVIEWS):
    if type(item) is not int or item <= 0 or state not in STATES[1:] or priority not in PRIORITIES:
        raise ReviewRefused("invalid_update_input")
    if issue is not None and (type(issue) is not int or not 1 <= issue <= 1_000_000_000):
        raise ReviewRefused("invalid_issue_number")
    rows = load_queue(queue_path)
    if item > len(rows):
        raise ReviewRefused("unknown_feedback_item")
    if not apply:
        current = fold_reviews(rows, read_reviews(review_path))
        old = current.get(item, {}).get("state", "NEW")
        if state not in TRANSITIONS[old]:
            raise ReviewRefused("invalid_review_transition")
        effective_issue = issue if issue is not None else current.get(item, {}).get("issue")
        if state in ("IN_PROGRESS", "RESOLVED") and effective_issue is None:
            raise ReviewRefused("issue_required")
        return {"item": item, "from": old, "to": state, "priority": priority,
                "issue": effective_issue, "applied": False}

    # Validate before O_CREAT; repeat under lock to reject concurrent changes.
    candidate = fold_reviews(rows, read_reviews(review_path))
    previous = candidate.get(item, {}).get("state", "NEW")
    effective = issue if issue is not None else candidate.get(item, {}).get("issue")
    if state not in TRANSITIONS[previous]:
        raise ReviewRefused("invalid_review_transition")
    if state in ("IN_PROGRESS", "RESOLVED") and effective is None:
        raise ReviewRefused("issue_required")
    fd = open_private(review_path, os.O_RDWR | os.O_APPEND | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        current = fold_reviews(rows, read_rows(fd))
        old = current.get(item, {}).get("state", "NEW")
        if state not in TRANSITIONS[old]:
            raise ReviewRefused("invalid_review_transition")
        effective_issue = issue if issue is not None else current.get(item, {}).get("issue")
        if state in ("IN_PROGRESS", "RESOLVED") and effective_issue is None:
            raise ReviewRefused("issue_required")
        event = {
            "schema_version": SCHEMA, "environment": "staging",
            "at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "item": item, "fingerprint": rows[item - 1][1],
            "state": state, "priority": priority, "issue": effective_issue,
        }
        raw = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if os.write(fd, raw) != len(raw):
            raise ReviewRefused("incomplete_review_append")
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"item": item, "from": old, "to": state, "priority": priority,
            "issue": effective_issue, "applied": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local private Staging Feedback Review (no network)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    sub.add_parser("list")
    show = sub.add_parser("show", help="explicitly reveal one comment only on this private terminal")
    show.add_argument("--item", required=True, type=int)
    change = sub.add_parser("set", help="dry-run by default; --apply writes review log")
    change.add_argument("--item", required=True, type=int)
    change.add_argument("--state", required=True, choices=STATES[1:])
    change.add_argument("--priority", required=True, choices=PRIORITIES)
    change.add_argument("--issue", type=int, help="existing issue number in KeiLee123/ai-knowledge")
    change.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "set":
            result = update(args.item, args.state, args.priority, args.issue, args.apply,
                            queue_path=QUEUE, review_path=REVIEWS)
            print(json.dumps(result, sort_keys=True))
            return 0
        rows, latest = snapshot(QUEUE, REVIEWS)
        if args.command == "summary":
            counts = {s: 0 for s in STATES}
            for i in range(1, len(rows) + 1):
                counts[latest.get(i, {}).get("state", "NEW")] += 1
            print(json.dumps({"environment": "staging", "total": len(rows),
                              "counts": counts}, sort_keys=True))
        elif args.command == "list":
            for i, (obj, _) in enumerate(rows, 1):
                state = latest.get(i, {})
                print(json.dumps({"item": i, "created_at_utc": obj["created_at_utc"],
                    "type": obj["type"], "source_id": obj["source_id"],
                    "state": state.get("state", "NEW"), "priority": state.get("priority"),
                    "issue": state.get("issue")}, sort_keys=True))
        else:
            if not 1 <= args.item <= len(rows):
                raise ReviewRefused("unknown_feedback_item")
            obj = rows[args.item - 1][0]
            print("PRIVATE FEEDBACK COMMENT (operator terminal only):")
            print(obj["comment"])
        return 0
    except (ReviewRefused, OSError, UnicodeError) as exc:
        # Deliberately no sensitive record content, filesystem path or token.
        print("FEEDBACK_REVIEW_REFUSED: " +
              (str(exc) if isinstance(exc, ReviewRefused) else "private_io_unavailable"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
