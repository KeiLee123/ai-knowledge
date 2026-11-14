# Private Beta 8765 Staging persistent service — design v0.1

**Status:** GitHub feature-branch candidate only. Not installed on VPS, not merged.
**Base:** GitHub `staging` at `002a62d6d2ee12ed965eb0c14e866d3129fe34c9`.
**Scope:** Existing Knowledge Brain Private Beta on `127.0.0.1:8765` only. No Production, Frozen Retrieval, DB schema, new internet ingress, model egress or external proxy.

## Architecture and safety constraints

Windows browser -> existing SSH tunnel -> VPS `127.0.0.1:8765` -> existing Private Beta UI, approved Staging evidence/DB and root-private feedback/PDF cache.

We retain existing `beta_private_ui_staging_v1.py` and its `qa.check_checkout()` source/DB guard unchanged. A replaceable `private_beta_systemd_staging_v1.py` imports its `build_server` and serves the same HTTP handlers, but **does not call the old `main()` which prints the session token to stdout**. Instead it binds loopback port 8765 first, then atomically writes a newly generated token into `/var/lib/jason-os/private-beta-staging/session-token-8765` (root-owned, mode 0600, parent root-owned mode 0700). It refuses symlinks, public parent/file modes and wrong effective user. Existing PDF cache must be root-private; original source SHA and quote integrity continue to be verified by the existing source/citation code.

Systemd unit is stored in this GitHub repo under `deploy/systemd/jason-os-private-beta-staging.service`, later copied to `/etc/systemd/system/` with root ownership after independent Staging acceptance. Unit runs as root **only because existing Feedback and PDF files are root-owned 0700/0600 and append_feedback rejects other owners**. A dedicated unprivileged service user is a separately reviewed later migration, not part of this MVP.

- `StandardOutput=null`, `StandardError=null`; never put a token in journal, environment, process command line, URL, Git, Google Drive or chat.
- `Restart=on-failure` and `WantedBy=multi-user.target` for reboot recovery.
- `UMask=0077`, `NoNewPrivileges=true`, `PrivateTmp=true`; no changes to original HTTP host binding, ports or SSH forwarding.
- Token rotates on each service process restart. Users must re-enter the **new private token** in the browser after restart; read it locally as root. The token file is not a long-lived user password or persistent reuse.
- A systemd service, private browser and GitHub Code are separate gates. The PR must not install/start/stop anything by itself.

## MVP Acceptance gates

1. Draft PR review and exact-head GitHub CI including `test_private_beta_systemd_staging_v1.py` offline token mode/rotation/symlink/parent-permission/atomicity and unit contract. Existing Beta UI and quote regressions must pass.
2. Owner VPS *read-only* check: current 8765 process identity, service absent, Staging pinned clean, root-private storage and approved PDFs intact. Completed for directory/port/version; a focused PID/cmdline check remains before controlled handoff.
3. Isolated worktree regression, leaving `/opt/ai-knowledge-staging`, `/opt/ai-knowledge`, Feedback and PDF cache intact.
4. Only after separately approved GitHub `staging` merge + green post-merge CI, perform guarded VPS Staging-only fast-forward and source checks. No Production promotion.
5. Owner-controlled cutover: verify PID/process path actually matches old Python foreground service; **stop old foreground 8765 first** from its own terminal, verify port released; install pinned reviewed systemd unit with `install -o root -g root -m 0644` and `systemctl daemon-reload`; `systemctl enable --now jason-os-private-beta-staging.service`.
6. Verify listener is exclusively `127.0.0.1:8765`, process is owned by systemd unit, HTTP 200 serves reading modes, no unauthorized API access, private token file owner root/mode0600 with no symlink, and `journalctl` does not contain token. Browser re-login and query 16/16, reading-mode toggle, PDF quote and feedback check; Feedback changes only if owner deliberately submits a test response.
7. Recovery: prove controlled `systemctl restart` rotates the token and remains bound to loopback; verify `systemctl is-enabled`; reboot test only under a separate maintenance window. Do not claim reboot durability until observed.
8. Rollback if unsafe/unavailable: `systemctl disable --now jason-os-private-beta-staging.service`, inspect port release, restore the previously verified foreground command with a fresh token, leave Production unchanged. Preserve feedback/PDF data, never reset the Git repo or expose public ports.

## Cautions

- Installing new service while existing Python foreground PID listens on 8765 will fail due to port conflict. Do not use `kill -9` or indiscriminately terminate Python processes.
- The unit discards application stdout/stderr to keep sensitive query/token data out of journald; `systemctl status` still provides service lifecycle/exit state. Avoid copying raw shell command traces containing token into GitHub/Drive/chat.
- A normal server restart rotates the session token, and any old open browser may require reauthentication.
- Source version/current legal applicability remain unverified; this operational service does not improve semantic ranking or close Issue #97 / KB03 Gate 2.
- VPS Production HEAD `daacbb4557e17790fdef18e492d5b83f4fcf7a23` previously differed from GitHub `main` `2a1aad8e6b740a0b28ea1cb3e07107fb2b8e7c46`; this is a **separate read-only audit**. Do not change Production for this PR.

GitHub is code Source of Truth; Google Drive is decision/document Source of Truth.
