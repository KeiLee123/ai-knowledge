# Hermes Gate 3D — Non-disruptive Staging release and rollback plan

> **Gate 3D-B update (2026-10-31):** Live preflight stopped **before copying**
> because UID 65534 cannot traverse /opt/data, although it cannot read
> /opt/data/.env and MCP SDK 2.0.0 protocol calls work. **Do not chmod or ACL
> the protected /opt/data directory** as a quick fix. All references below
> to a persistent /opt/data release are **blocked future deployment plans**,
> not the currently approved Canary. The reviewed Canary now uses only
> container-local /tmp/jason-os-pnap-canary and is deliberately ephemeral.
> It cannot be registered as a persistent Hermes MCP service.

Date: 2026-10-31. **Not deployed to Hermes.** GitHub Staging source only.
Requires operator review for any changes to the existing Hermes container.

## Confirmed facts

- Hermes Docker container `hermes-rgu4flce2juuzyq6idzr49z2` runs as root,
  `Privileged=false`, with persistent **writable** `/opt/data` mount.
- Existing Hermes toolset is `hermes-cli` (broad privileges). No MCP server configured.
- Hermes Python virtualenv `/opt/hermes/.venv/bin/python` has MCP SDK 2.0.0,
  compatible MCPServer/Client API.
- Live `setpriv --reuid=65534 --regid=65534 --clear-groups` in Hermes:
  UID 65534, `os.access("/opt/data/.env", os.R_OK)==False`,
  actual in-memory MCP list_tools/call_tool PASS.
- The trusted-side Staging export created exactly 8 approved chunks per
  APP145/APP149 under `/var/lib/jason-os/hermes-pnap-snapshots-staging`.
- Staging PostgreSQL container has `Network=none`; the `ai_knowledge`
  login is superuser. Never give Hermes direct access to this DB/socket.

## Design: reuse the one existing persistent mount

For this **Staging-only experiment** use a fixed, dedicated subdirectory:

```
Hermes /opt/data/jason-os-pnap-staging/
  server.py                  # vetted, root-owned, non-writable to UID 65534
  snapshots/
    BD_PNAP_APP145.json      # public-source evidence, no secrets
    BD_PNAP_APP149.json
```

The MCP reader in this PR reads only
`/opt/data/jason-os-pnap-staging/snapshots`.
This directory is inside the existing **RW mount**; root-owned `0555`
directories and `0444` files make it non-writable to the *dropped-privilege
MCP process*, but **do not** make it immutable to the root Hermes process.
Do not describe this as an OS sandbox or a Docker read-only bind mount.

Do not add an extra Docker mount, recreate Coolify service, open a TCP
port, attach the Staging database network, give Hermes docker.sock or
alter the DeepSeek credential/configuration.

## Gate 3D-A: pre-release checks (read-only; before any container writes)

1. GitHub Staging exact commit and CI must pass; VPS Staging worktree clean.
2. Verify both source files exist, mode root-only and JSON fields match
   `APPROVED` source URL + approved SHA256 hardcoded in the MCP reader.
3. Confirm the target path `/opt/data/jason-os-pnap-staging` does NOT
   already exist in Hermes; fail instead of overwriting unrelated files.
4. Ensure Hermes `/opt/data` mount is the existing persistent mount.
5. Record operator-approved rollback path and user-visible impact.

## Gate 3D-B: canary release (separate operator approval)

Copy only `beta_hermes_mcp_snapshot_stdio_v1.py` as `server.py` plus
the two approved JSON files to the fixed directory. Do this *after* the
read-only preflight, via `docker cp` into the **existing /opt/data mount**.
Set directory/file ownership to root and directory mode `0555`, file
mode `0444`. Do not copy DB keys, CLI credentials or the source repo.

Verify byte-for-byte SHA256 of each copied file against the trusted host.
Then run the existing Hermes Python SDK under an explicit
`setpriv UID=65534, GID=65534, --clear-groups` process with sanitized
environment (e.g. `env -i`), to:

- verify no read access to `/opt/data/.env`;
- load real `server.py`;
- execute one MCP `list_tools` and `call_tool` each for APP145/149;
- check source pins, 8 chunks each, review-required status and null answer;
- verify it cannot modify the installed files.

This phase **MUST NOT update `/opt/data/config.yaml`** or start Hermes AI
chat. It validates the installed consumer, not a model answer.

## Gate 3D-C: separate config activation (after explicit approval)

Back up `/opt/data/config.yaml` with root-only permissions and verify
it can be restored, without printing its contents (may contain secrets).
Use an atomic, reversible edit that **only adds**:

```yaml
mcp_servers:
  jason_os_pnap_staging:
    command: /usr/bin/setpriv
    args:
      - --reuid=65534
      - --regid=65534
      - --clear-groups
      - /usr/bin/env
      - -i
      - PYTHONDONTWRITEBYTECODE=1
      - /opt/hermes/.venv/bin/python
      - /opt/data/jason-os-pnap-staging/server.py
    tools:
      include: [read_approved_pnap_source]
      prompts: false
      resources: false
```

The server contributes a dynamic toolset `mcp-jason_os_pnap_staging`.
Use a *dedicated* `hermes chat --toolsets mcp-jason_os_pnap_staging`
trial with carefully reviewed public BD excerpts. Do not amend global
`toolsets: [hermes-cli]`. Confirm the session does not expose terminal,
file-write, browser or delegation tools. A restricted model toolset
is **not** an OS-level boundary because the main Hermes process is root.

Hermes gateway may dynamically reload watched config; do not assume that
the edit is inactive until a restart. Activation is a separate controlled
operational change with immediate verification, rollback readiness and
explicit consent to send test questions/public evidence to DeepSeek.

## Rollback

- 3D-B without config change: root removes **only** the exact newly added
  `/opt/data/jason-os-pnap-staging` release directory after verifying
  its contents and path; original source snapshots on the host remain intact.
  No service restart required.
- 3D-C after config activation: disable/remove only the
  `mcp_servers.jason_os_pnap_staging` entry with a safe atomic edit; reload
  MCP or confirm gateway automatically disconnects it; validate removal
  before deciding whether to remove the release directory.
- If the Hermes config was otherwise modified concurrently, do NOT
  blindly restore an old full config backup over new legitimate changes:
  reconcile the specific entry and preserve current secrets/settings.
- No rollback changes to Knowledge Brain Production, Staging DB, or
  Source Registry are necessary.

## Fail-closed conditions

Stop if live Hermes process/environment or mounted source differs from
the audit, if target path already exists, if server SDK import fails,
if approved source SHA/URL differs, if any file is unexpectedly writable
by UID 65534, if secrets are readable by UID 65534, if MCP returns a
non-reviewed answer, or if Session exposes non-allowlisted tools.

The copied evidence files remain disposable caches, not canonical PDFs.
Google Drive is still the source of truth for original documents. A
source SHA in JSON is not a signature authenticating the snapshot JSON.

References:
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/
- https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference
- https://github.com/KeiLee123/ai-knowledge/issues/60

## Gate 3D-B guarded operator installer (added 2026-10-31)

After PR canary code merges into GitHub Staging **and** its merge-commit CI
passes, first sync a clean VPS Staging checkout to the exact approved merge
commit. Then run this one checked-in script, *not manually pasted Docker cp
commands*:

    cd /opt/ai-knowledge-staging
    bash scripts/hermes_gate3d_canary_install_staging.sh

The script validates the current clean `staging` checkout is exactly at
`origin/staging` and contains the accepted Gate 3D baseline, Docker is
running unprivileged (not privileged mode), the single existing /opt/data
volume is RW, the target directory does not exist (including no dangling
symlink), and UID65534 can **traverse /opt/data** while still unable to read
the tested Hermes .env file. It also checks the two root-private source
snapshots, their approved source/checksum, schema, and 8 verified chunks.

The script then creates the dedicated release directory, copies **only**
`server.py` and APP145/149 JSON snapshots, assigns root ownership,
sets 0555 directories / 0444 files, checks byte hashes against the trusted
host, and exercises actual MCP list_tools/call_tool for both sources under
UID65534 with `env -i`. It verifies `/opt/data/config.yaml` has an
unchanged SHA256 before and after; no model call, no network listener and no
MCP registration occurs.

If the parent /opt/data is not traversable by UID65534, the script **fails
before making any changes**. Never fix this with chmod on all of /opt/data;
that would risk exposing Hermes secrets. If any step fails **after**
creating the release directory, the script intentionally leaves its partial
files intact for forensic review. **Do not rerun or run rm -rf blindly.**
Review exact path, type, ownership and content with a separate rollback step.

Do not confuse 0555/0444 permissions with an actual Docker read-only mount:
Hermes' root process can still change the files. Gate 3D-C (config/agent
registration and restricted model session) remains an independent gated
change, not part of the installer.

## Revised Gate 3D-B ephemeral canary (post-preflight refusal)

Operator observed:

    AssertionError: UID 65534 cannot traverse /opt/data
    CANARY STOPPED (exit 1)

The script stopped on its **first, pre-write** check, so it did not create
any Canary artifacts. The revised version of
`scripts/hermes_gate3d_canary_install_staging.sh` instead requires that
UID 65534 can traverse `/tmp` and that root can create a previously
nonexistent `/tmp/jason-os-pnap-canary` directory. It does not change the
`/opt/data` parent, its ACLs, its permissions or Hermes config.yaml.

Revised consumer source has a narrowly scoped selection:
- normal `ROOT` stays `/opt/data/jason-os-pnap-staging/snapshots`, but
  this is **not currently usable** by UID65534;
- **only** when the isolated `JASON_OS_PNAP_CANARY=1` environment variable
  is set before launching the MCP Python program, `ROOT` instead selects
  `/tmp/jason-os-pnap-canary/snapshots`.

The script installs exactly three root-owned, child-nonwritable files under
that `/tmp` directory, checks hashes, and runs the actual MCP client
`list_tools` and `call_tool` against the two eight-chunk JSON snapshots
under the UID 65534 process, with `env -i`, then verifies unchanged config.

The copied snapshots are **public BD excerpts**, not secrets. This is not a
persistent deployment: Docker/Coolify recreation may erase the entire /tmp
Canary. Do **not** modify mcp_servers to point here or use this as the
live DeepSeek integration. Later review must choose a genuinely restricted
persistent mount that UID65534 can traverse, or a carefully scoped ACL
change following separate security acceptance. Avoid granting shell,
Docker socket, staging DB superuser or access to the entire /opt/data.

On failure after directory creation, inspect only
`/tmp/jason-os-pnap-canary` before any cleanup. Do not rerun blindly,
remove unrelated temp files or broaden /opt/data permissions.
