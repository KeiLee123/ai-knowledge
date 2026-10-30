#!/usr/bin/env python3
"""M10B-2B-1: read-only local Embedding endpoint discovery (NO HTTP).

Never contact /embed, inspect environment variables, read process commands,
read logs, open model files, access a DB, or change services. This is
an evidence inventory, NOT security approval to send candidate content.
"""
import argparse
import json
import re
import subprocess
import sys

AUDIT_VERSION = "m10b2b1-readonly-endpoint-audit-v1"
PORT = 8088
LOCAL_HOSTS = {"127.0.0.1", "::1"}
SERVICE_PATTERN = re.compile(
    r"embed|(^|[^a-z])tei([^a-z]|$)|inference|huggingface|transformer",
    re.IGNORECASE,
)
# Docker commands explicitly use the local Unix socket: DOCKER_HOST cannot
# redirect this audit to an unapproved remote Docker daemon.
DOCKER_LOCAL = ("docker", "--host", "unix:///var/run/docker.sock")


def command_result(args):
    """Fixed commands only; no shell, no stdin, no raw stderr in report."""
    try:
        response = subprocess.run(
            list(args), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=8,
            shell=False, check=False,
        )
        return (response.returncode, response.stdout[:250_000])
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired,
            OSError):
        return (None, "")


def parse_ss(text):
    """Extract only listening host, process name and PID, never full command."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "LISTEN":
            continue
        local = parts[3]
        try:
            host, port = local.rsplit(":", 1)
        except ValueError:
            continue
        if port != str(PORT):
            continue
        host = host.strip("[]")
        # Refuse to treat unfamiliar bind forms as private/loopback.
        is_loopback = host in LOCAL_HOSTS
        process_match = re.search(
            r'users:\(\("([^"\\]{1,80})",pid=(\d{1,12})', line
        )
        out.append({
            "bound_host": host[:90],
            "port": PORT,
            "scope": "loopback" if is_loopback else "non_loopback_or_unknown",
            "process_name": process_match.group(1) if process_match else None,
            "pid": int(process_match.group(2)) if process_match else None,
        })
    # Stable, deduplicated observations; a proxy may expose the same port.
    seen, ordered = set(), []
    for item in out:
        key = (item["bound_host"], item["pid"], item["process_name"])
        if key not in seen:
            seen.add(key)
            ordered.append(item)
    return sorted(ordered, key=lambda x: (x["bound_host"], x["pid"] or -1))


def parse_systemd(text):
    results = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].endswith(".service"):
            continue
        name = fields[0]
        if SERVICE_PATTERN.search(name):
            results.append({
                "unit": name[:150],
                "load": fields[1],
                "active": fields[2],
                "sub": fields[3],
            })
    return results[:20]


def parse_docker(text):
    """Docker ps exposes safe metadata, never inspect Config.Env."""
    results = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        cid, name, image, ports = fields
        if not (str(PORT) in ports or SERVICE_PATTERN.search(name) or
                SERVICE_PATTERN.search(image)):
            continue
        if not re.fullmatch(r"[0-9a-f]{12,64}", cid):
            continue
        results.append({
            "container_id_short": cid[:12],
            "name": name[:120],
            "image": image[:180],
            "published_ports": ports[:250],
        })
    return results[:20]


def parse_docker_inspect(text):
    # Only an exact, restricted Go template; no environment or mounts.
    fields = text.strip().split("|")
    if len(fields) != 4:
        return None
    mode, logdriver, readonly, pid = fields
    if not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,90}", mode):
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,60}", logdriver):
        return None
    if readonly not in ("true", "false") or not pid.isdecimal():
        return None
    return {
        "network_mode": mode,
        "log_driver_type": logdriver,
        "read_only_root_fs": readonly == "true",
        "pid": int(pid),
    }


def audit(*, runner=command_result):
    report = {
        "version": AUDIT_VERSION,
        "environment": "staging-host-observation",
        "configured_endpoint": "http://127.0.0.1:8088/embed",
        "embedding_api_called": False,
        "embedding_requests": 0,
        "network_probe_performed": False,
        "secrets_or_environment_read": False,
        "logs_or_model_files_read": False,
        "db_access": False,
        "service_mutations": False,
        "file_writes": False,
        "approval_to_send_pdf": False,
        "approval_to_send_query": False,
        "model_identity_verified": False,
        "model_revision_verified": False,
        "tokenizer_verified": False,
        "egress_and_telemetry_verified": False,
        "data_retention_verified": False,
        "deployment_isolation_verified": False,
        "proxy_redirect_policy_verified": False,
        "manual_review_needed": [
            "model_identity_revision_and_digest",
            "tokenizer_token_budget_and_query_passage_prefix",
            "outbound_egress_and_telemetry",
            "request_logging_and_retention",
            "container_or_process_ownership_and_staging_isolation",
            "proxy_redirect_and_http_request_limits",
        ],
    }

    ss_code, ss_text = runner(
        ("ss", "-H", "-ltnp", "( sport = :8088 )")
    )
    listeners = parse_ss(ss_text) if ss_code == 0 else []
    report["listener_inventory"] = {
        "command_succeeded": ss_code == 0,
        "listeners": listeners,
    }
    if ss_code != 0:
        report["status"] = "AUDIT_INCOMPLETE"
        report["exit_code"] = 4
    elif not listeners:
        report["status"] = "NO_LISTENER_OBSERVED"
        report["exit_code"] = 3
    elif any(x["scope"] != "loopback" for x in listeners):
        report["status"] = "BIND_EXPOSURE_RISK"
        report["exit_code"] = 2
    else:
        report["status"] = "LOOPBACK_BIND_OBSERVED_NOT_APPROVED"
        report["exit_code"] = 0

    systemd_code, systemd_text = runner((
        "systemctl", "list-units", "--all", "--type=service",
        "--no-legend", "--no-pager", "--plain",
    ))
    report["systemd_inventory"] = {
        "command_succeeded": systemd_code == 0,
        "matching_services": parse_systemd(systemd_text)
        if systemd_code == 0 else [],
    }

    docker_code, docker_text = runner(DOCKER_LOCAL + (
        "ps", "--no-trunc", "--format",
        "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}",
    ))
    containers = parse_docker(docker_text) if docker_code == 0 else []
    for entry in containers:
        # All Docker inspect data are selected from a fixed SAFE metadata
        # template. In particular, NEVER return Config.Env or command args.
        c, raw = runner(DOCKER_LOCAL + (
            "inspect", "--type", "container", "--format",
            "{{.HostConfig.NetworkMode}}|{{.HostConfig.LogConfig.Type}}|"
            "{{.HostConfig.ReadonlyRootfs}}|{{.State.Pid}}",
            entry["container_id_short"],
        ))
        entry["runtime_metadata"] = (
            parse_docker_inspect(raw) if c == 0 else None
        )
    report["docker_inventory"] = {
        "command_succeeded": docker_code == 0,
        "matching_containers": containers,
    }
    report["inventory_completeness"] = (
        "partial" if systemd_code != 0 or docker_code != 0
        else "discovery_commands_succeeded"
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)  # No URL, PDF, secrets or output-path arguments.
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
