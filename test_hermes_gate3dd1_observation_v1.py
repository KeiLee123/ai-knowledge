#!/usr/bin/env python3
"""Offline unit tests for Gate 3D-D1; no Docker, credentials or API calls."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "hermes_gate3dd1_observe_staging.py"
COMMIT = "33cc34e86471aef0393ec22c201ce81b0aea353e"


def module():
    spec = importlib.util.spec_from_file_location("gate3dd1_observer", SCRIPT)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def fake_output(mod, mode):
    return "\n".join(mod.REQUIRED[mode]) + "\n"


class Completed:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = "DO_NOT_LOG_UNTRUSTED_STDERR"


def test_gate_markers(mod):
    for mode in ("preflight", "run_once"):
        good = fake_output(mod, mode)
        assert mod.evaluate_gate(mode, 0, good) == (True, "verified")
        assert mod.evaluate_gate(mode, 0, good + mod.REQUIRED[mode][0]) == (
            False, "gate_markers_missing"
        )
        for marker in mod.REQUIRED[mode]:
            missing = good.replace(marker + "\n", "")
            assert mod.evaluate_gate(mode, 0, missing)[0] is False, marker
        assert mod.evaluate_gate(mode, 1, good)[0] is False
        assert mod.evaluate_gate(
            mode, 0, good + "GATE 3D-C STOPPED: RuntimeError\n"
        ) == (False, "gate_stopped")
        assert mod.evaluate_gate(mode, 0, "x" * (mod.MAX_CAPTURE_CHARS + 1)) == (
            False, "capture_oversize"
        )
    missing_result = ("Actual MCP dispatch: mcp_tool_result_not_approved_snapshot\n"
                      + fake_output(mod, "run_once"))
    assert mod.evaluate_gate("run_once", 1, missing_result) == (
        False, "mcp_tool_result_not_approved_snapshot"
    )
    assert mod.evaluate_gate("run_once", 1,
                             "Actual MCP dispatch: TOKEN_LEAK\n")[1] == (
        "gate_process_failed"
    )
    print("Gate 3D-D1 exact marker fail-closed: PASS")


def test_one_subprocess_per_trial(mod):
    for mode in ("preflight", "run_once"):
        calls = []
        sensitive = "DO_NOT_OUTPUT_SECRET_KEY_123"
        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return Completed(fake_output(mod, mode) + sensitive)
        record = mod.execute(mode, runner=runner, commit=COMMIT)
        assert record["status"] == "PASS"
        assert record["reason_code"] == "verified"
        assert len(calls) == 1
        assert calls[0][0] == [
            "bash", str(mod.GATE_SHELL),
            "--preflight" if mode == "preflight" else "--run",
        ]
        assert calls[0][1]["capture_output"] is True
        assert calls[0][1]["timeout"] == 240
        assert sensitive not in json.dumps(record)
        assert record["human_legal_review"] == "REQUIRED"
    calls = []
    def timeout_runner(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
    timed_out = mod.execute("run_once", runner=timeout_runner, commit=COMMIT)
    assert len(calls) == 1
    assert timed_out["status"] == "FAIL"
    assert timed_out["reason_code"] == "trial_timeout"
    print("Gate 3D-D1 one-call limit, timeout, redaction: PASS")


def test_report_contract(mod):
    def rec(n, passed=True):
        return mod.short_record(
            "run_once", COMMIT, passed,
            "verified" if passed else "mcp_tool_result_not_approved_snapshot",
            1435, trial_id=("%032x" % n), at="2026-10-31T12:00:00+00:00",
        )
    sample = [rec(1), rec(2), rec(3)]
    report = mod.summarize_records(sample)
    assert report["sample_count"] == 3
    assert report["passed"] == 3 and report["failed"] == 0
    assert report["sample_sufficient_for_d1_mvp"] is True
    assert report["production_promotion"] == "NOT_AUTHORIZED"
    assert mod.summarize_records(sample[:2])["sample_sufficient_for_d1_mvp"] is False
    one_failed = mod.summarize_records([rec(1), rec(2), rec(3, False)])
    assert one_failed["observed_pass_rate"] == round(2 / 3, 4)
    assert one_failed["failure_reason_counts"] == {
        "mcp_tool_result_not_approved_snapshot": 1
    }
    def rejected(items):
        try:
            mod.summarize_records(items)
        except ValueError:
            return
        raise AssertionError("invalid metadata ledger accepted")
    rejected([rec(1), rec(1)])
    other_commit = rec(3)
    other_commit["staging_commit"] = "0" * 40
    rejected([rec(1), other_commit])
    invalid = rec(1)
    invalid["content"] = "PRIVATE_MODEL_RESPONSE"
    rejected([invalid])
    invalid = rec(1)
    invalid["status"] = "PASS"
    invalid["reason_code"] = "gate_stopped"
    rejected([invalid])
    invalid = rec(1)
    invalid["status"] = "FAIL"
    invalid["reason_code"] = "UNTRUSTED_ARBITRARY_TEXT"
    rejected([invalid])
    rejected([mod.short_record(
        "preflight", COMMIT, True, "verified", 7,
        trial_id="%032x" % 42, at="2026-10-31T12:00:00+00:00")])
    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "trial-metadata.jsonl"
        ledger.write_text("\n".join(json.dumps(x) for x in sample) + "\n")
        assert mod.read_ledger(ledger) == sample
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--report", str(ledger)])
        assert rc == 0 and json.loads(buf.getvalue())["passed"] == 3
        ledger.write_text(json.dumps({**rec(1), "raw_answer": "SECRET"}) + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--report", str(ledger)])
        assert rc == 1
        assert "SECRET" not in buf.getvalue()
        assert json.loads(buf.getvalue())["status"] == "REFUSED"
    print("Gate 3D-D1 bounded metadata report and refusal: PASS")


def test_explicit_paid_call_ack():
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-once"],
        capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 2
    assert "--ack-public-api-call" in process.stderr
    assert "DeepSeek credential" not in process.stdout
    print("Gate 3D-D1 live-run explicit acknowledgement: PASS")


def main():
    mod = module()
    test_gate_markers(mod)
    test_one_subprocess_per_trial(mod)
    test_report_contract(mod)
    test_explicit_paid_call_ack()
    print("HERMES GATE 3D-D1 OBSERVATION OFFLINE: PASS")


if __name__ == "__main__":
    main()
