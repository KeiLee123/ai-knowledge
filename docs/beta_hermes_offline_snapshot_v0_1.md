# Hermes Gate 3B — Offline Approved Evidence Snapshot (v0.1)

Status: **Staging development only**. Not deployed to Hermes or Production.
Date: 2026-10-31.

## Security finding and design decision

Operator audit confirmed:
- Hermes network: rgu4flce2juuzyq6idzr49z2 / 10.0.3.2, gateway 10.0.3.1.
- Staging PostgreSQL container: Docker `network_mode=none`; no routable container IP.
- Existing login `ai_knowledge` is a PostgreSQL superuser and can create
  databases and roles. **Never grant Hermes this login or mount Docker socket.**

Do not connect Docker networks, publish database ports, or modify frozen
Production and the existing isolated Staging database for convenience.

## Architecture

1. **Trusted exporter (operator side only)**: `beta_hermes_snapshot_export_v1.py`
   uses the already validated Staging-only database guard, approved Drive
   canonical baseline SHA, source registry, index integrity and source role.
   It SELECTs **all primary native text chunks** of exactly one approved
   checksum, refuses count/role/page mismatches and emits one JSON object
   on stdout. No DB writes, no Drive writes, no model, no network listener.
2. **Read-only snapshot files**: one fixed JSON per approved APP145/APP149,
   stored outside the source repository and mounted into the consumer as
   read-only by an operator. These are derivative evidence caches, NOT a
   new document Source of Truth. Google Drive still owns the original PDF.
3. **Unprivileged MCP consumer**: `beta_hermes_mcp_snapshot_stdio_v1.py`
   exports exactly one tool `read_approved_pnap_source`. It has no Docker,
   PostgreSQL or retrieval imports; it reads an exact filename from a
   fixed mount `/mnt/jason-os-pnap-readonly`. It checks source allowlist,
   pinned original SHA256, canonical HTTPS URL, page+chunk IDs, bounds,
   mandatory NOT_VERIFIED currentness and null answer; refuses if missing
   or tampered. No question-specific retrieval/ranking.
4. **Hermes / DeepSeek**: after separately authorized deployment, Hermes
   reads a selected source's full approved text and MAY draft an answer.
   Human reviews factual support and citation PDF page. Neither retrieval
   nor MCP annotation establishes that AI content is accurate/current.

## Why all chunks initially?

APP145 and APP149 have only about eight approved primary chunks each. For
two-document MVP, reading the entire selected source avoids the previously
observed top-2 ranking failure and avoids installing a database/query
service inside the Hermes container. This is NOT a general replacement
for scalable semantic search; later adapters remain replaceable.

## CI regression (no VPS required)

    python -m pip install -r requirements-hermes-mcp.txt
    python test_beta_hermes_snapshot_v1.py

The official MCP SDK is an optional dependency, not installed by the normal
Production requirements. Tests mock the trusted exporter DB calls, validate
original role/page/count, rejected source/false SHA, malformed/tampered
snapshots, and a real MCP client/server in-memory protocol request.

## Proposed VPS evidence export acceptance (NOT YET RUN)

Only after merging to GitHub Staging and syncing clean VPS Staging:

    cd /opt/ai-knowledge-staging
    export PYTHONDONTWRITEBYTECODE=1
    umask 077
    install -d -m 0700 /var/lib/jason-os/hermes-pnap-snapshots-staging

    for source in BD_PNAP_APP145 BD_PNAP_APP149; do
      out="/var/lib/jason-os/hermes-pnap-snapshots-staging/${source}.json"
      test ! -e "$out"
      .venv/bin/python beta_hermes_snapshot_export_v1.py \
        --source "$source" > "$out"
      chmod 0400 "$out"
    done

Validate the JSON objects (source ID, 8 chunks, approved SHA256, page range,
NOT_VERIFIED). Do not print full evidence unless needed. The files must be
reviewed before granting Hermes any access. Exporter never stores secrets.

**NO Hermes mounts, config changes, restarts or new ports in this gate.**

## Separate future Hermes deployment gate

- Verify Hermes container supports the exact stdio command and Python MCP
  environment; create a tool-restricted profile so it cannot use unrelated
  shell/file tools to act on retrieved text.
- Copy approved snapshot files to a dedicated **read-only mount**; do not
  mount Staging code directory, DB socket, Docker daemon, secrets or all of
  Google Drive.
- Confirm the Hermes-side MCP tool can read the fixed two snapshots but
  cannot see private files or execute host commands.
- Require explicit operator authorization for sending selected public PDF
  evidence + test question through Hermes to DeepSeek.
- Validate answer and citations on five real professional queries, one
  clearly unsupported question and source-version applicability.

## Limitations

Snapshots may become stale; require explicit re-export and new approval
when official source SHA changes. The original document SHA in the JSON
does **not** cryptographically prove the JSON itself wasn't edited: enforce
trusted operator generation and read-only ownership; stronger signed
snapshot provenance is a later hardening task. No claim of current law.
