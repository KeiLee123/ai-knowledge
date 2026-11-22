#!/usr/bin/env python3
"""Gate 1 join regression: synthetic files + fake Drive, never live services."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import beta_validate_drive_candidate_v1 as module
from test_m10b1_isolated_candidate_v1 import fixture, save
from test_m10_candidate_intake_v1 import SOURCE, make


def setup(base):
    root, summary, records, workspace = fixture(base)
    item = records[SOURCE]
    # Genuine M9 uses the registry document code for its candidate filename.
    new_path = item["candidate"].with_name("APP-149-candidate.pdf")
    item["candidate"].rename(new_path)
    item["candidate"] = new_path
    item["monitor"]["candidate_path"] = str(new_path)
    item["log"].write_text(json.dumps(item["monitor"]), encoding="utf-8")
    return root, summary, item, workspace


def snapshot(*roots):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
            for root in roots if root.exists() for p in root.rglob("*") if p.is_file()}


def invoke(root, summary, workspace, **kwargs):
    return module.run(summary, SOURCE, state_root=root, workspace_root=workspace, **kwargs)


@contextlib.contextmanager
def remote(candidate, *, body=None, after_read=None, missing=False):
    """Exercise the real copy/readback adapter with a fake rclone process."""
    import beta_stage_monitor_candidate_v1 as handoff
    calls = []
    def copy(args, **kwargs):
        assert args[:2] == ["rclone", "copyto"]
        expected = handoff.REMOTE + handoff.PREFIX + SOURCE + "/" + module.sha_file(candidate) + ".pdf"
        assert args[2] == expected, args
        assert Path(args[3]).name == "remote-copy.pdf"
        assert args[4:6] == ["--max-size", str(handoff.MAX_PDF_BYTES)]
        assert kwargs["timeout"] == 60 and kwargs["check"] is True
        calls.append(args)
        if missing:
            raise subprocess.CalledProcessError(1, args, stderr=b"PRIVATE PROVIDER DIAGNOSTIC")
        Path(args[3]).write_bytes(candidate.read_bytes() if body is None else body)
        if after_read:
            after_read()
        return subprocess.CompletedProcess(args, 0)
    with patch.object(module.subprocess, "run", side_effect=copy), \
         patch.object(handoff, "upload_candidate", side_effect=AssertionError("upload forbidden")), \
         patch.object(handoff.writer, "ensure_remote_parent", side_effect=AssertionError("mkdir remote forbidden")), \
         patch.object(handoff.writer, "run_rclone", side_effect=AssertionError("writer forbidden")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("HTTP forbidden")):
        yield calls


def test_default_plan_reads_no_drive_and_creates_no_workspace():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        before = snapshot(root)
        with patch.object(module, "read_existing_drive_candidate", side_effect=AssertionError("no remote")), \
             patch("subprocess.run", side_effect=AssertionError("no subprocess")):
            report = invoke(root, summary, workspace)
        assert report["status"] == "READY_FOR_DRIVE_READBACK", report
        assert report["drive_path"].endswith(report["candidate_sha256"] + ".pdf")
        assert report["drive_readback_verified"] is False
        assert not workspace.exists() and snapshot(root) == before


def test_no_change_never_reads_drive_or_creates_workspace():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, _ = make(Path(temp), decision="NO_CHANGE")
        workspace = Path(temp) / "source-update-validation-staging"
        before = snapshot(root)
        with patch.object(module, "read_existing_drive_candidate", side_effect=AssertionError("no remote")):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "NO_CHANGE", report
        assert not workspace.exists() and snapshot(root) == before


def test_verified_existing_drive_object_to_real_isolated_lexical_and_rerun():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        monitor_before = snapshot(root)
        with remote(item["candidate"]) as calls:
            first = invoke(root, summary, workspace, verify_drive=True, validate=True)
            before_rerun = snapshot(root, workspace)
            second = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert first["status"] == second["status"] == "DRIVE_LINKED_LEXICAL_CANARY_PASSED", first
        assert len(calls) == 2
        assert first["drive_readback"]["sha256"] == first["candidate_sha256"]
        assert first["parse_status"] == "PARSE_VERIFIED" and first["chunk_count"] > 0
        assert first["reference_sha256_before"] == first["reference_sha256_after"]
        assert first["m10b1_evidence_sha256"] == second["m10b1_evidence_sha256"]
        assert snapshot(root) == monitor_before and snapshot(root, workspace) == before_rerun
        assert not Path(calls[0][3]).parent.exists()
        for key in ("production_access", "production_write", "drive_write", "shared_db_access",
                    "canonical_promoted", "canonical_knowledge_updated", "accepted_reference_advanced",
                    "model_api_used", "retrieval_verified", "semantic_verified", "answer_verified", "proof_written"):
            assert first[key] is False, key
        assert first["gold_page_verified"] is None and first["currentness"] == "NOT_VERIFIED"
        assert "snippet" not in json.dumps(first)


def test_drive_verification_only_does_not_parse_or_write_evidence():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        before = snapshot(root)
        with remote(item["candidate"]), \
             patch("extract_document_v2.build_manifest", side_effect=AssertionError("parse not approved")):
            report = invoke(root, summary, workspace, verify_drive=True)
        assert report["status"] == "DRIVE_READBACK_VERIFIED_PARSE_PENDING", report
        assert not workspace.exists() and snapshot(root) == before


def test_missing_or_wrong_remote_blocks_before_parse_and_redacts_stderr():
    for options in ({"missing": True}, {"body": b"%PDF-tampered"}):
        with tempfile.TemporaryDirectory() as temp:
            root, summary, item, workspace = setup(Path(temp))
            with remote(item["candidate"], **options):
                report = invoke(root, summary, workspace, verify_drive=True, validate=True)
            assert report["status"] == "BLOCKED", report
            assert not workspace.exists()
            assert "PRIVATE PROVIDER DIAGNOSTIC" not in json.dumps(report)


def test_local_candidate_tamper_during_readback_prevents_parse():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        def tamper():
            item["candidate"].write_bytes(b"%PDF-tampered")
        with remote(item["candidate"], after_read=tamper):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "BLOCKED" and not workspace.exists(), report


def test_summary_and_reference_drift_during_readback_prevents_parse():
    for target in ("summary", "reference"):
        with tempfile.TemporaryDirectory() as temp:
            root, summary, item, workspace = setup(Path(temp))
            def drift():
                path = summary if target == "summary" else item["ref"]
                data = json.loads(path.read_text())
                if target == "summary":
                    data["git_commit"] = "c" * 40
                else:
                    data["snapshot"]["metadata_fingerprint"] = "d" * 64
                save(path, data)
            with remote(item["candidate"], after_read=drift):
                report = invoke(root, summary, workspace, verify_drive=True, validate=True)
            assert report["status"] == "BLOCKED" and not workspace.exists(), report


def test_registry_drift_during_readback_prevents_parse():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        actual_hash = module.sha_file
        changed = [False]
        def observed_hash(path):
            return "f" * 64 if changed[0] and path == module.isolated.REGISTRY else actual_hash(path)
        with remote(item["candidate"], after_read=lambda: changed.__setitem__(0, True)), \
             patch.object(module, "sha_file", side_effect=observed_hash):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "BLOCKED" and not workspace.exists(), report


def test_multimodal_hold_never_runs_lexical():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        import route_document_v2
        actual = route_document_v2.assess_manifest
        def multimodal(manifest, **kwargs):
            result = actual(manifest, **kwargs)
            result["decision"]["recommended_pipeline"] = "multimodal-v2"
            return result
        with remote(item["candidate"]), \
             patch("route_document_v2.assess_manifest", side_effect=multimodal), \
             patch.object(module.lexical, "run", side_effect=AssertionError("hold cannot search")):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "REVIEW_REQUIRED", report


def test_lexical_failure_does_not_become_success():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        with remote(item["candidate"]), patch.object(module.lexical, "rank_lexical", return_value=[]):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "LEXICAL_CANARY_FAILED", report
        assert report["retrieval_verified"] is False


def test_cached_evidence_from_another_monitor_cannot_join():
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        first = module.isolated.process(summary, SOURCE, state_root=root,
                                        workspace_root=workspace, validate=True)
        assert first["status"] == "PARSE_VERIFIED", first
        path = workspace / "candidates" / SOURCE / first["candidate_sha256"] / "evidence.json"
        data = json.loads(path.read_text())
        data["monitor_output_sha256"] = "f" * 64
        save(path, data)
        with remote(item["candidate"]):
            report = invoke(root, summary, workspace, verify_drive=True, validate=True)
        assert report["status"] == "BLOCKED", report
        assert "parse_binding_mismatch" in report["reasons"][0]


def test_readback_cannot_target_current_or_other_remote():
    import beta_stage_monitor_candidate_v1 as handoff
    with tempfile.TemporaryDirectory() as temp:
        root, summary, item, workspace = setup(Path(temp))
        plan = handoff.plan_candidate(state_root=root, run_dir=item["candidate"].parent,
            source_id=SOURCE, source=handoff.load_source(module.isolated.REGISTRY, SOURCE))
        for key, value in (("drive_path", "Current/APP149.pdf"), ("drive_remote", "other:")):
            changed = dict(plan, **{key: value})
            with patch("subprocess.run", side_effect=AssertionError("unsafe read must not execute")):
                try:
                    module.read_existing_drive_candidate(changed)
                except module.isolated.CandidateError:
                    pass
                else:
                    raise AssertionError("unsafe remote accepted")


def test_cli_requires_separate_flags_and_preserves_failure_exit_codes():
    import beta_stage_monitor_candidate_v1 as handoff
    base = ["--summary", "/tmp/summary.json", "--source", SOURCE]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for flags in (["--validate"], ["--confirm-staging-candidate-write"],
                      ["--validate", "--confirm-staging-candidate-write"],
                      ["--state-root", "/tmp/source-monitor-staging"]):
            try:
                module.main(base + flags)
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError("unsafe CLI accepted")
        with patch.object(handoff, "check_staging_checkout"), patch.object(module, "run") as run:
            for status, code in (("NO_CHANGE", 0), ("READY_FOR_DRIVE_READBACK", 0),
                                 ("DRIVE_LINKED_LEXICAL_CANARY_PASSED", 0),
                                 ("BLOCKED", 2), ("REVIEW_REQUIRED", 3), ("LEXICAL_CANARY_FAILED", 3)):
                run.return_value = {"status": status}
                assert module.main(base) == code


def test_early_lexical_block_preserves_actual_failure_reason():
    # Early lexical failures do not have a reference-after hash yet. They must
    # remain BLOCKED with their own cause, rather than a fabricated mismatch.
    sha = "a" * 64
    plan = dict(status="READY_FOR_PARSE", reasons=[], source_id=SOURCE,
                candidate_id=SOURCE + ":" + sha, candidate_sha256=sha,
                reference_sha256_before="b" * 64, monitor_output_sha256="c" * 64,
                monitor_run_id="run", batch_timestamp="batch", trusted_identity={})
    drive_plan = dict(status="READY_FOR_VERSIONED_DRIVE_STAGING",
                      candidate_sha256=sha, candidate_size_bytes=123,
                      drive_remote="unused:", drive_path="unused")
    item = dict(status="READY_FOR_STAGING_VALIDATION",
                candidate_id=plan["candidate_id"],
                monitor_output_sha256=plan["monitor_output_sha256"],
                candidate={"path": "candidate.pdf",
                           "accepted_reference_record_sha256": plan["reference_sha256_before"]})
    handoff = SimpleNamespace(load_source=lambda *args: {},
                              plan_candidate=lambda **kwargs: drive_plan)
    def process(*args, validate=False, **kwargs):
        return dict(plan, status="PARSE_VERIFIED" if validate else "READY_FOR_PARSE")
    with patch.dict(module.sys.modules, {"beta_stage_monitor_candidate_v1": handoff}), \
         patch.object(module, "validate_root", return_value=Path("fixture")), \
         patch.object(module.isolated, "workspace_scope", return_value=Path("workspace")), \
         patch.object(module.isolated, "process", side_effect=process), \
         patch.object(module, "sha_file", return_value="d" * 64), \
         patch.object(module, "inspect_batch", return_value={"results": [item]}), \
         patch.object(module, "read_existing_drive_candidate", return_value={"sha256": sha, "bytes": 123}), \
         patch.object(module.lexical, "candidate_paths", side_effect=AssertionError("blocked evidence cannot be joined")):
        for reason in ("unsafe_candidate_artifact", "manifest_hash_or_parser_drift"):
            blocked = module.lexical.report_base(SOURCE, sha)
            blocked["reasons"] = ["candidate_lexical_failed:CandidateError:" + reason]
            with patch.object(module.lexical, "run", return_value=blocked):
                report = module.run(Path("summary.json"), SOURCE,
                                    verify_drive=True, validate=True)
            assert report["status"] == "BLOCKED", report
            assert report["reasons"] == blocked["reasons"], report
            assert report["lexical_status"] == "BLOCKED", report
            assert report["parse_status"] == "PARSE_VERIFIED", report
            assert report["answer_verified"] is False


def main():
    cases = sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v))
    for name, test in cases:
        test()
        print(name + ": PASS")
    print("BETA DRIVE CANDIDATE TO ISOLATED VALIDATION: PASS")


if __name__ == "__main__":
    main()
