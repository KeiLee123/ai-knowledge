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

## Live result: E2E not accepted (2026-10-31)

Operator's real Staging E2E test returned:

    Warning: Unknown toolsets: mcp-jason_os_pnap_canary
    Chat exit code: 0
    Evidence fingerprint: invalid_model_json
    GATE 3D-C STOPPED: RuntimeError

DeepSeek printed literal DSML tool-call-shaped content instead of actually
running MCP and returning a tool result. Hermes also normalized
`deepseek-chat` to `deepseek-flash`. Therefore model availability is
established, but MCP registration and real tool dispatch are **NOT**.
The temporary profile was cleaned; existing Hermes config unchanged.
The `--run` command MUST NOT be repeated until registration is proven
independently without calling DeepSeek.

### Next diagnostic gate: no provider, no persistent config change

After GitHub Staging CI PASS and a clean VPS fast-forward to approved merge
SHA, execute exactly:

    cd /opt/ai-knowledge-staging
    bash scripts/hermes_gate3dc_mcp_discovery_staging.sh

This runs the installed Hermes CLI under UID 65534 with a disposable
`HERMES_HOME` created under /tmp, checks whether
`hermes config get mcp_servers --json` sees the isolated server,
and (if supported) runs `hermes mcp test jason_os_pnap_canary` to
discover its tools. It prints bounded diagnostic information only,
never loads a provider key or sends any prompt to DeepSeek. It checks
that the live `/opt/data/config.yaml` checksum was not changed and
cleans up the diagnostic profile.

The diagnostic distinguishes:
- Hermes not reading isolated profile config;
- MCP server configured but failed to spawn/connect/list tools;
- MCP manager discovers the server, but Chat's dynamic toolset
  resolution remains separate/broken.

A successful MCP manager test alone is not E2E success. A future model
retry must use structured tool-use/tool-result telemetry when available,
not accept free-form text that merely resembles a tool invocation.

## Hermes v0.21.5 MCP dynamic Toolset name compatibility (2026-10-31)

**Live diagnostic passed, but Chat failed**:
- `hermes config get mcp_servers --json` recognized the isolated profile.
- `hermes mcp test jason_os_pnap_canary` connected successfully and
  discovered exactly `read_approved_pnap_source`.
- Existing E2E nevertheless logged `Unknown toolsets: mcp-jason_os_pnap_canary`
  and printed text resembling a DSML tool call without executing it.

Inspecting the **actual deployed Hermes upstream source** at commit
`f97608f178d1ffeca59860195ab7da295f7c8e5f` identified a
specific compatibility risk: `hermes_cli/mcp_startup.py` passes the
literal `--toolsets` choice to its MCP server discovery filter, while
`tools/mcp_tool_discovery.py` matches the filter to the **bare
mcp_servers key**, not the generated `mcp-<server>` toolset name. Thus
`--toolsets mcp-jason_os_pnap_canary` can filter out the configured
server `jason_os_pnap_canary` itself before registration. After a real
MCP registration, `tools/mcp_tool_registration.py` adds an alias from
`jason_os_pnap_canary` to `mcp-jason_os_pnap_canary`.

**Staging-only fix**: use the **bare server alias**
`--toolsets jason_os_pnap_canary` and `toolsets: [jason_os_pnap_canary]`
in the disposable profile. Do not change the existing Hermes main
`/opt/data/config.yaml` or its default `hermes-cli` tools.

**New hard gate**: Both `--preflight` and `--run` now create the same
short-lived nonroot test Profile and execute an *independent, provider-free*
Registry probe under UID65534 with no `DEEPSEEK_API_KEY`. The probe sets
the same bare server allowlist, runs actual Hermes MCP discovery, and
requires **exactly one registered tool**, that its server alias resolves
to that toolset, and that no built-in toolset was added to the resolution.
If the probe fails, **no DeepSeek request takes place**. On either path,
clean up the profile and verify original Hermes config SHA unchanged.

This is a narrowed diagnosis supported by upstream source. A passed
Registry probe still does not prove the model performed the tool call;
real E2E must separately prove actual dispatch, not textual DSML alone.

Pinned upstream references:
- https://github.com/NousResearch/hermes-agent/blob/f97608f1/hermes_cli/mcp_startup.py
- https://github.com/NousResearch/hermes-agent/blob/f97608f1/tools/mcp_tool_discovery.py
- https://github.com/NousResearch/hermes-agent/blob/f97608f1/tools/mcp_tool_registration.py


## Live E2E answer observed — strict parser failed (2026-10-31)

After Registry PASS, the operator's real model trial ran against
Staging d87b1d61dc7c2298daef9ca4811d34dbb7537cd0:
- Hermes CLI exit 0; DeepSeek produced a JSON-shaped answer with APP149
  approved SHA256, 8 chunks, EVIDENCE_ONLY_REVIEW_REQUIRED, pages 1–5,
  and a substantial Traditional Chinese summary.
- Two Hermes CLI notices preceded the JSON: model deepseek-chat was normalized
  to deepseek-flash; tirith scanner unavailable with pattern-matching fallback.
- Existing parser attempted json.loads on the entire mixed stdout, returned
  invalid_model_json, and fail-closed RuntimeError. Isolated profile cleaned,
  existing Hermes configuration remained unchanged.
- No independently captured MCP tool execution trace was retained.
  Therefore **real E2E remains NOT ACCEPTED**, notwithstanding plausible
  output and accurate-looking metadata.

## Fix: bounded JSON parsing plus independent dispatch proof

The new extract_model_json accepts only the two known *exact* Hermes notice
lines as a leading prefix, followed by precisely one JSON object. Any
unexpected warning, arbitrary preamble, DSML pseudo-tool-call, malformed
JSON, multiple answers or trailing content fails closed. The model's SHA,
chunk count, review status and PDF pages are separately checked as before.

Model output alone is insufficient to prove a real tool call. The updated
one-shot script now inspects its own temporary HERMES_HOME/state.db in
**read-only SQLite mode**, before deleting that temporary profile. The
upstream Hermes v0.21.5 messages table stores assistant tool_calls,
tool_call_id, tool_name and role=tool results.

Acceptance requires one assistant tool call with the exact native function
name mcp__jason_os_pnap_canary__read_approved_pnap_source and argument
source_id=BD_PNAP_APP149, a matching unique tool_call_id, and exactly one
corresponding tool result containing APP149 approved checksum, all 8 chunks,
null answer and EVIDENCE_ONLY_REVIEW_REQUIRED. Missing session database,
other tools, wrong arguments/source, missing result or malformed data fail
closed. The script only prints a bounded success/reason code and cleans up
its temporary profile; it does NOT upload the full transcript.

New acceptance line: GATE 3D-C MCP CHAT: SOURCE FINGERPRINT AND TOOL DISPATCH PASS.
This is **still** an integration acceptance, not a guarantee of the legal
accuracy/current validity of the generated answer.

Do not invoke DeepSeek again until PR CI and merge CI PASS, the clean Staging
checkout is synced to the exact merge commit, and no-provider preflight PASS.
Previous run's temporary session was deleted so its historical tool
dispatch is not independently recoverable from that private profile.

## Further live tool-trace mismatch — precise diagnostic only (2026-10-31)

The next actual isolated Hermes Chat trial at Staging 836559769ffc64ea616cb2afe169bec78561f30c showed no-model Registry PASS, CLI exit 0, a valid and strictly parsed APP149 JSON response with approved SHA256, 8 chunks, review-required status and PDF pages [1,2,3,5], but the independent session DB tool check failed: Actual MCP dispatch: unexpected_tool_invoked. The ephemeral profile was removed and existing Hermes config remained unchanged.

This failure only establishes that at least one assistant function name in the trace did not exactly match the expected native MCP tool name. It does NOT establish which tool was actually requested or whether the transcript uses another naming convention. Gate 3D-C remains NOT ACCEPTED, and the deleted trace cannot be recovered.

Next change: no-provider Registry probe must verify the exact function name mcp__jason_os_pnap_canary__read_approved_pnap_source, not a substring. If a later controlled model run fails its independent SessionDB verification, show only bounded validated tool names, assistant tool-call counts and tool-result counts. No arguments, response content, prompts, conversation transcript or key should be displayed. Unexpected tools remain prohibited, and the temp profile remains disposable.

Operator should run only --preflight once GitHub PR and merge CI succeed. No further paid model call until this no-provider check passes and the run is explicitly approved. Any future --run still needs BOTH model fingerprint and independent recorded tool-call/result checks.
