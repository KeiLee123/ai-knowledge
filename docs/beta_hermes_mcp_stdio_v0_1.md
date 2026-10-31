# Hermes MCP Tool v0.1 — local Staging protocol validation

Status: GITHUB STAGING CANDIDATE, not connected to Hermes, not production.

## Minimal architecture

Hermes Chat (existing DeepSeek connection)
→ future restricted, authenticated MCP transport
→ one `search_official_pnap_evidence` tool
→ current approved Staging retrieval (APP145 or APP149 only)
→ source-pinned PDF excerpts, page, chunk IDs, SHA256
→ Hermes drafts a response or abstains, under human review.

## Why the first implementation is stdio-only

Hermes supports stdio MCP servers and remote HTTP servers. The simplest
protocol acceptance is a real stdio-compatible MCPServer with a single
read-only tool, tested against the official MCP Python SDK `Client(mcp)`
in memory. It opens NO network port, and it does not modify Hermes
config.yaml, .env, its Docker mounts, or DeepSeek credentials.

The actual Hermes runtime runs inside a separate Docker container. Its
existing API 8642 is loopback-only; this is irrelevant to this
Hermes→Brain tool architecture. A host-side stdio process cannot be
registered in the Hermes container simply by copying the config snippet.
Do not add a misleading Hermes config entry until transport is designed.

IMPORTANT: existing Staging retrieval invokes Docker commands on the host
to reach the Staging DB. Running a public-facing MCP server with that
privilege would be unsafe. This commit MUST NOT be converted into an HTTP
server and exposed without a least-privilege DB access redesign, auth,
private transport, startup guardrails, and explicit deployment review.

## Code and offline validation

- `beta_hermes_mcp_stdio_v1.py`: real MCP server exposing exactly one tool
  with read-only hints, fixed source IDs and question length limits.
- `beta_hermes_evidence_v1.py`: previously accepted machine-readable
  evidence serializer, unchanged.
- `requirements-hermes-mcp.txt`: optional separate SDK dependency,
  `mcp==2.2.0`. The normal `requirements.txt` is unchanged.
- `test_beta_hermes_mcp_stdio_v1.py`: real MCP tool discovery, call and
  sanitized refusal using in-memory Client; no Docker, no model call.

CI acceptance: install the optional SDK and run the offline protocol test.

Operator validation once merged to GitHub staging:

    cd /opt/ai-knowledge-staging
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python test_beta_hermes_mcp_stdio_v1.py

The optional MCP dependency must first be installed **in a separate
purpose-built environment**, not into the Frozen Production environment.
Do not launch the server as root, a permanent service, or an HTTP port.

## Transport gate required before live Hermes

The best long-term design is an unprivileged read-only Staging query service,
which does not have the Docker daemon/socket, filesystem write access,
or Production credentials. Supply a dedicated read-only DB role and only
allow approved documents; connect Hermes over a private, authenticated
container-to-service route or an explicitly reviewed Unix socket relay.
Server-side authentication is mandatory and should not depend on model
prompts or MCP annotations.

Before live connection, independently verify:
- Staging-only DB role, no Docker socket, no Production credentials;
- Hermes limited to the single approved MCP tool for this workflow;
- an explicit user decision on sending public source excerpts and
  professional questions to DeepSeek;
- factual/quote support, refusal/abstention, true PDF currentness,
  and source page accuracy across five professional queries.

References:
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- https://py.sdk.modelcontextprotocol.io/client/
- https://github.com/KeiLee123/ai-knowledge/issues/60
