# Hermes Gate 3D-C — Isolated MCP-only DeepSeek Chat, Staging v0.1

Date: 2026-10-31. **Code in GitHub Staging only; no live chat test yet.**

## Architecture before activation

Knowledge Brain Staging official APP149 approved snapshot (8 complete chunks)
→ disposable container-local `/tmp/jason-os-pnap-canary`
→ one stdio MCP tool `read_approved_pnap_source`
→ **isolated temporary Hermes profile, entire Hermes CLI runs as UID 65534**
→ DeepSeek (public BD evidence and fixed test question only)
→ source fingerprint + actual PDF page verification; human review.

This uses the already accepted Gate 3D-B Canary; no new database access,
no Docker socket, no network listener and **no changes to running
Hermes /opt/data/config.yaml or default hermes-cli toolsets**. A separate
profile is created in /tmp only for the single CLI command. It is
removed once complete, including on failure where possible. It cannot
be registered as a durable service.

## Why different from earlier MCP test

Gate 3D-B proves actual MCP list_tools and call_tool worked as UID65534,
but does NOT prove Hermes Chat / DeepSeek can discover or call the tool.
This gate tests that missing integration. We do not silently expand
Hermes' existing root-owned profile, credentials or tool privileges.

An isolated Hermes profile is a **configuration and state boundary**, not
a sandbox. The stronger OS boundary comes from starting the **entire CLI**
with `setpriv --reuid=65534 --regid=65534 --clear-groups`.
The dedicated MCP child inherits that UID, and `env -i` strips all
secrets passed to Hermes before the child starts.

The root-only preflight wrapper reads **only** the configured
`DEEPSEEK_API_KEY` from root-protected `/opt/data/.env` (or root
process environment). It never prints or persists the key; it supplies
that one variable solely to the temporary non-root Chat process. The
environment of that subprocess could be observable by other processes
running under the same UID or by root, so this is a narrow controlled
test, not a hardened production credential deployment.

## Operator instructions (after GitHub Staging merge CI PASS)

First fast-forward **clean** VPS `/opt/ai-knowledge-staging` from the
previous exact SHA to the new approved GitHub Staging merge SHA.

Read-only preflight, no provider call:

    cd /opt/ai-knowledge-staging
    bash scripts/hermes_gate3dc_isolated_chat_staging.sh --preflight

This verifies public APP145/APP149 snapshot identity and 8 chunks each,
MCP canary and CLI presence, current root config exists and a DeepSeek
key is configured. Prints boolean only, never key value.

**Only if preflight PASS** and operator explicitly authorizes transmitting
the fixed public BD APP149 excerpts and one test question to DeepSeek:

    bash scripts/hermes_gate3dc_isolated_chat_staging.sh --run

The runner creates a random isolated /tmp profile, writes only MCP
server setup there and uses exactly one toolset
`mcp-jason_os_pnap_canary`, includes one tool
`read_approved_pnap_source`, disables resources/prompts, uses
`--provider deepseek --model deepseek-chat --quiet --max-turns 4`.
It invokes a non-root CLI (UID65534) and asks one source-specific
question. Test question and APP149 original excerpts may go to DeepSeek.
No user-private data or Production corpus is intentionally passed.

It expects the model to return JSON with the exact official APP149
SHA256, 8 chunk count, review-required status, a short Traditional
Chinese summary and one or more PDF pages found in the approved chunks.
These identity fields are NOT supplied in the model prompt; they must
come back from a successful MCP tool call. A correct identity and page
fingerprint is an integration-level acceptance gate, NOT proof that
the generated professional/legal summary is accurate.

Run outcome:
- `GATE 3D-C MCP CHAT: SOURCE FINGERPRINT PASS` means the official
  source identity, page and metadata checks passed in a real model trial.
- A nonzero exit / `GATE 3D-C STOPPED` means **NOT ACCEPTED**; preserve
  the redacted terminal output and diagnose without guesswork.
- No model call from `--preflight`.
- After `--run`, temporary profile is removed; the original Hermes
  root profile's `config.yaml` SHA is compared before/after.
- No settings changes to running Hermes gateway, no restarts, no MCP
  registry in its default profile, no durable service.

## Boundaries / next steps

This still uses /tmp snapshots that can disappear on container recreation
and does not make Hermes' existing root process secure. It is an
**isolated CLI test**, not the user-visible Hermes Telegram/other
gateway chat, and not persistent production integration.

After success, test one clearly unsupported question and inspect the
answer's actual factual support in the PDF; then design a dedicated
persistent read-only volume or separate constrained container with
specific account/toolset controls, version refresh and rollback.

Sources:
- https://hermes-agent.nousresearch.com/docs/user-guide/profiles/
- https://hermes-agent.nousresearch.com/docs/reference/cli-commands/
- https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/
- https://github.com/KeiLee123/ai-knowledge/issues/60
