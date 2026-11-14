#!/usr/bin/env python3
"""Synthetic-only contracts for private, append-only KB03 review loop."""

import contextlib
import hashlib
import io
import json
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import beta_feedback_review_staging_v1 as review


def fixture():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    root.chmod(0o700)
    queue = root / "feedback.jsonl"
    reviews = root / "feedback-reviews.jsonl"
    records = [{
        "schema_version": "private-beta-feedback-v0.1", "environment": "staging",
        "created_at_utc": "2026-11-14T05:01:44+00:00", "request_id": "a" * 16,
        "source_id": "AUTO_APPROVED", "type": "other",
        "comment": "private synthetic case: §13 default quote context",
        "status": "NEW",
    }, {
        "schema_version": "private-beta-feedback-v0.1", "environment": "staging",
        "created_at_utc": "2026-11-14T05:02:00+00:00", "request_id": "b" * 16,
        "source_id": "BD_PNAP_APP145", "type": "answer_wrong",
        "comment": "private second item", "status": "NEW",
    }]
    queue.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    queue.chmod(0o600)
    return temp, queue, reviews


def run_cli(queue, reviews, args):
    output = io.StringIO()
    with patch.object(review, "QUEUE", queue), patch.object(review, "REVIEWS", reviews):
        with contextlib.redirect_stdout(output):
            code = review.main(args)
    return code, output.getvalue()


def test_default_summary_and_list_redact_private_comments():
    t, q, r = fixture()
    with t:
        code, summary = run_cli(q, r, ["summary"])
        assert code == 0
        assert json.loads(summary)["counts"]["NEW"] == 2
        code, listing = run_cli(q, r, ["list"])
        assert code == 0 and len(listing.splitlines()) == 2
        assert '"issue": null' in listing
        assert '"type": "other"' in listing
        assert "private synthetic" not in listing
        assert "request_id" not in listing
        assert '"comment"' not in listing
        assert not r.exists()


def test_explicit_show_is_local_only():
    t, q, r = fixture()
    with t:
        code, result = run_cli(q, r, ["show", "--item", "1"])
        assert code == 0 and "private synthetic case" in result
        assert not r.exists()


def test_default_dry_run_no_mutation_and_apply_event_log():
    t, q, r = fixture()
    with t:
        checksum = hashlib.sha256(q.read_bytes()).hexdigest()
        code, result = run_cli(q, r, ["set", "--item", "1", "--state", "TRIAGED", "--priority", "MEDIUM"])
        assert code == 0 and json.loads(result)["applied"] is False and not r.exists()
        code, result = run_cli(q, r, ["set", "--item", "1", "--state", "TRIAGED", "--priority", "MEDIUM", "--apply"])
        assert code == 0 and json.loads(result)["applied"] is True
        assert stat.S_IMODE(r.stat().st_mode) == 0o600
        assert hashlib.sha256(q.read_bytes()).hexdigest() == checksum
        _, st = review.snapshot(q, r)
        assert st[1]["state"] == "TRIAGED"
        assert st[1]["issue"] is None
        assert st[1]["priority"] == "MEDIUM"
        code, result = run_cli(q, r, ["set", "--item", "1", "--state", "IN_PROGRESS", "--priority", "HIGH", "--issue", "60", "--apply"])
        assert code == 0
        code, result = run_cli(q, r, ["set", "--item", "1", "--state", "RESOLVED", "--priority", "HIGH", "--apply"])
        assert code == 0 and json.loads(result)["issue"] == 60
        _, st = review.snapshot(q, r)
        assert st[1]["state"] == "RESOLVED" and st[1]["issue"] == 60
        assert len(review.read_reviews(r)) == 3
        assert hashlib.sha256(q.read_bytes()).hexdigest() == checksum
        code, _ = run_cli(q, r, ["set", "--item", "1", "--state", "TRIAGED", "--priority", "LOW", "--apply"])
        assert code == 2 and len(review.read_reviews(r)) == 3


def test_issue_gate_unknown_item_and_invalid_transition_fail_closed():
    t, q, r = fixture()
    with t:
        bad_cases = [
            ["set", "--item", "1", "--state", "IN_PROGRESS", "--priority", "LOW", "--apply"],
            ["set", "--item", "3", "--state", "TRIAGED", "--priority", "LOW", "--apply"],
            ["set", "--item", "1", "--state", "RESOLVED", "--priority", "LOW", "--issue", "60", "--apply"],
            ["set", "--item", "1", "--state", "TRIAGED", "--priority", "LOW", "--issue", "0", "--apply"],
        ]
        for case in bad_cases:
            code, msg = run_cli(q, r, case)
            assert code == 2 and "FEEDBACK_REVIEW_REFUSED" in msg
        assert not r.exists()  # Invalid transitions never create a review log


def test_corrupted_queue_and_review_state_refused_without_leak():
    t, q, r = fixture()
    with t:
        q.write_text('{"comment": "sensitive untrusted incomplete"}\n', encoding="utf-8")
        code, msg = run_cli(q, r, ["summary"])
        assert code == 2 and "sensitive" not in msg
        assert not r.exists()
    t, q, r = fixture()
    with t:
        raw = {"schema_version": review.SCHEMA, "environment": "staging", "item": 1,
               "fingerprint": "wrong", "state": "TRIAGED", "priority": "HIGH",
               "issue": 60, "at_utc": "2026-11-14"}
        r.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        r.chmod(0o600)
        code, msg = run_cli(q, r, ["list"])
        assert code == 2 and "FEEDBACK_REVIEW_REFUSED" in msg
        assert "wrong" not in msg


def test_symlink_and_public_permissions_rejected():
    t, q, r = fixture()
    with t:
        q.chmod(0o644)
        code, msg = run_cli(q, r, ["summary"])
        assert code == 2 and "permission" in msg
        q.chmod(0o600)
        q.rename(q.parent / "good.jsonl")
        q.symlink_to(q.parent / "good.jsonl")
        code, msg = run_cli(q, r, ["list"])
        assert code == 2 and "symlink" in msg
        q.unlink()
        (q.parent / "good.jsonl").rename(q)
        q.parent.chmod(0o755)
        code, msg = run_cli(q, r, ["summary"])
        assert code == 2 and "permission" in msg
        q.parent.chmod(0o700)


def test_review_symlink_refused_no_follow():
    t, q, r = fixture()
    with t:
        target = q.parent / "protected"
        target.write_text("keep", encoding="utf-8")
        target.chmod(0o600)
        r.symlink_to(target)
        code, msg = run_cli(q, r, ["set", "--item", "1", "--state", "TRIAGED", "--priority", "HIGH", "--apply"])
        assert code == 2 and "symlink" in msg
        assert target.read_text(encoding="utf-8") == "keep"


def test_no_remote_github_or_private_beta_write_path_in_module():
    code = Path(review.__file__).read_text(encoding="utf-8")
    assert "urllib" not in code and "requests." not in code and "http.client" not in code
    assert "beta_private_ui_staging_v1" not in code
    assert "/var/lib/jason-os/private-beta-staging" in code
    assert "O_NOFOLLOW" in code
    assert "LOCK_EX" in code
    assert "--apply" in code
    assert "0.0.0.0" not in code


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("KB03 PRIVATE FEEDBACK REVIEW MVP: PASS")


if __name__ == "__main__":
    main()
