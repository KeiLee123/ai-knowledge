# M10B-2B-1 — Read-only Local Embedding Endpoint Audit v0.1

**Scope: discovery only. Nothing calls the Embedding API, sends a PDF, or approves access to a model.**

Architecture: https://docs.google.com/document/d/1togruRi30usv0TEilCIBYxAwtbaaR5t2prb-6pQj1pE/edit

## Architecture and decision

Current repository configuration references `http://127.0.0.1:8088/embed`, `multilingual-e5-small`, and 384-dimensional vectors in `validate_staging_retrieval_v2.py` and `benchmark_multimodal_retrieval_v2.py`. These are **configured expectations**, not evidence that a trustworthy private endpoint is running. The existing validator accesses shared staging DB via Docker and cannot be reused for isolated candidate validation.

M10B-2B-1 first performs a passive host metadata inventory. It is **not** the live Embedding Adapter, and it will not certify that any candidate PDF is safe to send. GitHub feature branch -> staging PR/CI -> VPS Staging passive audit -> manual evaluation of missing model and egress controls -> separate adapter milestone.

## CLI (after pinned GitHub staging acceptance)

```bash
cd /opt/ai-knowledge-staging
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python ops/audit_embedding_endpoint_staging_v1.py
```

The only commands the script launches are:

- `ss -H -ltnp "( sport = :8088 )"`: passive kernel socket inventory for port 8088; outputs only listener bind address and process name/PID. **No TCP connection is initiated.**
- `systemctl list-units --all --type=service --no-legend --no-pager --plain`: passive list of matching service names/state.
- `docker --host unix:///var/run/docker.sock ps --no-trunc --format ...`: reads local Docker daemon metadata only; filters to embedding-related containers or host port 8088.
- For matching Docker containers, `docker --host unix:///var/run/docker.sock inspect --type container --format ...`: **only fixed safe fields** HostConfig.NetworkMode, HostConfig.LogConfig.Type, HostConfig.ReadonlyRootfs and State.Pid. It never obtains Config.Env, mounts, command arguments, logs, Docker credentials or secret values.

The script never executes curl/wget, calls the /embed HTTP endpoint, connects to any URL, reads process environment or command line, displays log content, accesses database, calls external Vision, changes systemd/Docker services, or writes audit output to files. It prints a bounded stdout JSON summary. Since Docker's Unix socket grants substantial privileges, only run this under the existing authorized VPS admin account; the script does not attempt Docker mutation.

## Status and exit codes

| Status | Meaning | Exit |
| --- | --- | --- |
| `LOOPBACK_BIND_OBSERVED_NOT_APPROVED` | At least one listener, **all** visible port 8088 bind addresses loopback | 0 |
| `BIND_EXPOSURE_RISK` | Any wildcard/public/unknown bind | 2 |
| `NO_LISTENER_OBSERVED` | No listener on port 8088 | 3 |
| `AUDIT_INCOMPLETE` | ss command unavailable or failed | 4 |

**Exit 0 is a successful passive socket observation, NEVER approval to send any candidate text.** Missing Docker/systemd commands yield `inventory_completeness=partial` and cannot silently be treated as model verification.

Every response explicitly retains: approval_to_send_pdf=false, approval_to_send_query=false, embedding_requests=0, model_identity_verified=false, model_revision_verified=false, tokenizer_verified=false, egress_and_telemetry_verified=false, data_retention_verified=false, deployment_isolation_verified=false, proxy_redirect_policy_verified=false.

## Critical limitations and next evidence

An observed loopback binding does **not** prove remote access impossible: reverse proxies, SSH forwarding, host networking, firewalls, container bridges and process outbound connections require separate review. Docker ps ports show only published port metadata; the process inside may listen differently. A container image/name does **not** prove model checksum/revision.

The next **manual risk review** must inspect model revision/digest, tokenizer + 512-token length behavior, query:/passage: prefixes, service ownership, proxy/redirect rules, egress and telemetry settings, request logging/retention, and whether Production shares the same embedding service. Avoid printing/collecting raw environment variables or credentials in chat. No real PDF/query requests until these gates are explicitly approved.

## Regression boundaries

Synthetic mocked tests cover loopback v4/v6, public bind, mixed bindings, no listener, ss failure, unavailable Docker/systemd, fixed command allowlist (no HTTP, secrets or logs), safe Docker metadata, deterministic JSON, no model/network calls and the mandatory NOT_APPROVED output. Existing M10A/M10B-0/M10B-1/M10B-2A/M10B-2B-0 regressions run without actual endpoint access.

No frozen M8/M9/M5D/v1.3 change; no Production or main change. No new timer, shared DB write, embedding inference, official Gold review, semantic model quality claim or automatic promotion.
