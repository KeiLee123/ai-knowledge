#!/usr/bin/env python3
"""Offline regressions for the non-invasive M10B-2B-1 endpoint audit."""
import contextlib
import io
from unittest.mock import patch

from ops.audit_embedding_endpoint_staging_v1 import (
    AUDIT_VERSION, DOCKER_LOCAL, audit, main, parse_docker,
    parse_docker_inspect, parse_ss, parse_systemd,
)

SS_LOOPBACK = (
    'LISTEN 0 4096 127.0.0.1:8088 0.0.0.0:* '
    'users:(("python3",pid=12345,fd=7))\n'
)
SS_IPV6 = (
    'LISTEN 0 4096 [::1]:8088 [::]:* '
    'users:(("embed",pid=99,fd=8))\n'
)
SS_EXPOSED = (
    'LISTEN 0 4096 0.0.0.0:8088 0.0.0.0:* '
    'users:(("server",pid=77,fd=8))\n'
)
DOCKER_PS = (
    "f" * 64 + "\tembedding-tei\ttei:test-model\t127.0.0.1:8088->80/tcp\n"
    + "a" * 64 + "\tpostgres-db\tpostgres:16\t127.0.0.1:5433->5432/tcp\n"
)
SYSTEMD = (
    "embedding-staging.service loaded active running local-embed\n"
    "ssh.service loaded active running ssh\n"
)


class FakeRunner:
    def __init__(self, ss=(0, SS_LOOPBACK),
                 docker=(0, DOCKER_PS), systemd=(0, SYSTEMD),
                 inspect=(0, "bridge|json-file|false|5123\n")):
        self.ss, self.docker, self.systemd, self.inspect = (
            ss, docker, systemd, inspect
        )
        self.calls = []

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args[0] == "ss":
            return self.ss
        if args[0] == "systemctl":
            return self.systemd
        if args[:3] == DOCKER_LOCAL and args[3] == "ps":
            return self.docker
        if args[:3] == DOCKER_LOCAL and args[3] == "inspect":
            return self.inspect
        raise AssertionError(f"unexpected external command: {args}")


def test_loopback_observed_but_never_approved():
    runner = FakeRunner()
    result = audit(runner=runner)
    assert result["version"] == AUDIT_VERSION
    assert result["status"] == "LOOPBACK_BIND_OBSERVED_NOT_APPROVED"
    assert result["exit_code"] == 0
    assert result["approval_to_send_pdf"] is False
    assert result["approval_to_send_query"] is False
    assert result["model_identity_verified"] is False
    assert result["egress_and_telemetry_verified"] is False
    assert result["data_retention_verified"] is False
    assert result["deployment_isolation_verified"] is False
    assert result["embedding_api_called"] is False
    assert result["embedding_requests"] == 0
    assert result["file_writes"] is False
    assert result["db_access"] is False
    assert result["logs_or_model_files_read"] is False
    assert result["secrets_or_environment_read"] is False
    assert result["listener_inventory"]["listeners"][0]["pid"] == 12345
    matches = result["docker_inventory"]["matching_containers"]
    assert len(matches) == 1
    assert matches[0]["name"] == "embedding-tei"
    assert matches[0]["runtime_metadata"] == {
        "network_mode": "bridge",
        "log_driver_type": "json-file",
        "read_only_root_fs": False,
        "pid": 5123,
    }
    assert len(result["systemd_inventory"]["matching_services"]) == 1
    assert result == audit(runner=FakeRunner())


def test_ipv6_loopback_only_is_not_an_exposure():
    result = audit(runner=FakeRunner(ss=(0, SS_LOOPBACK + SS_IPV6)))
    assert result["status"] == "LOOPBACK_BIND_OBSERVED_NOT_APPROVED"
    assert len(result["listener_inventory"]["listeners"]) == 2
    assert [r["scope"] for r in result["listener_inventory"]["listeners"]] == [
        "loopback", "loopback",
    ]


def test_wildcard_exposed_is_security_risk():
    for listen in (SS_EXPOSED,
                   'LISTEN 0 50 [::]:8088 [::]:* users:(("api",pid=1,fd=4))\n',
                   'LISTEN 0 50 192.0.2.4:8088 0.0.0.0:* \n'):
        report = audit(runner=FakeRunner(ss=(0, listen)))
        assert report["status"] == "BIND_EXPOSURE_RISK", report
        assert report["exit_code"] == 2
        assert report["approval_to_send_pdf"] is False


def test_mixed_listeners_exposure_is_not_downgraded():
    report = audit(runner=FakeRunner(ss=(0, SS_LOOPBACK + SS_EXPOSED)))
    assert report["status"] == "BIND_EXPOSURE_RISK"
    assert len(report["listener_inventory"]["listeners"]) == 2


def test_absent_listener_is_not_approval():
    report = audit(runner=FakeRunner(ss=(0, "")))
    assert report["status"] == "NO_LISTENER_OBSERVED"
    assert report["exit_code"] == 3


def test_ss_failure_fails_closed():
    for code in (None, 1, 127):
        report = audit(runner=FakeRunner(ss=(code, SS_LOOPBACK)))
        assert report["status"] == "AUDIT_INCOMPLETE"
        assert report["exit_code"] == 4
        assert report["listener_inventory"]["listeners"] == []


def test_missing_docker_systemd_marks_partial_but_no_approval():
    report = audit(runner=FakeRunner(docker=(None, ""),
                                     systemd=(1, "")))
    assert report["status"] == "LOOPBACK_BIND_OBSERVED_NOT_APPROVED"
    assert report["inventory_completeness"] == "partial"
    assert report["docker_inventory"]["command_succeeded"] is False
    assert report["systemd_inventory"]["command_succeeded"] is False
    assert report["approval_to_send_query"] is False


def test_unexpected_and_unrelated_metadata_not_disclosed():
    assert parse_docker(DOCKER_PS)[0]["name"] == "embedding-tei"
    assert len(parse_docker(DOCKER_PS)) == 1
    assert parse_systemd(SYSTEMD) == [
        {"unit": "embedding-staging.service", "load": "loaded",
         "active": "active", "sub": "running"},
    ]
    assert parse_docker_inspect("bridge|json-file|false|5123")["pid"] == 5123
    assert parse_docker_inspect("bridge|json-file|maybe|5123") is None
    assert parse_docker_inspect("bridge|json-file|false|not-a-pid") is None
    assert parse_ss("LISTEN 0 4096 127.0.0.1:5433 0.0.0.0:*\n") == []


def test_fixed_safe_commands_only():
    runner = FakeRunner()
    audit(runner=runner)
    assert runner.calls[0] == ("ss", "-H", "-ltnp",
                               "( sport = :8088 )")
    assert runner.calls[1][:2] == ("systemctl", "list-units")
    assert runner.calls[2][:4] == DOCKER_LOCAL + ("ps",)
    assert runner.calls[3][:4] == DOCKER_LOCAL + ("inspect",)
    allowed = {"ss", "systemctl", "docker"}
    assert all(c[0] in allowed for c in runner.calls)
    assert all("http://" not in " ".join(c) for c in runner.calls)
    assert all("--env" not in " ".join(c) and "Config.Env" not in " ".join(c)
               and "Environment" not in " ".join(c)
               and "logs" not in c and "curl" not in c
               and "exec" not in c for c in runner.calls)
    assert not any(c[0] in {"ps", "cat", "find", "curl", "python", "wget"}
                   for c in runner.calls)


def test_no_hidden_network_or_logs_during_audit():
    runner = FakeRunner()
    with patch("urllib.request.urlopen",
               side_effect=AssertionError("HTTP probe forbidden")), \
         patch("socket.create_connection",
               side_effect=AssertionError("TCP connection forbidden")):
        audit(runner=runner)
    assert runner.calls


def test_report_never_claims_verified_model_or_network():
    runner = FakeRunner()
    r = audit(runner=runner)
    for key in ("model_identity_verified", "model_revision_verified",
                "tokenizer_verified", "egress_and_telemetry_verified",
                "data_retention_verified", "deployment_isolation_verified",
                "proxy_redirect_policy_verified"):
        assert r[key] is False


def test_cli_json_and_status_exit_code():
    runner = FakeRunner()
    buf = io.StringIO()
    with patch("ops.audit_embedding_endpoint_staging_v1.command_result",
               side_effect=runner):
        with contextlib.redirect_stdout(buf):
            assert main([]) == 0
    import json
    obj = json.loads(buf.getvalue())
    assert obj["status"] == "LOOPBACK_BIND_OBSERVED_NOT_APPROVED"
    assert obj["approval_to_send_pdf"] is False
    assert obj["embedding_requests"] == 0


def main_test():
    tests = [
        test_loopback_observed_but_never_approved,
        test_ipv6_loopback_only_is_not_an_exposure,
        test_wildcard_exposed_is_security_risk,
        test_mixed_listeners_exposure_is_not_downgraded,
        test_absent_listener_is_not_approval,
        test_ss_failure_fails_closed,
        test_missing_docker_systemd_marks_partial_but_no_approval,
        test_unexpected_and_unrelated_metadata_not_disclosed,
        test_fixed_safe_commands_only,
        test_no_hidden_network_or_logs_during_audit,
        test_report_never_claims_verified_model_or_network,
        test_cli_json_and_status_exit_code,
    ]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("M10B-2B-1 read-only endpoint audit regression: PASS")


if __name__ == "__main__":
    main_test()
