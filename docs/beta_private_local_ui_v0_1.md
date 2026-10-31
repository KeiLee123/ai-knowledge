# Knowledge Brain — Private Beta local Web UI v0.1

Status: **GitHub Staging candidate**. No Production release; no public service.

## Architecture

Personal browser -> SSH local port forward -> VPS 127.0.0.1:8765 -> random session token + Origin/Host checks -> existing beta_ask_staging_v1.build_packet -> approved APP145/APP149 -> Staging DB + local embeddings -> currentness_abstention -> linked official source evidence.

The UI does not generate an AI answer. It does not alter the Frozen Retrieval engine, DB, source registry, Hermes, M8/M9 or Drive Current. It does not require Flask, Node, npm, external scripts or a new service manager. The UI is an ephemeral foreground Python stdlib HTTP server bound to IPv4 loopback ONLY.

The only new write is **local Staging feedback JSONL** at /var/lib/jason-os/private-beta-staging/feedback.jsonl (parent permission 0700, file 0600). It stores a feedback type, comment, source ID, timestamp and opaque query ID, NOT the raw question or retrieved source text. This local feedback queue is temporary; Google Drive remains the documentary Source of Truth and any formal sync/triage will be separately approved.

## Preconditions

- Exact merged GitHub Staging SHA, green CI, clean VPS staging branch at /opt/ai-knowledge-staging.
- Existing approved APP145/APP149, staging index, local embedding and source baseline are healthy.
- An SSH client or SSH application's port forwarding is available on the owner's trusted personal computer.
- No Coolify public route, VPS firewall opening, reverse proxy, exposed management port, systemd unit or timer.

## VPS commands (only after exact commit acceptance)

    cd /opt/ai-knowledge-staging
    test "$(git branch --show-current)" = staging
    test -z "$(git status --porcelain)"
    export PYTHONDONTWRITEBYTECODE=1
    python3 test_beta_ask_staging_v1.py
    python3 test_beta_private_ui_staging_v1.py

Start ONE foreground process. No installation:

    umask 077
    PYTHONDONTWRITEBYTECODE=1 python3 beta_private_ui_staging_v1.py --serve --port 8765

The console will print the localhost URL and a **random one-session token**. Copy the token into the browser's password input. Never paste that token into GitHub, chats or public documents. Stop the process with Ctrl+C. The next launch has a new token.

On your own laptop/desktop, open a different terminal and use an authorized SSH identity:

    ssh -N -L 8765:127.0.0.1:8765 <ssh-user>@<vps-address>

Then open http://127.0.0.1:8765 in the browser on THAT personal computer. An existing SSH app's port-forward feature is an alternative. The HTTP connection must travel inside the SSH tunnel; do not browse to a VPS public IP or open 8765 in its firewall.

## First private browser acceptance

1. Choose BD_PNAP_APP149. Ask: 臨時獲提名的認可簽署人可以簽署監督計劃及指定表格嗎？其地盤監督職責是甚麼？ Expect 8/8 indexed source chunks, and APP149 paragraph 9, PDF page 3 (chunk 123) among the evidence, with real official PDF links. The UI does not generate an AI answer.
2. Choose BD_PNAP_APP145. Ask: 截至2026年10月31日，第572章消防安全（建築物）條例的現行規定是否與 APP145 完全相同？最新修訂日期及法定改善期限是甚麼？ Expect CURRENTNESS_UNVERIFIED_ABSTAIN, not a made-up legal deadline.
3. Submit benign feedback such as 請優先顯示第9段，而不是附錄表格. Expect a feedback receipt and one private JSONL line. Only an authorized local Staging feedback directory is written.
4. Check an incorrect token and cross-origin requests cannot read evidence, and verify PDF page links point to the approved bd.gov.hk location.
5. Stop the local server and SSH tunnel. No background service should remain.

Metadata-only checks for feedback (do not paste raw content):

    stat -c '%a %U %n' /var/lib/jason-os/private-beta-staging /var/lib/jason-os/private-beta-staging/feedback.jsonl
    wc -l /var/lib/jason-os/private-beta-staging/feedback.jsonl

## Safety and limitations

- Fixed bind host: 127.0.0.1. No --host override. A privileged operator may need to run this temporary process for existing Docker Staging access; do not host it publicly, and design a restricted worker identity before wider rollout.
- Token is per-process, sent in a custom header; never stored in browser localStorage or URL. Same-origin POST, Host checking, max JSON body, fixed source allowlist, no access logs, no-cache headers, Content Security Policy nonce, safe DOM text rendering.
- No LLM egress; no uploaded private documents; no arbitrary path, process or SQL input. All evidence is sourced via the existing Staging-only Beta contract. Existing embedding service is loopback-local.
- Only an explicit subset of currentness cues are blocked. This is not a universal or independently reviewed legal-safety classifier.
- 8/8 indexed chunk coverage is not current law, semantic relevance or a correct human/AI legal answer.
- Feedback is local Staging data until reviewed into the Drive document Source of Truth. The UI does not implement feedback triage or Anki packages yet.
- The UI has no model-generation toggle, no Auto Anki, no shared account login and no public hosting.

## Acceptance ladder

CODED (files in GitHub) -> CI_PASS (Staging PR + merge Validation) -> VPS_STAGING_ACCEPTED (real browser evidence and feedback journey) -> USER_BETA (independent human-reviewed Q&A, user feedback cycle, 5–10 vetted Anki Test Profile cards) -> PRODUCTION (separate authorization).

No stage may be skipped based on green CI alone.

Tracking: https://github.com/KeiLee123/ai-knowledge/issues/60
Architecture Source of Truth: https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit
