#!/usr/bin/env python3
"""Beta Gate 1 integration contract: M9 log shape -> versioned Drive sink."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import beta_stage_monitor_candidate_v1 as m

SOURCE = "BD_PNAP_APP149"
STAMP = "20261031T064000Z"
BLOB = b"%PDF-1.7\nsynthetic source change, NOT a real government document\n%%EOF"
SOURCE_CONFIG = {"document_code": "APP-149",
                 "canonical_url": "https://www.bd.gov.hk/doc/APP149.pdf"}


def fixture(tmp, *, status="CANDIDATE_NEW_VERSION", body=BLOB):
    root = Path(tmp) / "state"
    run = root / "runs" / SOURCE / STAMP
    run.mkdir(parents=True)
    sha = hashlib.sha256(body).hexdigest()
    candidate = run / "APP-149-candidate.pdf"
    if status != "UNCHANGED":
        candidate.write_bytes(body)
    outcome = {"version": "official-source-monitor-v1", "source_id": SOURCE,
               "production_access": False, "production_write": False,
               "baseline_status": "DOCUMENT_CHANGED", "decision": status,
               "action": "STAGING_VALIDATION_REQUIRED",
               "candidate_downloaded": True, "candidate_path": str(candidate),
               "candidate_sha256": sha}
    if status == "UNCHANGED":
        outcome.update(baseline_status="UNCHANGED", action="NONE",
                       candidate_downloaded=False)
        outcome.pop("candidate_path")
        outcome.pop("candidate_sha256")
    (run / "monitor-output.txt").write_text(
        "=== M9 STAGING RUN ===\nrun_dir=" + str(run) + "\n" +
        json.dumps(outcome, indent=2) + "\nSTATUS: RUN_COMPLETE\n",
        encoding="utf-8")
    return root, run, outcome


def rejects(fn, contains=None):
    try:
        fn()
    except m.HandoffRefused as e:
        if contains:
            assert contains in str(e), (contains, e)
        return
    raise AssertionError("unsafe candidate accepted")


def plan(root, run):
    return m.plan_candidate(state_root=root, run_dir=run, source_id=SOURCE,
                            source=SOURCE_CONFIG)


def update_monitor(run, outcome):
    (run / "monitor-output.txt").write_text(
        "run_dir=" + str(run) + "\n" + json.dumps(outcome) + "\n",
        encoding="utf-8")


def test_real_m9_log_shape_produces_content_addressed_staging_plan():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        output = plan(root, run)
        assert output["status"] == "READY_FOR_VERSIONED_DRIVE_STAGING"
        assert output["candidate_sha256"] == hashlib.sha256(BLOB).hexdigest()
        assert output["drive_path"].startswith("_Staging_Incoming/APP/_versioned_candidates/BD_PNAP_APP149/")
        assert output["drive_path"].endswith(output["candidate_sha256"] + ".pdf")
        assert not output["write_authorized"]
        assert output["staging_validation_completed"] is False
        assert output["canonical_current_updated"] is False
        assert output["production_write"] is False


def test_no_change_is_noop_without_candidate_or_remote_calls():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp, status="UNCHANGED")
        with patch.object(m.writer, "run_rclone", side_effect=AssertionError("no rclone")), \
             patch.object(m.writer, "remote_file_exists", side_effect=AssertionError("no remote")):
            output = plan(root, run)
        assert output["status"] == "NO_CHANGE"
        assert not output["write_authorized"]


def test_changed_candidate_with_other_decision_never_uploads():
    for status, action in (("EXCEPTION_REVIEW", "EXCEPTION_REVIEW"),
                           ("POLICY_BLOCKED", "STOP"),
                           ("UNCHANGED", "NONE")):
        with tempfile.TemporaryDirectory() as tmp:
            root, run, result = fixture(tmp)
            result["decision"], result["action"] = status, action
            update_monitor(run, result)
            rejects(lambda: plan(root, run), "candidate_requires_separate_review")


def test_false_or_missing_production_flags_fail_closed():
    for key, value in (("production_write", True),
                       ("production_access", None),
                       ("production_access", "false")):
        with tempfile.TemporaryDirectory() as tmp:
            root, run, result = fixture(tmp)
            result[key] = value
            update_monitor(run, result)
            rejects(lambda: plan(root, run), "production_flag_refused")


def test_candidate_sha_mismatch_rejected_before_remote():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        (run / "APP-149-candidate.pdf").write_bytes(BLOB + b"corruption")
        rejects(lambda: plan(root, run), "candidate_sha_mismatch")


def test_nonpdf_or_oversized_candidate_refused():
    for data in (b"not a pdf", BLOB + b"z" * 100):
        with tempfile.TemporaryDirectory() as tmp:
            root, run, _ = fixture(tmp, body=data)
            with patch.object(m, "MAX_PDF_BYTES", 100):
                rejects(lambda: plan(root, run))


def test_symlink_to_candidate_or_log_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        path = run / "APP-149-candidate.pdf"
        target = run / "alternate.pdf"
        path.rename(target)
        path.symlink_to(target)
        rejects(lambda: plan(root, run), "symlink_refused")
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        path = run / "monitor-output.txt"
        target = run / "alternate.txt"
        path.rename(target)
        path.symlink_to(target)
        rejects(lambda: plan(root, run), "symlink_refused")


def test_source_and_run_location_crossing_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, result = fixture(tmp)
        result["source_id"] = "BD_PNAP_APP145"
        update_monitor(run, result)
        rejects(lambda: plan(root, run), "monitor_identity_mismatch")
        rejects(lambda: m.plan_candidate(state_root=root, run_dir=run,
                                         source_id="BD_PNAP_APP145",
                                         source=SOURCE_CONFIG), "unexpected_source_or_run_stamp")
        rejects(lambda: m.plan_candidate(state_root=root, run_dir=run.parent,
                                         source_id=SOURCE, source=SOURCE_CONFIG),
                "invalid_monitor_run_location")


def test_candidate_path_from_another_run_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, result = fixture(tmp)
        result["candidate_path"] = str(run.parent / "another" / "APP-149-candidate.pdf")
        update_monitor(run, result)
        rejects(lambda: plan(root, run), "candidate_location_mismatch")


def test_bad_or_missing_monitor_output_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        (run / "monitor-output.txt").write_text("missing JSON", encoding="utf-8")
        rejects(lambda: plan(root, run), "missing_monitor_result")
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        (run / "monitor-output.txt").write_text("x" * (2 * 1024 * 1024 + 1))
        rejects(lambda: plan(root, run), "invalid_monitor_log")


def fake_remote():
    remote_data = {}
    operations = []
    def exists(remote, dest):
        assert remote == m.REMOTE
        return (remote + dest) in remote_data
    def parent(remote, dest):
        assert remote == m.REMOTE
        assert dest.startswith(m.PREFIX)
        operations.append("mkdir")
    def rclone(args):
        assert args[0] == "copyto"
        src, dest = args[1:3]
        if src.startswith(m.REMOTE):
            Path(dest).write_bytes(remote_data[src])
            operations.append("readback")
        else:
            assert args[3:] == ["--immutable"]
            if dest in remote_data and remote_data[dest] != Path(src).read_bytes():
                raise RuntimeError("immutable conflict")
            remote_data[dest] = Path(src).read_bytes()
            operations.append("upload")
        return ""
    return remote_data, operations, exists, parent, rclone


def test_real_upload_interface_roundtrip_and_idempotent_rerun():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        p = plan(root, run)
        items, ops, exists, parent, cmd = fake_remote()
        with patch.object(m.writer, "remote_file_exists", side_effect=exists), \
             patch.object(m.writer, "ensure_remote_parent", side_effect=parent), \
             patch.object(m.writer, "run_rclone", side_effect=cmd):
            first = m.upload_candidate(p)
            second = m.upload_candidate(p)
        assert first["status"] == "STAGED_AND_VERIFIED"
        assert second["status"] == "ALREADY_STAGED_VERIFIED"
        assert ops.count("upload") == 1 and ops.count("readback") == 2
        assert len(items) == 1
        assert first["sha256"] == hashlib.sha256(BLOB).hexdigest()
        assert not first["canonical_current_updated"]
        assert not first["reference_advanced"]
        assert not first["staging_validation_completed"]


def test_preexisting_remote_mismatch_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        p = plan(root, run)
        items, ops, exists, parent, cmd = fake_remote()
        items[m.REMOTE + p["drive_path"]] = b"%PDF-malicious-content"
        with patch.object(m.writer, "remote_file_exists", side_effect=exists), \
             patch.object(m.writer, "ensure_remote_parent", side_effect=parent), \
             patch.object(m.writer, "run_rclone", side_effect=cmd):
            rejects(lambda: m.upload_candidate(p), "drive_roundtrip_mismatch")
        assert "upload" not in ops


def test_tampered_local_after_plan_is_blocked_before_rclone():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        p = plan(root, run)
        (run / "APP-149-candidate.pdf").write_bytes(BLOB + b"bad")
        with patch.object(m.writer, "run_rclone", side_effect=AssertionError("no upload")):
            rejects(lambda: m.upload_candidate(p), "candidate_changed_before_upload")


def test_edited_plan_cannot_write_current_or_other_remote():
    with tempfile.TemporaryDirectory() as tmp:
        root, run, _ = fixture(tmp)
        p = plan(root, run)
        for key, value in (("drive_path", "Current/APP/APP149.pdf"),
                           ("drive_path", m.PREFIX + "../Current/a.pdf"),
                           ("drive_remote", "gdrive-out:"),
                           ("source_id", "BD_PNAP_APP145")):
            changed = dict(p)
            changed[key] = value
            rejects(lambda: m.upload_candidate(changed))


def test_checkout_guard_rejects_non_staging_path_before_git():
    with patch.object(m.subprocess, "run", side_effect=AssertionError("no git")):
        rejects(lambda: m.check_staging_checkout(Path("/opt/ai-knowledge")),
                "not_the_staging_checkout")


def test_actual_registry_has_only_safe_staging_writer():
    reg = Path(__file__).resolve().parent / "source_registry_v1.yaml"
    source = m.load_source(reg, SOURCE)
    assert source["document_code"] == "APP-149"
    assert source["drive_writer"]["remote"] == m.REMOTE
    assert source["drive_writer"]["allow_overwrite"] is False
    assert source["canonical_promotion"]["trigger_ingestion"] is False
    try:
        m.load_source(reg, "UNKNOWN")
    except (KeyError, RuntimeError, ValueError):
        pass
    else:
        raise AssertionError("unregistered source accepted")


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("BETA GATE 1 M9 → VERSIONED DRIVE STAGING HANDOFF: PASS")


if __name__ == "__main__":
    main()
