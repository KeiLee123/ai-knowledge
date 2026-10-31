# Hermes ⇄ Knowledge Brain — Read-only Evidence Contract v0.1

Date: 2026-10-31. **State: GitHub Staging development only. No Hermes live connection.**

## Architecture decision: use Hermes as the chat frontend

User talks to existing Hermes (already configured with a model provider / DeepSeek)
  → Hermes calls one dedicated *future* read-only MCP tool
  → Staging Knowledge Brain runs already accepted APP145 / APP149 evidence retrieval
  → returns original text + SHA256 + canonical PDF URL + PDF page + source markers
  → Hermes/DeepSeek may draft an answer or abstain
  → human checks quotations and whether the PDF is current

This design does NOT require exposing Hermes' own API port 8642 to the VPS host.
Do not alter Hermes' API_SERVER_HOST, API_SERVER_KEY, Docker port publishing or
running container merely to allow the reverse (Knowledge Brain → Hermes) direction.

## Why the change

Hermes Docker image nousresearch/hermes-agent:v2026.9.24 is up. The operator
proved internal 127.0.0.1:8642 /health HTTP 200 and /v1/models HTTP 401.
The VPS host 127.0.0.1:8642 connection is reset; accessing port 8642 via the
container's own network IPv4 from inside the container returns URLError.
The likely cause is Hermes API bound only to container loopback.
API_SERVER_KEY is present in /opt/data/.env; config.yaml and .env exist there.
This is an inbound API reachability issue, **not proof** that DeepSeek is down.
No further 8642/9119 checks needed to start the correct Hermes→Brain design.

## Engineering artifact, currently additive only

Use the operator-safe (no external model) Staging evidence serializer:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python beta_hermes_evidence_v1.py \
      --source BD_PNAP_APP149 \
      --question "Under APP149, what are the requirements for a temporary AS?"

It imports only the existing beta_ask_staging_v1.build_packet, so the
approved source whitelist, pinned Staging baseline, DB checks, clean Staging
checkout, local embedding, Top-5 native primary retrieval and source integrity
continue to apply. Returns exactly one JSON packet with:

- source ID, official title, PDF canonical URL and approved SHA256;
- PDF page, original chunk ID, source marker and bounded (6,000 chars) text;
- truncated flags rather than pretending text is complete;
- explicit NOT_VERIFIED revision and legal currentness;
- answer=null, answer_status=EVIDENCE_ONLY_REVIEW_REQUIRED.

Fails closed with a sanitized JSON refusal and nonzero exit code. It never
connects to Hermes/DeepSeek, modifies Drive/Production, or opens a port.

Contract tests:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python test_beta_hermes_evidence_v1.py

## Future MCP transport gate (NOT implemented in this commit)

Official Hermes supports remote HTTP MCP connections in mcp_servers
with a per-server tool include allowlist. Use **one** read-only tool,
tentative name search_official_pnap_evidence, whose backend calls the
JSON evidence contract. Do NOT expose PostgreSQL, arbitrary shell, unrestricted
filesystem, Production, or the whole Hermes agent API.

Before deployment, verify which *host-side* private Docker bridge IP can
be reached by the Hermes container; bind the MCP listener narrowly there,
not 0.0.0.0 or a public interface; apply a dedicated bearer token at the
MCP server boundary, firewall/networks, request limits and audit safety.
Tokens must be stored in a secret store, never git or terminal output.
Assess whether the Hermes chat platform currently has privileged tools:
a dedicated restricted profile/platform toolset is preferable for handling
untrusted PDF excerpts. Merely filtering one MCP server does not disable
Hermes' unrelated built-in tools.

Once that secured route is verified, explicitly authorize passing selected
public BD evidence and test questions to DeepSeek through Hermes, then
validate draft citations, actual factual support and insufficient-evidence
abstentions on five human-reviewed professional questions. Avoid asserting
that Top-5 retrieval alone proves answerability.

References:
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- https://github.com/KeiLee123/ai-knowledge/issues/60
- https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit
